"""
Low-friction consent: install-time acknowledgement, household acknowledgement, consent at
pod save, stale notices. Real assembled app, SQLite per test, real gate.

These prove the code does what docs/PARENTAL_CONSENT.md says. Whether the
method or the custodian wording is legally sufficient is for counsel.
"""
import asyncio
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core import consent
from core.config import settings
from core.database import Base, ConsentRecord, get_db
from core.security import create_access_token
from core.student_keys import clear_cache

pytestmark = pytest.mark.real_consent

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def _h(role="parent"):
    return {"Authorization": f"Bearer {create_access_token({'sub': role, 'role': role})}"}


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from core.middleware import reset_rate_limiter
    reset_rate_limiter()
    yield
    reset_rate_limiter()


@pytest.fixture
def clock(monkeypatch):
    state = {"now": T0}
    monkeypatch.setattr(consent, "_now", lambda: state["now"])
    return state


@pytest.fixture
def ctx(monkeypatch, test_client_with_database_context):
    import main
    import core.database as database_module

    url = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/household.sqlite"

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
    with test_client_with_database_context(main.app, engine) as c:
        c.factory = factory
        yield c
        main.app.dependency_overrides.pop(get_db, None)
    clear_cache()


def _cfg(name):
    return {"student_name": name, "subjects": ["history"], "grade": "3", "grade_stage": "3-5"}


def _save(c, names, **extra):
    return c.post("/pod/configs", json={"configs": [_cfg(n) for n in names], **extra}, headers=_h())


def _transcript(c, name):
    body = {
        "student_name": name, "subjects": ["history"], "duration_minutes": 10,
        "messages": [{"role": "user", "content": "x", "timestamp": "2026-10-29T10:00:00Z"}],
    }
    return c.post(f"/transcripts/{name}", json=body, headers=_h("child"))


def _db(c, coro_fn):
    async def run():
        async with c.factory() as s:
            return await coro_fn(s)
    return asyncio.run(run())


def _records(c, name):
    async def q(s):
        r = await s.execute(select(ConsentRecord).where(ConsentRecord.student_name == name).order_by(ConsentRecord.id))
        return list(r.scalars())
    return _db(c, q)


# ── Install-time acknowledgement ────────────────────────────────────────────


def _ack(monkeypatch, *, hash_=None, at=None):
    monkeypatch.setattr(settings, "consent_install_ack_hash", consent.notice_hash() if hash_ is None else hash_)
    monkeypatch.setattr(settings, "consent_install_ack_at", (T0 - timedelta(days=1)).isoformat() if at is None else at)


@pytest.fixture(autouse=True)
def _no_ack_by_default(monkeypatch):
    monkeypatch.setattr(settings, "consent_install_ack_hash", "")
    monkeypatch.setattr(settings, "consent_install_ack_at", "")


def test_no_ack_means_refused_with_parent_action(ctx, clock):
    r = _transcript(ctx, "Emma")
    assert r.status_code == 403
    d = r.json()["detail"]
    assert d["error"] == "parental_consent_required" and d["parent_action"] == "open_parent_setup"


def test_valid_ack_permits_and_writes_one_ledger_row_at_the_ack_time(ctx, clock, monkeypatch):
    _ack(monkeypatch)
    assert _transcript(ctx, "Emma").status_code != 403
    assert _transcript(ctx, "Emma").status_code != 403
    recs = _records(ctx, "Emma")
    assert len(recs) == 1
    assert recs[0].method == "install_custodian_attestation"
    assert recs[0].notice_hash == consent.notice_hash()
    assert recs[0].granted_at.replace(tzinfo=timezone.utc) == T0 - timedelta(days=1)
    assert b"custodian" not in bytes(recs[0].parent_label_enc)  # stored encrypted


@pytest.mark.parametrize("label,kw", [
    ("wrong hash", {"hash_": "0" * 64}),
    ("empty hash", {"hash_": ""}),
    ("future time", {"at": "2026-11-01T12:10:00+00:00"}),
    ("empty time", {"at": ""}),
    ("unparseable time", {"at": "not-a-time"}),
    ("naive time", {"at": "2026-10-31T12:00:00"}),
])
def test_invalid_acks_do_not_permit(ctx, clock, monkeypatch, label, kw):
    _ack(monkeypatch, **kw)
    if label == "empty time":
        monkeypatch.setattr(settings, "consent_install_ack_at", "")
    assert _transcript(ctx, "Emma").status_code == 403, label
    assert _records(ctx, "Emma") == []


def test_ack_within_five_minutes_of_future_is_tolerated(ctx, clock, monkeypatch):
    _ack(monkeypatch, at="2026-11-01T12:04:00Z")
    assert _transcript(ctx, "Emma").status_code != 403


