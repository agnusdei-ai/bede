"""
core/device_registry.py — P9 device revocation (Option C,
docs/DEVICE_IDENTITY_DESIGN.md). Mirrors tests/test_parent_credential.py's
structure since the module mirrors that one's shape (a DB-backed fact,
cached in-process, periodically re-synced for multi-replica staleness).
"""
import pytest
import pytest_asyncio

from core import device_registry
from core.database import DeviceRecord

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


@pytest_asyncio.fixture
async def db_session(demo_db):
    async with demo_db() as session:
        yield session


@pytest.fixture(autouse=True)
def _reset_cache():
    """Module-level cached revoked-set would otherwise leak between tests."""
    device_registry._set_cache(set())
    yield
    device_registry._set_cache(set())


async def test_a_never_seen_device_is_not_revoked():
    assert device_registry.is_revoked("never-seen") is False


async def test_a_device_with_no_id_is_never_revoked():
    """No device_id claim (a token issued before this existed, or a caller
    driving the API directly with no device_id sent) must never be treated
    as revoked -- there is nothing to revoke."""
    assert device_registry.is_revoked(None) is False
    assert device_registry.is_revoked("") is False


async def test_touch_creates_a_new_device_record(db_session):
    await device_registry.touch(db_session, "dev-1", "parent", "Mozilla/5.0 Test")
    row = await db_session.get(DeviceRecord, "dev-1")
    assert row is not None
    assert row.last_role == "parent"
    assert row.last_user_agent == "Mozilla/5.0 Test"
    assert row.revoked is False
    assert row.first_seen_at == row.last_seen_at


async def test_touch_updates_an_existing_record_rather_than_duplicating(db_session):
    await device_registry.touch(db_session, "dev-1", "parent", "first UA")
    first_seen = (await db_session.get(DeviceRecord, "dev-1")).first_seen_at

    await device_registry.touch(db_session, "dev-1", "child", "second UA")
    row = await db_session.get(DeviceRecord, "dev-1")
    assert row.last_role == "child"
    assert row.last_user_agent == "second UA"
    # first_seen_at never moves once set -- it answers "when did this
    # device first appear", not "when was it last touched".
    assert row.first_seen_at == first_seen


async def test_touch_truncates_an_oversized_user_agent(db_session):
    huge_ua = "X" * 5000
    await device_registry.touch(db_session, "dev-1", "parent", huge_ua)
    row = await db_session.get(DeviceRecord, "dev-1")
    assert len(row.last_user_agent) == 200


async def test_touch_never_un_revokes_a_device(db_session):
    await device_registry.touch(db_session, "dev-1", "parent", "ua")
    await device_registry.revoke(db_session, "dev-1")
    await device_registry.touch(db_session, "dev-1", "parent", "ua again")
    row = await db_session.get(DeviceRecord, "dev-1")
    assert row.revoked is True


async def test_revoke_returns_false_for_an_unknown_device(db_session):
    assert await device_registry.revoke(db_session, "never-existed") is False


async def test_revoke_marks_the_row_and_stamps_revoked_at(db_session):
    await device_registry.touch(db_session, "dev-1", "parent", "ua")
    ok = await device_registry.revoke(db_session, "dev-1")
    assert ok is True
    row = await db_session.get(DeviceRecord, "dev-1")
    assert row.revoked is True
    assert row.revoked_at is not None


async def test_revoke_updates_the_in_process_cache_immediately(db_session):
    await device_registry.touch(db_session, "dev-1", "parent", "ua")
    assert device_registry.is_revoked("dev-1") is False
    await device_registry.revoke(db_session, "dev-1")
    assert device_registry.is_revoked("dev-1") is True


async def test_list_devices_orders_newest_seen_first(db_session):
    await device_registry.touch(db_session, "old", "parent", "ua")
    await device_registry.touch(db_session, "new", "parent", "ua")
    # Force a strictly later last_seen_at for "new" — two touches in the
    # same test can land in the same microsecond on a fast machine.
    row = await db_session.get(DeviceRecord, "new")
    from datetime import datetime, timedelta, timezone
    row.last_seen_at = datetime.now(timezone.utc) + timedelta(seconds=5)
    await db_session.commit()

    devices = await device_registry.list_devices(db_session)
    assert [d.device_id for d in devices] == ["new", "old"]


# ── Multi-replica staleness bound ───────────────────────────────────────────

async def test_refresh_from_db_syncs_the_cache_to_existing_revocations(db_session):
    await device_registry.touch(db_session, "dev-1", "parent", "ua")
    await device_registry.revoke(db_session, "dev-1")
    device_registry._set_cache(set())  # simulate a fresh process that hasn't synced yet
    assert device_registry.is_revoked("dev-1") is False
    await device_registry.refresh_from_db(db_session)
    assert device_registry.is_revoked("dev-1") is True


async def test_refresh_from_db_with_nothing_revoked_is_an_empty_set(db_session):
    await device_registry.touch(db_session, "dev-1", "parent", "ua")
    await device_registry.refresh_from_db(db_session)
    assert device_registry.is_revoked("dev-1") is False


async def test_periodic_refresh_picks_up_a_sibling_replicas_revocation(db_session):
    """The replication landmine this bound exists for -- see
    core/parent_credential.py's docstring, which this mirrors exactly.
    Replica A revokes a device; replica B is already running with a stale
    cache that doesn't know about it yet. One refresh cycle closes the gap.
    """
    await device_registry.touch(db_session, "dev-1", "parent", "ua")

    # Replica B's view: started before the revocation.
    device_registry._set_cache(set())
    assert device_registry.is_revoked("dev-1") is False

    # Replica A revokes against the shared database.
    await device_registry.revoke(db_session, "dev-1")

    # Replica B still holds its stale (empty) cache -- this is the window
    # the refresh interval bounds, not something it eliminates.
    device_registry._set_cache(set())
    assert device_registry.is_revoked("dev-1") is False

    await device_registry.refresh_from_db(db_session)
    assert device_registry.is_revoked("dev-1") is True


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
async def test_refresh_interval_is_short_enough_to_bound_a_takeover():
    assert 0 < device_registry._REFRESH_INTERVAL_SECONDS <= 30
