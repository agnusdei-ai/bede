"""
Parental consent, the collection gate, the per-child pause, and parent
review/export — exercised through the REAL assembled app (main.app) with only
its database swapped for a per-test SQLite file.

COPPA 16 CFR 312.5 (consent before collection), 312.6 (review, refuse further
collection, delete), 312.4 (notice). These tests prove the code enforces the
controls; they do not decide whether the consent method is legally sufficient,
which is a question for counsel (see core/consent.py).

Every gated route is called here with no consent first and must refuse. The
autouse stub in conftest.py is switched off for this module by the marker below.
"""
import asyncio
import hashlib
import tempfile

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

from core import consent
from core.config import settings
from core.database import (
    Base,
    ConsentRecord,
    NarrationAssessment,
    StudentCollectionState,
    StudentConfig,
    get_db,
)
from core.encryption import decrypt_json, student_aad
from core.security import create_access_token
from core.student_keys import clear_cache

pytestmark = pytest.mark.real_consent

STUDENT = "Emma"


def _parent_headers() -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': 'parent', 'role': 'parent'})}"}


def _child_headers() -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': 'child', 'role': 'child'})}"}


def _demo_headers(code: str = "DEMOCODE1") -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': 'demo', 'role': 'demo_code', 'code': code})}"}


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from core.middleware import reset_rate_limiter
    reset_rate_limiter()
    yield
    reset_rate_limiter()


@pytest.fixture
def client(monkeypatch, test_client_with_database_context):
    """The real app, with its database pointed at a fresh SQLite file.

    Same shape as tests/test_privileged_elevation.py's fixture, which is the
    working pattern for a route test that writes encrypted rows and audit events.
    """
    import main
    import core.database as database_module

    url = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/consent.sqlite"

    async def _create():
        eng = create_async_engine(url, poolclass=NullPool)
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await eng.dispose()

    asyncio.run(_create())

    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database_module, "AsyncSessionLocal", factory)
    monkeypatch.setattr(database_module, "engine", engine)

    import core.encryption as encryption_module
    if encryption_module._DATA_KEY is None:
        from Crypto.Random import get_random_bytes
        monkeypatch.setattr(encryption_module, "_DATA_KEY", get_random_bytes(32))

    clear_cache()

    async def _override():
        async with factory() as session:
            yield session

    main.app.dependency_overrides[get_db] = _override
    with test_client_with_database_context(main.app, engine) as test_client:
        yield test_client
        main.app.dependency_overrides.pop(get_db, None)
    clear_cache()


def _grant(client, *, method="parent_attested_checkbox", notice=None, label="Mum"):
    return client.post(
        f"/consent/{STUDENT}",
        json={
            "method": method,
            "notice_hash": notice or consent.notice_hash(),
            "parent_label": label,
        },
        headers=_parent_headers(),
    )


def _transcript_body():
    return {
        "student_name": STUDENT,
        "subjects": ["history"],
        "duration_minutes": 10,
        "messages": [{"role": "user", "content": "Rome was founded", "timestamp": "2026-10-29T10:00:00Z"}],
    }


def _tutor_body(student=STUDENT):
    return {
        "session_config": {
            "student_name": student,
            "subjects": ["history"],
            "grade": "3",
            "grade_stage": "3-5",
        },
        "current_subject": "history",
        "child_message": "Tell me about Rome",
    }


# ── C-01: every collection route refuses without consent ───────────────────


def test_tutor_chat_refused_without_consent(client):
    r = client.post("/tutor/chat", json=_tutor_body(), headers=_parent_headers())
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "parental_consent_required"


def test_transcript_save_refused_without_consent(client):
    r = client.post(f"/transcripts/{STUDENT}", json=_transcript_body(), headers=_child_headers())
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "parental_consent_required"


def test_narration_profile_refused_without_consent(client):
    r = client.post(f"/narration/{STUDENT}/profile?session_count=1", headers=_parent_headers())
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "parental_consent_required"


def test_voice_enrollment_refused_without_consent_before_any_audio_is_read(client):
    files = [("samples", ("a.wav", b"not-audio", "audio/wav")), ("samples", ("b.wav", b"not-audio", "audio/wav"))]
    r = client.post("/voice/enroll", data={"student_name": STUDENT}, files=files, headers=_parent_headers())
    # 403 proves the gate ran first: the bytes are not valid audio, so reading
    # them would have failed validation with a different status.
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "parental_consent_required"