def test_ack_of_an_older_notice_is_not_valid(ctx, clock, monkeypatch):
    _ack(monkeypatch)
    monkeypatch.setattr(consent, "_NOTICE_BYTES", consent._NOTICE_BYTES + b"\nA new paragraph.\n")
    assert _transcript(ctx, "Emma").status_code == 403


def test_a_revoked_student_is_not_resurrected_by_the_ack(ctx, clock, monkeypatch):
    _ack(monkeypatch)
    assert _transcript(ctx, "Emma").status_code != 403
    assert ctx.post("/consent/Emma/revoke", json={}, headers=_h()).status_code == 200
    assert _transcript(ctx, "Emma").status_code == 403
    assert len(_records(ctx, "Emma")) == 1


def test_pause_still_applies_with_a_valid_ack(ctx, clock, monkeypatch):
    _ack(monkeypatch)
    ctx.post("/consent/Emma/pause", headers=_h())
    assert _transcript(ctx, "Emma").status_code == 423


def test_the_install_method_cannot_be_requested_through_the_api(ctx):
    r = ctx.post("/consent/Emma", json={"method": "install_custodian_attestation",
                                        "notice_hash": consent.notice_hash()}, headers=_h())
    assert r.status_code == 422 and r.json()["detail"]["error"] == "method_not_available"


def test_demo_role_is_not_gated(ctx, monkeypatch):
    import core.consent as cm
    calls = []

    async def spy(db, name):
        calls.append(name)

    monkeypatch.setattr(cm, "require_collection", spy)
    import routers.tutor as tutor_module

    async def _no_model(*a, **k):
        if False:
            yield

    monkeypatch.setattr(tutor_module, "stream_tutor_response", _no_model)
    import core.demo_code_session as dcs
    code = asyncio.run(dcs.generate_code(student_name="Ellie", grade="4"))
    body = {"session_config": _cfg("Demo"), "current_subject": "history", "child_message": "hi"}
    h = {"Authorization": f"Bearer {create_access_token({'sub': 'd', 'role': 'demo_code', 'code': code})}"}
    assert ctx.post("/tutor/chat", json=body, headers=h).status_code == 200
    assert calls == []


# ── Household ───────────────────────────────────────────────────────────────


def test_household_get_shape_without_ack(ctx, clock):
    _save(ctx, ["Emma", "Noah"])
    ctx.post("/consent/Noah", json={"notice_hash": consent.notice_hash()}, headers=_h())
    j = ctx.get("/household/consent", headers=_h()).json()
    assert set(j) == {"needs_consent", "install_ack", "notice_hash", "notice_version", "notice_text", "students"}
    assert j["install_ack"] is False and j["needs_consent"] is True
    assert j["notice_hash"] == consent.notice_hash()
    assert j["notice_version"] == consent.NOTICE_VERSION and j["notice_text"] == consent.NOTICE_TEXT
    assert j["students"] == [
        {"student_name": "Emma", "consented": False, "stale": False},
        {"student_name": "Noah", "consented": True, "stale": False},
    ]


def test_household_get_counts_ack_covered_students_but_not_revoked_ones(ctx, clock, monkeypatch):
    _save(ctx, ["Emma", "Noah"])
    _ack(monkeypatch)
    j = ctx.get("/household/consent", headers=_h()).json()
    assert j["install_ack"] is True and j["needs_consent"] is False
    assert all(s["consented"] and not s["stale"] for s in j["students"])
    assert _records(ctx, "Emma") == []  # reading status writes no ledger row
    _transcript(ctx, "Noah")
    ctx.post("/consent/Noah/revoke", json={}, headers=_h())
    j = ctx.get("/household/consent", headers=_h()).json()
    assert {s["student_name"]: s["consented"] for s in j["students"]} == {"Emma": True, "Noah": False}
    assert j["needs_consent"] is True


def test_household_post_grants_all_is_idempotent_and_checks_hash(ctx, clock):
    _save(ctx, ["Emma", "Noah"])
    bad = ctx.post("/household/consent", json={"notice_hash": "0" * 64, "parent_label": "Mum"}, headers=_h())
    assert bad.status_code == 409 and bad.json()["detail"]["error"] == "notice_changed"
    assert _records(ctx, "Emma") == []
    r = ctx.post("/household/consent", json={"notice_hash": consent.notice_hash(), "parent_label": "Mum"}, headers=_h())
    assert r.status_code == 201
    assert sorted(r.json()["granted"]) == ["Emma", "Noah"] and r.json()["already"] == []
    r2 = ctx.post("/household/consent", json={"notice_hash": consent.notice_hash()}, headers=_h())
    assert r2.json() == {"granted": [], "already": ["Emma", "Noah"], "refreshed": []}
    assert len(_records(ctx, "Emma")) == 1
    assert _records(ctx, "Emma")[0].method == "parent_attested_checkbox"


