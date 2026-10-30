"""
Installation receipt (core/installation_receipt.py): state machine, tamper
evidence, and that ONLY a verified family receipt unlocks collection, through
the real consent.require_collection and the real /installation routes.
docs/INSTALLATION_AUTHORIZATION_FLOW.md.
"""
import asyncio
import json
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core import consent, installation_receipt as ir
from core.config import settings
from core.database import Base, ConsentRecord, get_db
from core.security import create_access_token
from core.student_keys import clear_cache
from tests import installation_helpers as h

pytestmark = pytest.mark.real_consent

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def _hd(role="parent"):
    return {"Authorization": f"Bearer {create_access_token({'sub': role, 'role': role})}"}


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(consent, "_now", lambda: T0)
    monkeypatch.setattr(settings, "consent_install_ack_hash", "")
    monkeypatch.setattr(settings, "consent_install_ack_at", "")
    yield
    ir.invalidate()


@pytest.fixture
def ctx(monkeypatch, test_client_with_database_context):
    import main
    import core.database as database_module

    url = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/inst.sqlite"

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
    import core.encryption as enc
    if enc._DATA_KEY is None:
        from Crypto.Random import get_random_bytes
        monkeypatch.setattr(enc, "_DATA_KEY", get_random_bytes(32))
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


def _transcript(c, name="Emma"):
    body = {"student_name": name, "subjects": ["history"], "duration_minutes": 10,
            "messages": [{"role": "user", "content": "x", "timestamp": "2026-10-29T10:00:00Z"}]}
    return c.post(f"/transcripts/{name}", json=body, headers=_hd("child"))


def _records(c, name="Emma"):
    async def run():
        async with c.factory() as s:
            return list((await s.execute(select(ConsentRecord).where(ConsentRecord.student_name == name))).scalars())
    return asyncio.run(run())


# ── State machine ───────────────────────────────────────────────────────────

def test_no_file_is_none_and_closed(monkeypatch):
    h.no_receipt(monkeypatch)
    st = ir.current()
    assert st.state == "none" and not st.processing_enabled


@pytest.mark.parametrize("state", ["pending_verification", "withdrawn", "superseded", "invalid"])
def test_every_state_but_verified_leaves_processing_off(monkeypatch, state):
    h.install(monkeypatch, h.chain(h.family_record(state)))
    st = ir.current()
    assert st.state == state and not st.processing_enabled


def test_a_complete_verified_family_receipt_is_verified(monkeypatch):
    h.verified_family(monkeypatch)
    st = ir.current()
    assert st.state == "verified" and st.chain_valid and st.family_verified


def test_latest_record_wins_across_the_chain(monkeypatch):
    rid = "r-1"
    h.install(monkeypatch, h.chain(
        h.family_record("pending_verification", receipt_id=rid),
        h.family_record("verified", receipt_id=rid),
        h.family_record("withdrawn", receipt_id=rid)))
    assert ir.current().state == "withdrawn"


def test_a_withdrawn_receipt_cannot_be_resurrected_by_appending_verified(monkeypatch):
    rid = "r-1"
    h.install(monkeypatch, h.chain(
        h.family_record("verified", receipt_id=rid), h.family_record("withdrawn", receipt_id=rid),
        h.family_record("verified", receipt_id=rid)))
    st = ir.current()
    assert st.state == "invalid" and "illegal_transition" in st.reasons[0]


def test_a_new_receipt_id_after_withdrawal_is_a_fresh_authorization(monkeypatch):
    h.install(monkeypatch, h.chain(
        h.family_record("withdrawn", receipt_id="a"), h.family_record("verified", receipt_id="b")))
    assert ir.current().state == "verified"


def test_verified_without_a_completed_verification_method_is_invalid(monkeypatch):
    h.install(monkeypatch, h.chain(h.family_record(
        "verified", verification={"method": None, "completed_at": None})))
    st = ir.current()
    assert st.state == "invalid" and "verification_incomplete" in st.reasons


# ── Tamper ──────────────────────────────────────────────────────────────────

def test_editing_a_field_invalidates(monkeypatch):
    recs = h.chain(h.family_record("pending_verification"))
    recs[0]["state"] = "verified"  # hand-edit, hash untouched
    h.install(monkeypatch, recs)
    st = ir.current()
    assert st.state == "invalid" and not st.chain_valid and not st.processing_enabled