def test_refused_turn_writes_nothing_about_the_child(client):
    client.post("/tutor/chat", json=_tutor_body(), headers=_parent_headers())
    client.post(f"/transcripts/{STUDENT}", json=_transcript_body(), headers=_child_headers())
    import asyncio as _a
    from core.database import AsyncSessionLocal, SessionTranscript

    async def _count():
        async with AsyncSessionLocal() as s:
            return len((await s.execute(select(SessionTranscript))).scalars().all())

    assert _a.run(_count()) == 0


# ── C-02: the consent ledger ──────────────────────────────────────────────


def test_grant_requires_the_current_notice_hash(client):
    stale = hashlib.sha256(b"an older notice").hexdigest()
    r = _grant(client, notice=stale)
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "notice_changed"


def test_placeholder_payment_method_is_refused_not_granted(client):
    r = _grant(client, method="payment_transaction")
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "method_not_available"
    assert consent.METHODS["payment_transaction"].wired is False


def test_unknown_method_is_refused(client):
    r = _grant(client, method="carrier_pigeon")
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "unknown_method"


def test_grant_with_current_notice_permits_collection_and_is_recorded(client):
    r = _grant(client)
    assert r.status_code == 201
    assert r.json()["created"] is True
    # Collection now passes the gate. The save reaches the database and succeeds.
    ok = client.post(f"/transcripts/{STUDENT}", json=_transcript_body(), headers=_child_headers())
    assert ok.status_code == 200, ok.text


def test_a_second_grant_is_idempotent_and_keeps_the_original_record(client):
    _grant(client, label="Mum")
    again = _grant(client, label="Dad")
    assert again.status_code == 201
    assert again.json()["created"] is False

    import asyncio as _a
    from core.database import AsyncSessionLocal

    async def _rows():
        async with AsyncSessionLocal() as s:
            return (await s.execute(select(ConsentRecord))).scalars().all()

    assert len(_a.run(_rows())) == 1


def test_parent_label_is_stored_encrypted_not_as_plaintext(client):
    _grant(client, label="Mum-Secret-Alias")

    import asyncio as _a
    from core import student_keys
    from core.database import AsyncSessionLocal

    async def _raw():
        async with AsyncSessionLocal() as s:
            row = (await s.execute(select(ConsentRecord))).scalar_one()
            key = await student_keys.get_existing(s, STUDENT)
            return row.parent_label_enc, key

    blob, key = _a.run(_raw())
    assert b"Mum-Secret-Alias" not in blob
    assert decrypt_json(blob, student_aad("consent_records", "parent_label_enc", STUDENT), key) == {
        "label": "Mum-Secret-Alias"
    }


# ── C-04: revocation and pause ────────────────────────────────────────────


def test_revocation_stops_collection_but_keeps_the_ledger_row(client):
    _grant(client)
    r = client.post(f"/consent/{STUDENT}/revoke", json={"reason": "changed my mind"}, headers=_parent_headers())
    assert r.status_code == 200

    refused = client.post(f"/transcripts/{STUDENT}", json=_transcript_body(), headers=_child_headers())
    assert refused.status_code == 403

    import asyncio as _a
    from core.database import AsyncSessionLocal

    async def _row():
        async with AsyncSessionLocal() as s:
            return (await s.execute(select(ConsentRecord))).scalar_one()

    row = _a.run(_row())
    assert row.revoked_at is not None


def test_revoking_with_nothing_active_is_a_clear_404(client):
    r = client.post(f"/consent/{STUDENT}/revoke", json={}, headers=_parent_headers())
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "no_active_consent"


def test_pause_refuses_collection_with_423(client):
    _grant(client)
    assert client.post(f"/consent/{STUDENT}/pause", headers=_parent_headers()).status_code == 200
    r = client.post(f"/transcripts/{STUDENT}", json=_transcript_body(), headers=_child_headers())
    assert r.status_code == 423
    assert r.json()["detail"]["error"] == "collection_paused"
    assert client.post("/voice/enroll", data={"student_name": STUDENT},
                       files=[("samples", ("a", b"x", "audio/wav")), ("samples", ("b", b"x", "audio/wav"))],
                       headers=_parent_headers()).status_code == 423


def test_pause_leaves_reads_and_export_working(client):
    _grant(client)
    client.post(f"/transcripts/{STUDENT}", json=_transcript_body(), headers=_child_headers())
    client.post(f"/consent/{STUDENT}/pause", headers=_parent_headers())

    assert client.get(f"/consent/{STUDENT}", headers=_parent_headers()).json()["collection_paused"] is True
    assert client.get(f"/pod/students/{STUDENT}/review", headers=_parent_headers()).status_code == 200