def test_stale_consent_blocks_collection_until_refreshed(ctx, clock, monkeypatch):
    _save(ctx, ["Emma"], consent_notice_hash=consent.notice_hash())
    old = consent.notice_hash()
    monkeypatch.setattr(consent, "_NOTICE_BYTES", consent._NOTICE_BYTES + b"\nEdited.\n")
    assert consent.notice_hash() != old
    j = ctx.get("/household/consent", headers=_h()).json()
    assert j["students"][0] == {"student_name": "Emma", "consented": False, "stale": True}
    assert j["needs_consent"] is True
    denied = _transcript(ctx, "Emma")
    assert denied.status_code == 403
    assert denied.json()["detail"]["error"] == "parental_consent_required"
    r = ctx.post("/household/consent", json={"notice_hash": consent.notice_hash()}, headers=_h())
    assert r.json()["refreshed"] == ["Emma"]
    recs = _records(ctx, "Emma")
    assert len(recs) == 2 and recs[0].revoked_at is not None and recs[1].revoked_at is None
    assert recs[0].notice_hash == old and recs[1].notice_hash == consent.notice_hash()
    assert ctx.get("/household/consent", headers=_h()).json()["needs_consent"] is False
    assert _transcript(ctx, "Emma").status_code != 403


def test_stale_direct_grant_rotates_ledger_and_restores_collection(ctx, clock, monkeypatch):
    _save(ctx, ["Emma"], consent_notice_hash=consent.notice_hash())
    old = consent.notice_hash()
    monkeypatch.setattr(consent, "_NOTICE_BYTES", consent._NOTICE_BYTES + b"\nRevised.\n")
    assert consent.notice_hash() != old
    assert _transcript(ctx, "Emma").status_code == 403
    r = ctx.post("/consent/Emma", json={"notice_hash": consent.notice_hash()}, headers=_h())
    assert r.status_code in (200, 201), r.text
    records = _records(ctx, "Emma")
    assert len(records) == 2
    assert records[0].revoked_at is not None
    assert records[1].notice_hash == consent.notice_hash()
    assert _transcript(ctx, "Emma").status_code != 403


def test_household_routes_are_parent_only(ctx):
    assert ctx.get("/household/consent", headers=_h("child")).status_code in (401, 403)
    assert ctx.post("/household/consent", json={"notice_hash": "x"}, headers=_h("child")).status_code in (401, 403)


def test_a_student_named_household_does_not_collide(ctx):
    r = ctx.get("/consent/household", headers=_h())
    assert r.status_code == 200 and "student_consented" in r.json()


# ── Consent at pod save ─────────────────────────────────────────────────────


def test_pod_save_with_correct_hash_records_consent(ctx, clock, monkeypatch):
    r = _save(ctx, ["Emma", "Noah"], consent_notice_hash=consent.notice_hash(), parent_label="Mum")
    assert r.status_code == 204
    assert len(_records(ctx, "Emma")) == 1 and len(_records(ctx, "Noah")) == 1
    _save(ctx, ["Emma"], consent_notice_hash=consent.notice_hash())  # idempotent
    assert len(_records(ctx, "Emma")) == 1
    assert _transcript(ctx, "Emma").status_code != 403


def test_pod_save_with_wrong_hash_is_409_and_saves_nothing(ctx):
    r = _save(ctx, ["Emma"], consent_notice_hash="f" * 64)
    assert r.status_code == 409 and r.json()["detail"]["error"] == "notice_changed"
    assert _records(ctx, "Emma") == []
    assert ctx.get("/pod/configs", headers=_h()).json() == []


def test_pod_save_without_hash_is_unchanged(ctx):
    assert _save(ctx, ["Emma"]).status_code == 204
    assert _records(ctx, "Emma") == []


# ── Settings ────────────────────────────────────────────────────────────────


def test_ack_settings_default_empty():
    from core.config import Settings
    assert Settings().consent_install_ack_hash == "" and Settings().consent_install_ack_at == ""
    assert not hasattr(Settings(), "consent_mode") and not hasattr(Settings(), "consent_grace_days")


def test_notice_hash_is_sha256_of_the_file_bytes():
    import hashlib
    assert consent.notice_hash() == hashlib.sha256(consent.NOTICE_PATH.read_bytes()).hexdigest()
    first = consent.NOTICE_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert first == f"Notice version: {consent.NOTICE_VERSION}"
