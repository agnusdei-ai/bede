"""Startup side of installation authorization: school import and inventory.
Real tables on SQLite; the license-server leg is observed at the HTTP seam."""
import asyncio
import tempfile
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core import installation_receipt as ir, installation_registry as reg, school_authorization as sa
from core.config import settings
from core.database import Base, InstallationInventory, PilotCampus, PilotCampusDataAuthorization as A
from tests import installation_helpers as h


@pytest.fixture
def factory(monkeypatch):
    url = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/reg.sqlite"

    async def _create():
        eng = create_async_engine(url, poolclass=NullPool)
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await eng.dispose()

    asyncio.run(_create())
    import core.encryption as enc
    if enc._DATA_KEY is None:
        from Crypto.Random import get_random_bytes
        monkeypatch.setattr(enc, "_DATA_KEY", get_random_bytes(32))
    monkeypatch.setattr(enc, "_INSTALL_ID", None)
    monkeypatch.setattr(settings, "license_server_url", "")
    yield async_sessionmaker(create_async_engine(url, poolclass=NullPool), expire_on_commit=False)
    ir.invalidate()


def run(factory, fn):
    async def go():
        async with factory() as s:
            return await fn(s)
    return asyncio.run(go())


def _campus(factory, cid=h.LOCATION):
    async def f(s):
        s.add(PilotCampus(id=cid, title="Campus"))
        await s.commit()
    run(factory, f)


def _auth_rows(factory, cid=h.LOCATION):
    async def f(s):
        return list((await s.execute(select(A).where(A.campus_id == cid))).scalars())
    return run(factory, f)


def test_verified_school_receipt_is_imported_once(factory, monkeypatch):
    h.install(monkeypatch, h.chain(h.school_record("verified")), location=h.LOCATION)
    _campus(factory)
    assert run(factory, reg.import_school_receipt) == "imported"
    assert run(factory, reg.import_school_receipt) == "already_imported"
    rows = _auth_rows(factory)
    assert len(rows) == 1 and rows[0].notice_hash == sa.notice_hash()
    assert rows[0].authorizer_role == "administrator"
    assert run(factory, lambda s: sa.is_authorized(s, h.LOCATION)) is True
    assert sa.authorizer_name(rows[0]) == "Sam Principal"


def test_startup_twice_creates_no_duplicate(factory, monkeypatch):
    h.install(monkeypatch, h.chain(h.school_record("verified")), location=h.LOCATION)
    _campus(factory)
    asyncio.run(reg.run_startup(factory))
    asyncio.run(reg.run_startup(factory))
    assert len(_auth_rows(factory)) == 1


def test_a_runtime_withdrawal_is_not_undone_by_a_restart(factory, monkeypatch):
    h.install(monkeypatch, h.chain(h.school_record("verified")), location=h.LOCATION)
    _campus(factory)
    run(factory, reg.import_school_receipt)
    run(factory, lambda s: sa.revoke(s, h.LOCATION, reason="x"))
    assert run(factory, reg.import_school_receipt) == "already_imported"
    assert run(factory, lambda s: sa.is_authorized(s, h.LOCATION)) is False


@pytest.mark.parametrize("make", [
    lambda: h.school_record("pending_verification"),
    lambda: h.school_record("withdrawn"),
    lambda: h.school_record("verified", delegation=None),
    lambda: h.school_record("verified", location="someone-else"),
    lambda: h.school_record("verified", notice={"file": "school_data_notice.txt", "version": "t", "sha256": "0" * 64}),
])
def test_invalid_or_incomplete_receipts_import_nothing(factory, monkeypatch, make):
    h.install(monkeypatch, h.chain(make()), location=h.LOCATION)
    _campus(factory)
    assert run(factory, reg.import_school_receipt) == "not_school_verified"
    assert _auth_rows(factory) == []


def test_tampered_school_chain_imports_nothing(factory, monkeypatch):
    recs = h.chain(h.school_record("pending_verification"))
    recs[0]["state"] = "verified"
    h.install(monkeypatch, recs, location=h.LOCATION)
    _campus(factory)
    assert run(factory, reg.import_school_receipt) == "not_school_verified"


def test_no_campus_row_imports_nothing(factory, monkeypatch):
    h.install(monkeypatch, h.chain(h.school_record("verified")), location=h.LOCATION)
    assert run(factory, reg.import_school_receipt) == "campus_absent"


