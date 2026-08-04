"""NIST 800-63B §5.2.2 and 800-53 AC-7 on the one-time-code paths.

Both were already satisfied on the password paths (core/parent_lockout.py,
reached from login and step-up) and on the child PIN
(core/child_throttle.py). They were satisfied on none of the code paths:
POST /auth/recovery/verify had no limit at all, POST
/mfa/totp/authenticate/verify verified the code and 401'd without recording
anything, and POST /auth/elevate counted a wrong password but not a wrong
code. Each of those accepts a six-digit secret, which is exactly the case
§5.2.2 is written for.

The per-IP limiter is not a substitute, and this codebase already says so —
core/child_throttle.py's docstring notes it "keys on IP alone, which a LAN
attacker defeats trivially."

What these pin:

  1. The cost of guessing actually rises. A test that only checked "a
     counter incremented" would pass against a throttle that never delays.
  2. A real person fumbling a code pays nothing.
  3. The ceiling exists (§5.2.2 names 100) and lifts on its own. A ceiling
     needing an administrator to clear would be a denial of service aimed
     at the account-recovery flow, which is the last door in.
  4. The counters do not bleed into each other. Failed recovery attempts
     must not throttle an ordinary login, and vice versa.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select

from core import otp_throttle
from core.database import ParentLoginLockout

pytestmark = [pytest.mark.usefixtures("demo_db")]


@pytest_asyncio.fixture
async def db_session(demo_db):
    async with demo_db() as session:
        yield session


# ── The ladder itself (pure, so no test spends the wall-clock time) ──────

def test_the_first_few_failures_are_free():
    """A code that rolled over mid-typing, a glance at the wrong account.
    A parent must not be punished for any of that."""
    for n in range(1, otp_throttle.FREE_ATTEMPTS + 1):
        assert otp_throttle.delay_for(n) == 0.0


def test_the_cost_of_guessing_rises():
    """The property that makes this a throttle rather than a counter."""
    delays = [otp_throttle.delay_for(n) for n in range(otp_throttle.FREE_ATTEMPTS + 1, 12)]
    assert delays[0] > 0
    assert delays == sorted(delays), delays
    assert delays[-1] == otp_throttle.MAX_DELAY_SECONDS


def test_the_delay_is_capped_rather_than_unbounded():
    """An unbounded ladder stops throttling and starts holding connections
    open, which is a resource problem wearing a security costume."""
    assert otp_throttle.delay_for(10_000) == otp_throttle.MAX_DELAY_SECONDS


# ── Counting, and the §5.2.2 ceiling ────────────────────────────────────

@pytest.mark.asyncio
async def test_failures_accumulate_and_delay_grows(db_session):
    first = await otp_throttle.record_failure(db_session, otp_throttle.PURPOSE_TOTP)
    assert first == 0.0
    for _ in range(otp_throttle.FREE_ATTEMPTS):
        last = await otp_throttle.record_failure(db_session, otp_throttle.PURPOSE_TOTP)
    assert last > 0.0


@pytest.mark.asyncio
async def test_a_correct_code_clears_the_count(db_session):
    for _ in range(6):
        await otp_throttle.record_failure(db_session, otp_throttle.PURPOSE_TOTP)
    await otp_throttle.record_success(db_session, otp_throttle.PURPOSE_TOTP)

    assert await otp_throttle.record_failure(db_session, otp_throttle.PURPOSE_TOTP) == 0.0


@pytest.mark.asyncio
async def test_the_ceiling_refuses_further_attempts(db_session):
    """§5.2.2 caps consecutive failures on one account at 100."""
    assert await otp_throttle.check_blocked(db_session, otp_throttle.PURPOSE_RECOVERY) is None
    for _ in range(otp_throttle.CONSECUTIVE_FAILURE_CEILING):
        await otp_throttle.record_failure(db_session, otp_throttle.PURPOSE_RECOVERY)

    assert await otp_throttle.check_blocked(db_session, otp_throttle.PURPOSE_RECOVERY) is not None


@pytest.mark.asyncio
async def test_the_ceiling_lifts_without_an_administrator(db_session):
    """The emergency exit must reopen on its own. A ceiling that needed
    someone to clear it would let anyone keep a locked-out parent locked
    out permanently, at the exact moment they have no other way in."""
    for _ in range(otp_throttle.CONSECUTIVE_FAILURE_CEILING):
        await otp_throttle.record_failure(db_session, otp_throttle.PURPOSE_RECOVERY)

    row = await db_session.get(ParentLoginLockout, otp_throttle.PURPOSE_RECOVERY)
    assert row.locked_until is not None
    # It is a timestamp, not a flag — nothing but time is required.
    assert row.locked_until > row.updated_at


@pytest.mark.asyncio
async def test_a_success_clears_the_ceiling_too(db_session):
    for _ in range(otp_throttle.CONSECUTIVE_FAILURE_CEILING):
        await otp_throttle.record_failure(db_session, otp_throttle.PURPOSE_RECOVERY)
    await otp_throttle.record_success(db_session, otp_throttle.PURPOSE_RECOVERY)

    assert await otp_throttle.check_blocked(db_session, otp_throttle.PURPOSE_RECOVERY) is None


# ── The counters must stay independent ──────────────────────────────────

@pytest.mark.asyncio
async def test_recovery_failures_do_not_throttle_ordinary_login(db_session):
    """The same bug core/middleware.py's separate `auth_recovery` bucket
    exists to avoid, one layer up: the burst of failures that gets a parent
    into trouble must not also spend the budget of the flow that gets them
    back out."""
    for _ in range(otp_throttle.CONSECUTIVE_FAILURE_CEILING):
        await otp_throttle.record_failure(db_session, otp_throttle.PURPOSE_RECOVERY)

    assert await otp_throttle.check_blocked(db_session, otp_throttle.PURPOSE_TOTP) is None
    assert await otp_throttle.record_failure(db_session, otp_throttle.PURPOSE_TOTP) == 0.0


@pytest.mark.asyncio
async def test_each_purpose_gets_its_own_row(db_session):
    await otp_throttle.record_failure(db_session, otp_throttle.PURPOSE_TOTP)
    await otp_throttle.record_failure(db_session, otp_throttle.PURPOSE_RECOVERY)

    keys = {r.key for r in (await db_session.execute(select(ParentLoginLockout))).scalars().all()}
    assert {otp_throttle.PURPOSE_TOTP, otp_throttle.PURPOSE_RECOVERY} <= keys


@pytest.mark.asyncio
async def test_it_does_not_disturb_the_password_lockout(db_session):
    """core/parent_lockout.py keys the same table on "parent". These share a
    table and must not share a counter."""
    from core import parent_lockout

    for _ in range(otp_throttle.CONSECUTIVE_FAILURE_CEILING):
        await otp_throttle.record_failure(db_session, otp_throttle.PURPOSE_TOTP)

    assert await parent_lockout.check_locked(db_session) is None


# ── Survives a restart, which is the point of it being in the database ──

@pytest.mark.asyncio
async def test_the_count_is_not_held_in_memory(db_session):
    """An in-process counter would hand an attacker the reset: restart the
    container, start again from zero."""
    for _ in range(6):
        await otp_throttle.record_failure(db_session, otp_throttle.PURPOSE_TOTP)

    row = await db_session.get(ParentLoginLockout, otp_throttle.PURPOSE_TOTP)
    assert row is not None and row.failure_count == 6
