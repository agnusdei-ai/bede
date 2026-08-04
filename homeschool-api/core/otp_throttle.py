"""
Throttling for the one-time-code paths — TOTP at login completion, TOTP at
step-up, and account recovery.

NIST SP 800-63B §5.2.2 requires a verifier to rate-limit authentication
attempts and to cap consecutive failures on a single account at 100. NIST SP
800-53 AC-7 requires the same thing in different words. Both were satisfied
on the two PASSWORD paths (core/parent_lockout.py, via routers/auth.py's
login and elevate) and on the child PIN (core/child_throttle.py), and on
none of the code paths:

  * POST /auth/recovery/verify        no limit of any kind
  * POST /mfa/totp/verify             verified the code, 401'd, recorded nothing
  * POST /auth/elevate                counted a wrong PASSWORD, not a wrong code

Each of those accepts a six-digit secret, which is the case §5.2.2 is
written for. The per-IP limiter in core/middleware.py is not a substitute,
and this codebase already says why: core/child_throttle.py's own docstring
notes it "keys on IP alone, which a LAN attacker defeats trivially." The
same reasoning applies to an attacker on the internet with a handful of
addresses.

WHY THIS IS NOT core/parent_lockout.py REUSED WHOLESALE

parent_lockout refuses outright for 15 minutes past its threshold, which is
right for a password: the parent has account recovery as a way back in.
Applying that shape to recovery itself would put a hard lock on the
emergency exit — anyone able to send requests could keep a locked-out
parent permanently locked out, and the recovery flow is the last door.
That is a denial-of-service primitive aimed at the worst possible moment.

So the primary instrument here is escalating DELAY, the shape
core/child_throttle.py already argues for. The first few failures cost
nothing, so a parent fumbling a code that has just rolled over notices
nothing. Sustained guessing gets expensive in wall-clock time regardless of
how many source addresses it comes from, because the count is keyed on the
credential being attacked rather than on where the attempt came from.

A ceiling still exists, because §5.2.2 requires one: past
CONSECUTIVE_FAILURE_CEILING attempts inside the window, further attempts
are refused until the window rolls. Reaching it is not something a real
parent does — with the delay ladder below, 100 consecutive failures takes
roughly three quarters of an hour of uninterrupted wrong codes — and the
refusal expires on its own rather than needing an administrator, so the
emergency exit reopens without anyone's help.

DB-backed, reusing ParentLoginLockout's table under different keys. Same
reason parent_lockout is: an in-process counter resets when the container
restarts, and "restart to clear the throttle" would hand the attacker the
reset. It needs no new table because that model was already keyed by a
string rather than a hardcoded singleton.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import ParentLoginLockout

# One counter per credential under attack. Deliberately separate: burning
# through recovery attempts must not also throttle an ordinary login, and a
# fumbled TOTP at the login screen must not eat into the recovery budget a
# locked-out parent is about to need. That second point is the same bug
# core/middleware.py's `auth_recovery` bucket exists to avoid, one layer up.
PURPOSE_TOTP = "otp_totp"
PURPOSE_RECOVERY = "otp_recovery"

# A code that just rolled over, a mistyped digit, a glance at the wrong
# account in the authenticator app. None of that should cost a parent
# anything, so the ladder starts flat.
FREE_ATTEMPTS = 3

# Seconds of delay applied BEFORE responding to a failure, indexed by
# failures beyond the free allowance. Capped rather than unbounded: a delay
# long enough to matter to an attacker is already long enough, and an
# unbounded ladder eventually just holds a connection open.
_DELAY_LADDER = (1, 2, 4, 8, 15, 30)
MAX_DELAY_SECONDS = _DELAY_LADDER[-1]

# §5.2.2's explicit number. Refusal, not delay, and it lifts when the
# window rolls — see the module docstring on why this must not need an
# administrator to clear.
CONSECUTIVE_FAILURE_CEILING = 100

# Consecutive means consecutive. Nothing failing for this long is the same
# evidence a success is: whatever was happening is no longer happening.
FAILURE_WINDOW_SECONDS = 30 * 60


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite (the test engine) drops tzinfo that Postgres round-trips.
    Everything written here is UTC — same helper, same reason, as
    core/parent_lockout.py's."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def delay_for(failure_count: int) -> float:
    """Seconds to wait before answering the NEXT failure. Pure, so the
    ladder can be asserted without sleeping through it."""
    beyond_free = failure_count - FREE_ATTEMPTS
    if beyond_free <= 0:
        return 0.0
    return float(_DELAY_LADDER[min(beyond_free, len(_DELAY_LADDER)) - 1])


async def check_blocked(db: AsyncSession, purpose: str) -> Optional[datetime]:
    """When the ceiling has been hit, the moment it lifts. None otherwise.

    Call before verifying, so a blocked attempt never reaches the
    comparison — the point of a ceiling is that guesses stop being counted
    at all, not that they stop being reported."""
    row = await db.get(ParentLoginLockout, purpose)
    if row is None or row.locked_until is None:
        return None
    until = _aware(row.locked_until)
    if until <= datetime.now(timezone.utc):
        return None
    return until


async def record_failure(db: AsyncSession, purpose: str) -> float:
    """Count a wrong code and return how long to wait before answering.

    The caller sleeps rather than this function, so the delay is visible at
    the call site and a test can assert the ladder without spending the
    time.
    """
    now = datetime.now(timezone.utc)
    row = await db.get(ParentLoginLockout, purpose)
    if row is None:
        row = ParentLoginLockout(key=purpose, failure_count=0, locked_until=None)
        db.add(row)

    updated_at = _aware(row.updated_at)
    blocked_until = _aware(row.locked_until)
    stale = updated_at is not None and (now - updated_at).total_seconds() > FAILURE_WINDOW_SECONDS
    expired = blocked_until is not None and blocked_until <= now
    if stale or expired:
        row.failure_count = 0
        row.locked_until = None

    row.failure_count += 1
    if row.failure_count >= CONSECUTIVE_FAILURE_CEILING:
        row.locked_until = now + timedelta(seconds=FAILURE_WINDOW_SECONDS)

    delay = delay_for(row.failure_count)
    await db.commit()
    return delay


async def record_success(db: AsyncSession, purpose: str) -> None:
    """Clear the count. A correct code is proof the preceding wrong ones
    were a real person fumbling, or are no longer an active attempt."""
    row = await db.get(ParentLoginLockout, purpose)
    if row is not None and (row.failure_count or row.locked_until is not None):
        row.failure_count = 0
        row.locked_until = None
        await db.commit()


async def sleep_for_failure(db: AsyncSession, purpose: str) -> None:
    """record_failure plus the wait, for the ordinary call site that wants
    both. Kept separate from record_failure so a caller that needs to do
    something else first still can."""
    delay = await record_failure(db, purpose)
    if delay:
        await asyncio.sleep(delay)