def test_breaking_the_chain_invalidates(monkeypatch):
    recs = h.chain(h.family_record("pending_verification", receipt_id="x"),
                   h.family_record("verified", receipt_id="x"))
    h.install(monkeypatch, [recs[1]])  # first record removed
    st = ir.current()
    assert st.state == "invalid" and "chain_broken" in st.reasons[0]


def test_reordering_the_chain_invalidates(monkeypatch):
    recs = h.chain(h.family_record("pending_verification", receipt_id="x"),
                   h.family_record("verified", receipt_id="x"))
    h.install(monkeypatch, [recs[1], recs[0]])
    assert ir.current().state == "invalid"


def test_swapping_in_a_different_notice_hash_invalidates(monkeypatch):
    h.install(monkeypatch, h.chain(h.family_record("verified", notice_sha="0" * 64)))
    st = ir.current()
    assert st.state == "invalid" and "notice_changed" in st.reasons


def test_a_notice_edited_after_verification_makes_it_invalid(monkeypatch):
    h.verified_family(monkeypatch)
    assert ir.current().state == "verified"
    monkeypatch.setattr(consent, "_NOTICE_BYTES", consent._NOTICE_BYTES + b"\nnew\n")
    assert ir.current().state == "invalid"


def test_garbage_and_wrong_schema_are_invalid_not_a_crash(monkeypatch):
    d = h.no_receipt(monkeypatch)
    (d / "installation_receipt.json").write_text("{not json")
    assert ir.current().state == "invalid"
    ir.invalidate()
    h.install(monkeypatch, [dict(h.family_record("verified"), schema="other")])
    assert ir.current().state == "invalid"


def test_a_school_receipt_for_another_location_is_invalid(monkeypatch):
    h.install(monkeypatch, h.chain(h.school_record("verified", location="other-campus")),
              location=h.LOCATION)
    st = ir.current()
    assert st.state == "invalid" and "location_mismatch" in st.reasons


def test_school_verified_requires_delegation_and_role(monkeypatch):
    h.install(monkeypatch, h.chain(h.school_record("verified", delegation=None)), location=h.LOCATION)
    assert ir.current().state == "invalid"
    h.install(monkeypatch, h.chain(h.school_record("verified", role="janitor")), location=h.LOCATION)
    assert ir.current().state == "invalid"
    h.install(monkeypatch, h.chain(h.school_record("verified")), location=h.LOCATION)
    assert ir.current().school_verified


# ── Collection: invocation through the real gate ────────────────────────────

def test_verified_family_receipt_unlocks_collection_and_writes_one_row(ctx, monkeypatch):
    h.verified_family(monkeypatch)
    assert _transcript(ctx).status_code != 403
    assert _transcript(ctx).status_code != 403
    recs = _records(ctx)
    assert len(recs) == 1 and recs[0].method == consent.INSTALL_ACK_METHOD


@pytest.mark.parametrize("state", ["pending_verification", "invalid", "withdrawn", "superseded"])
def test_other_states_do_not_unlock_collection(ctx, monkeypatch, state):
    h.install(monkeypatch, h.chain(h.family_record(state)))
    assert _transcript(ctx).status_code == 403
    assert _records(ctx) == []


def test_no_receipt_does_not_unlock_collection(ctx, monkeypatch):
    h.no_receipt(monkeypatch)
    assert _transcript(ctx).status_code == 403


def test_the_legacy_env_ack_alone_cannot_unlock(ctx, monkeypatch):
    h.no_receipt(monkeypatch)
    monkeypatch.setattr(settings, "consent_install_ack_hash", consent.notice_hash())
    monkeypatch.setattr(settings, "consent_install_ack_at", "2026-10-31T12:00:00Z")
    assert _transcript(ctx).status_code == 403
    h.install(monkeypatch, h.chain(h.family_record("pending_verification")))
    assert _transcript(ctx).status_code == 403


def test_a_school_receipt_does_not_cover_household_children(ctx, monkeypatch):
    h.install(monkeypatch, h.chain(h.school_record("verified")), location=h.LOCATION)
    assert _transcript(ctx).status_code == 403


def test_tampering_after_unlock_closes_the_gate_again(ctx, monkeypatch):
    d = h.verified_family(monkeypatch)
    assert _transcript(ctx, "Noah").status_code != 403
    # A child with no consent row yet is only covered while the receipt holds.
    recs = json.loads((d / "installation_receipt.json").read_text())
    recs[0]["accepted_at"] = "2026-10-30T12:00:00Z"
    (d / "installation_receipt.json").write_text(json.dumps(recs))
    assert ir.current().state == "invalid"
    assert _transcript(ctx, "Emma").status_code == 403