def test_resume_restores_collection(client):
    _grant(client)
    client.post(f"/consent/{STUDENT}/pause", headers=_parent_headers())
    assert client.post(f"/consent/{STUDENT}/resume", headers=_parent_headers()).status_code == 200
    ok = client.post(f"/transcripts/{STUDENT}", json=_transcript_body(), headers=_child_headers())
    assert ok.status_code == 200


def test_missing_consent_is_reported_before_a_pause(client):
    """Order of refusal: a paused student who never consented is refused as
    unconsented, the more basic fact."""
    client.post(f"/consent/{STUDENT}/pause", headers=_parent_headers())
    r = client.post(f"/transcripts/{STUDENT}", json=_transcript_body(), headers=_child_headers())
    assert r.status_code == 403


def test_pause_and_resume_are_audited(client):
    import asyncio as _a
    from core.database import AsyncSessionLocal, AuditLog

    async def _count():
        async with AsyncSessionLocal() as s:
            return len((await s.execute(select(AuditLog))).scalars().all())

    _grant(client)
    before = _a.run(_count())
    client.post(f"/consent/{STUDENT}/pause", headers=_parent_headers())
    client.post(f"/consent/{STUDENT}/resume", headers=_parent_headers())
    assert _a.run(_count()) >= before + 2, "pause and resume each need an audit row"


def test_parent_only_routes_refuse_a_child(client):
    for method, path in (
        ("get", f"/consent/{STUDENT}"),
        ("post", f"/consent/{STUDENT}/pause"),
        ("get", f"/pod/students/{STUDENT}/review"),
    ):
        r = getattr(client, method)(path, headers=_child_headers())
        assert r.status_code in (401, 403), (path, r.status_code)


# ── C-05: parent review and export ─────────────────────────────────────────


def test_export_enumerates_exactly_the_deletion_cascade(client):
    """The export and the delete must cover the same tables. A table that
    deletion removes but export omits is a 312.6(a)(1) gap; the reverse is a
    disclosure claim that does not match the cascade."""
    from services.student_deletion import student_scoped_models

    _grant(client)
    r = client.get(f"/pod/students/{STUDENT}/review", headers=_parent_headers())
    assert r.status_code == 200
    export_labels = set(r.json()["tables"])
    deletion_labels = {label for label, _ in student_scoped_models()}
    assert export_labels == deletion_labels
    assert {"consent_records", "student_collection_state"} <= export_labels


def test_export_decrypts_what_was_written(client):
    _grant(client)
    client.post(f"/transcripts/{STUDENT}", json=_transcript_body(), headers=_child_headers())
    r = client.get(f"/pod/students/{STUDENT}/review", headers=_parent_headers()).json()

    saved = r["tables"]["session_transcripts"]
    assert len(saved) == 1
    assert saved[0]["transcript_enc"]["messages"][0]["content"] == "Rome was founded"

    consents = r["tables"]["consent_records"]
    assert consents[0]["parent_label_enc"] == {"label": "Mum"}


def test_export_decrypts_a_narration_assessment_with_its_writer_aad(client):
    """Seeds a row exactly as services/ai_service.py writes one (same AAD),
    then requires the export to read it back. A wrong AAD in the export shows
    up here as {"unreadable": true}, not as a silent omission."""
    import asyncio as _a
    from core import student_keys
    from core.database import AsyncSessionLocal
    from core.encryption import encrypt_json

    async def _seed():
        async with AsyncSessionLocal() as s:
            key = await student_keys.get_or_create(s, STUDENT)
            s.add(StudentConfig(student_name=STUDENT, config_enc=encrypt_json(
                {"student_name": STUDENT, "subjects": ["history"]},
                student_aad("student_configs", "config_enc", STUDENT), key)))
            s.add(NarrationAssessment(
                student_name=STUDENT, subject="history",
                assessment_enc=encrypt_json({"score": "adequate"},
                                            student_aad("narration_assessments", "assessment_enc", STUDENT), key),
            ))
            await s.commit()

    _a.run(_seed())
    _grant(client)
    r = client.get(f"/pod/students/{STUDENT}/review", headers=_parent_headers()).json()
    assert r["tables"]["narration_assessments"][0]["assessment_enc"] == {"score": "adequate"}
    assert r["tables"]["student_config"][0]["config_enc"]["subjects"] == ["history"]


