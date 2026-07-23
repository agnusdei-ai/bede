"""
core/parent_lockout.py — DB-backed account lockout for the parent role.
The piece the E009 anomaly watch (core/audit.py) never provided: it
alerts after repeated failures, but never actually blocks the next
attempt. DB-backed specifically so a container restart can't reset an
attacker's progress toward the threshold.
"""
import pytest
import pytest_asyncio

from core import parent_lockout

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


@pytest_asyncio.fixture
async def db_session(demo_db):
    async with demo_db() as session:
        yield session


async def test_not_locked_with_no_prior_failures(db_session):
    assert await parent_lockout.check_locked(db_session) is None


async def test_locks_out_exactly_at_the_threshold(db_session):
    for _ in range(parent_lockout.FAILURE_THRESHOLD - 1):
        triggered = await parent_lockout.record_failure(db_session)
        assert triggered is None
        assert await parent_lockout.check_locked(db_session) is None

    triggered = await parent_lockout.record_failure(db_session)
    assert triggered is not None
    assert await parent_lockout.check_locked(db_session) == triggered


async def test_successful_login_clears_accumulated_failures(db_session):
    for _ in range(parent_lockout.FAILURE_THRESHOLD - 2):
        await parent_lockout.record_failure(db_session)

    await parent_lockout.record_success(db_session)

    # Back to a clean slate — needs the full threshold again, not just 2 more.
    for _ in range(parent_lockout.FAILURE_THRESHOLD - 1):
        triggered = await parent_lockout.record_failure(db_session)
        assert triggered is None
    triggered = await parent_lockout.record_failure(db_session)
    assert triggered is not None


async def test_record_success_is_a_no_op_with_nothing_to_clear(db_session):
    await parent_lockout.record_success(db_session)  # must not raise
    assert await parent_lockout.check_locked(db_session) is None


async def test_expired_lockout_reads_as_unlocked(db_session, monkeypatch):
    for _ in range(parent_lockout.FAILURE_THRESHOLD):
        await parent_lockout.record_failure(db_session)
    assert await parent_lockout.check_locked(db_session) is not None

    # Simulate time passing well beyond the lockout duration.
    import datetime as real_datetime
    from core import parent_lockout as module

    class _FutureDatetime(real_datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            base = real_datetime.datetime.now(tz)
            return base + real_datetime.timedelta(seconds=module.LOCKOUT_DURATION_SECONDS + 1)

    monkeypatch.setattr(module, "datetime", _FutureDatetime)
    assert await parent_lockout.check_locked(db_session) is None


async def test_a_failure_long_after_the_last_one_resets_the_window(db_session, monkeypatch):
    """A stale failure count (nothing failed in FAILURE_WINDOW_SECONDS)
    must not accumulate toward a lockout an occasional typo over months
    should never trigger."""
    for _ in range(parent_lockout.FAILURE_THRESHOLD - 1):
        await parent_lockout.record_failure(db_session)

    import datetime as real_datetime
    from core import parent_lockout as module

    class _FutureDatetime(real_datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            base = real_datetime.datetime.now(tz)
            return base + real_datetime.timedelta(seconds=module.FAILURE_WINDOW_SECONDS + 1)

    monkeypatch.setattr(module, "datetime", _FutureDatetime)

    # This single failure should NOT trigger a lockout — the prior window
    # is stale, so the count restarts at 1, not FAILURE_THRESHOLD.
    triggered = await parent_lockout.record_failure(db_session)
    assert triggered is None