def test_a_withdrawn_receipt_stops_a_not_yet_covered_child(ctx, monkeypatch):
    h.verified_family(monkeypatch)
    r = ctx.post("/installation/withdraw", headers=_hd())
    assert r.status_code == 200 and r.json()["state"] == "withdrawn"
    assert _transcript(ctx, "Emma").status_code == 403


# ── Routes ──────────────────────────────────────────────────────────────────

def test_status_reports_state_and_enabled(ctx, monkeypatch):
    h.install(monkeypatch, h.chain(h.family_record("pending_verification")))
    j = ctx.get("/installation/status", headers=_hd()).json()
    assert j["state"] == "pending_verification" and j["processing_enabled"] is False
    assert j["chain_valid"] is True and j["verification_method_available"] is False
    h.verified_family(monkeypatch)
    assert ctx.get("/installation/status", headers=_hd()).json()["processing_enabled"] is True


def test_status_refuses_a_child_and_anonymous(ctx):
    assert ctx.get("/installation/status", headers=_hd("child")).status_code in (401, 403)
    assert ctx.get("/installation/status").status_code in (401, 403)


@pytest.mark.parametrize("path", ["/installation/verification/start", "/installation/verification/complete"])
def test_verification_is_unavailable_and_changes_nothing(ctx, monkeypatch, path):
    h.install(monkeypatch, h.chain(h.family_record("pending_verification")))
    r = ctx.post(path, headers=_hd())
    assert r.status_code == 409 and r.json()["error"] == "verification_method_unavailable"
    assert ir.current().state == "pending_verification"
    assert _transcript(ctx).status_code == 403


def test_withdraw_appends_without_touching_the_original_file(ctx, monkeypatch):
    d = h.verified_family(monkeypatch)
    before = (d / "installation_receipt.json").read_bytes()
    r = ctx.post("/installation/withdraw", headers=_hd())
    assert r.status_code == 200 and r.json()["processing_enabled"] is False
    assert (d / "installation_receipt.json").read_bytes() == before
    st = ir.current()
    assert st.state == "withdrawn" and st.chain_valid and st.record_count == 2
    assert ctx.post("/installation/withdraw", headers=_hd()).status_code == 409


def test_withdraw_is_parent_only_for_family(ctx, monkeypatch):
    h.verified_family(monkeypatch)
    assert ctx.post("/installation/withdraw", headers=_hd("child")).status_code in (401, 403)
    assert ir.current().state == "verified"


def test_withdraw_reports_failure_rather_than_pretending(ctx, monkeypatch):
    h.verified_family(monkeypatch)
    monkeypatch.setattr(settings, "installation_receipt_append_path", "/proc/nope/append.jsonl")
    r = ctx.post("/installation/withdraw", headers=_hd())
    assert r.status_code == 503 and r.json()["error"] == "withdrawal_not_recorded"
    assert ir.current().state == "verified"


def test_withdraw_on_a_broken_chain_is_refused(ctx, monkeypatch):
    recs = h.chain(h.family_record("verified"))
    recs[0]["accepted_at"] = "2020-01-01T00:00:00Z"
    h.install(monkeypatch, recs)
    assert ctx.post("/installation/withdraw", headers=_hd()).status_code == 409


# ── Outages never change consent (owner constraint) ─────────────────────────

def test_a_license_server_outage_changes_no_receipt_state(ctx, monkeypatch):
    """The consent verdict reads the local receipt and nothing else."""
    import httpx
    from core import license_heartbeat

    async def _down(*a, **k):
        raise httpx.ConnectError("outage")

    monkeypatch.setattr(license_heartbeat, "_post_json", _down)
    monkeypatch.setattr(settings, "demo_pin", "")
    monkeypatch.setattr(settings, "license_server_url", "https://licenses.invalid")
    h.verified_family(monkeypatch)
    assert ir.current().state == "verified" and _transcript(ctx).status_code != 403
    h.install(monkeypatch, h.chain(h.family_record("pending_verification")))
    assert ir.current().state == "pending_verification" and _transcript(ctx, "Noah").status_code == 403


def test_consent_and_receipt_modules_make_no_network_call():
    import inspect
    for mod in (ir, consent):
        src = inspect.getsource(mod)
        assert "httpx" not in src and "license_heartbeat" not in src