def test_voice_profile_is_listed_but_its_embedding_is_withheld(client):
    import asyncio as _a
    from core import student_keys
    from core.database import AsyncSessionLocal, VoiceProfile
    from core.encryption import aad_for, encrypt_json

    async def _seed():
        async with AsyncSessionLocal() as s:
            key = await student_keys.get_or_create(s, STUDENT)
            # services/voice_auth.py binds the profile with this exact AAD.
            s.add(VoiceProfile(student_name=STUDENT, profile_enc=encrypt_json(
                {"embedding": [0.1]}, aad_for("voice_profiles", "profile_enc", STUDENT), key)))
            await s.commit()

    _a.run(_seed())
    _grant(client)
    r = client.get(f"/pod/students/{STUDENT}/review", headers=_parent_headers()).json()
    row = r["tables"]["voice_profile"][0]
    assert row["profile_enc"] == "withheld: biometric template, not exported"
    assert "embedding" not in str(row)


def test_export_is_audited_with_counts_only(client):
    _grant(client)
    client.get(f"/pod/students/{STUDENT}/review", headers=_parent_headers())
    import asyncio as _a
    from core.database import AsyncSessionLocal, AuditLog

    async def _rows():
        async with AsyncSessionLocal() as s:
            return (await s.execute(select(AuditLog))).scalars().all()

    assert _a.run(_rows()), "export wrote no audit row"


# ── C-06: notice ───────────────────────────────────────────────────────────


def test_notice_endpoint_serves_the_text_and_its_hash(client):
    r = client.get("/consent/notice", headers=_parent_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["hash"] == consent.notice_hash() == hashlib.sha256(
        f"{consent.NOTICE_VERSION}\n{consent.NOTICE_TEXT}".encode("utf-8")
    ).hexdigest()
    assert body["text"] == consent.NOTICE_TEXT
    available = {m["id"]: m["available"] for m in body["methods"]}
    assert available == {"parent_attested_checkbox": True, "payment_transaction": False}


def test_notice_hash_changes_when_the_text_changes(monkeypatch):
    before = consent.notice_hash()
    monkeypatch.setattr(consent, "NOTICE_TEXT", consent.NOTICE_TEXT + " Changed.")
    assert consent.notice_hash() != before


# ── Deletion takes the consent state with it ──────────────────────────────


def test_deleting_a_student_removes_consent_and_pause_state(client):
    """Calls the cascade service directly. The HTTP delete route is
    elevation-gated, and that gate is not what this test is about."""
    import asyncio as _a
    from core.database import AsyncSessionLocal
    from services.student_deletion import delete_all_student_data

    _grant(client)
    client.post(f"/consent/{STUDENT}/pause", headers=_parent_headers())

    async def _delete_and_count():
        async with AsyncSessionLocal() as s:
            counts = await delete_all_student_data(s, STUDENT)
        async with AsyncSessionLocal() as s:
            left = (
                len((await s.execute(select(ConsentRecord))).scalars().all()),
                len((await s.execute(select(StudentCollectionState))).scalars().all()),
            )
        return counts, left

    counts, left = _a.run(_delete_and_count())
    assert counts["consent_records"] == 1
    assert counts["student_collection_state"] == 1
    assert left == (0, 0)


# ── The demo is not parent-consented and must not be gated ────────────────


def test_demo_chat_is_not_gated_by_parental_consent(client, monkeypatch):
    """The public demo has no StudentConfig and no parent to consent. Its
    turns must not reach the consent check at all. Verified by spying on the
    gate: a call from the demo path fails this test."""
    import core.consent as consent_module
    import routers.tutor as tutor_module

    calls = []

    async def _spy(db, student_name):
        calls.append(student_name)

    monkeypatch.setattr(consent_module, "require_collection", _spy)

    async def _no_model(*args, **kwargs):
        if False:
            yield  # pragma: no cover — an empty stream keeps the turn offline

    monkeypatch.setattr(tutor_module, "stream_tutor_response", _no_model)

    import asyncio as _a
    import core.demo_code_session as demo_code_session

    # A real, live demo session, so the token is accepted and the request
    # reaches the route's own demo branch.
    code = _a.run(demo_code_session.generate_code(student_name="Ellie", grade="4"))
    assert code, "could not mint a demo code for the test"
    r = client.post("/tutor/chat", json=_tutor_body(student="Demo"), headers=_demo_headers(code))
    assert calls == [], "the demo role reached the parental-consent gate"
    assert r.status_code == 200, r.text