def test_each_campus_is_scoped_separately(factory, monkeypatch):
    other = str(uuid.uuid4())
    h.install(monkeypatch, h.chain(h.school_record("verified")), location=h.LOCATION)
    _campus(factory)
    _campus(factory, other)
    run(factory, reg.import_school_receipt)
    assert len(_auth_rows(factory)) == 1 and _auth_rows(factory, other) == []
    assert run(factory, lambda s: sa.is_authorized(s, other)) is False


def test_a_family_receipt_imports_nothing_for_schools(factory, monkeypatch):
    h.verified_family(monkeypatch)
    _campus(factory)
    assert run(factory, reg.import_school_receipt) == "not_school_verified"


# ── Inventory ───────────────────────────────────────────────────────────────

def _inv(factory):
    async def f(s):
        return list((await s.execute(select(InstallationInventory))).scalars())
    return run(factory, f)


def test_verified_gets_one_inventory_row_offline(factory, monkeypatch):
    h.verified_family(monkeypatch)
    asyncio.run(reg.run_startup(factory))
    asyncio.run(reg.run_startup(factory))
    rows = _inv(factory)
    assert len(rows) == 1
    r = rows[0]
    assert r.mode == "family" and r.location_id is None and r.license_server_outcome == "offline"
    assert r.receipt_id == ir.current().receipt_id and r.install_id and r.registered_at


def test_school_inventory_carries_the_location(factory, monkeypatch):
    h.install(monkeypatch, h.chain(h.school_record("verified")), location=h.LOCATION)
    asyncio.run(reg.run_startup(factory))
    assert _inv(factory)[0].location_id == h.LOCATION


def test_unverified_receipts_are_not_registered(factory, monkeypatch):
    h.install(monkeypatch, h.chain(h.family_record("pending_verification")))
    asyncio.run(reg.run_startup(factory))
    assert _inv(factory) == []


def test_offline_makes_no_license_server_call(factory, monkeypatch):
    from core import license_heartbeat

    async def _boom(*a, **k):
        raise AssertionError("no outbound call expected")

    monkeypatch.setattr(license_heartbeat, "_post_json", _boom)
    h.verified_family(monkeypatch)
    assert asyncio.run(reg.run_startup(factory)) is None


@pytest.mark.parametrize("status,body,expected", [
    (200, {"status": "active"}, "registered"),
    (409, {"error": "activation_cap_reached"}, "cap_reached"),
])
def test_registration_reuses_activate_and_records_the_outcome(factory, monkeypatch, status, body, expected):
    from core import license_heartbeat, license_state

    calls = []

    async def _post(path, payload):
        calls.append((path, payload))
        return status, body

    monkeypatch.setattr(license_heartbeat, "_post_json", _post)
    monkeypatch.setattr(settings, "demo_pin", "")
    monkeypatch.setattr(settings, "license_server_url", "https://licenses.invalid")
    monkeypatch.setattr(settings, "license_key", "KEY-TEXT")
    monkeypatch.setattr(license_state, "refresh", lambda *a, **k: None)
    h.verified_family(monkeypatch)
    asyncio.run(reg.register_installation(factory))
    assert [c[0] for c in calls] == ["/v1/activate"]
    # The wire payload is exactly today's: no inventory fields added.
    assert set(calls[0][1]) == {"license_key", "install_id"}
    assert _inv(factory)[0].license_server_outcome == expected


def test_an_unreachable_license_server_is_recorded_not_fatal(factory, monkeypatch):
    import httpx
    from core import license_heartbeat

    async def _down(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(license_heartbeat, "_post_json", _down)
    monkeypatch.setattr(settings, "demo_pin", "")
    monkeypatch.setattr(settings, "license_server_url", "https://licenses.invalid")
    monkeypatch.setattr(settings, "license_key", "KEY-TEXT")
    h.verified_family(monkeypatch)
    asyncio.run(reg.register_installation(factory))
    assert _inv(factory)[0].license_server_outcome == "unreachable"
    assert ir.current().state == "verified"  # an outage changes no consent verdict


def test_the_heartbeat_module_was_not_changed_to_carry_inventory():
    import inspect
    from core import license_heartbeat
    src = inspect.getsource(license_heartbeat)
    for word in ("installation_inventory", "InstallationInventory", "receipt"):
        assert word not in src


def test_startup_is_wired_into_the_real_lifespan():
    import inspect, main
    assert "installation_registry.run_startup" in inspect.getsource(main.lifespan)
    assert "app.include_router(installation.router)" in inspect.getsource(main)
