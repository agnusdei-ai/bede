"""
Account lockout for the parent role — the piece the E009 anomaly watch
(core/audit.py) never provided: that alerts a parent after repeated
PARENT_PASSWORD failures, but never actually stops the next attempt. This
module does. DB-backed (see core/database.py's ParentLoginLockout) so a
container restart can't reset an attacker's progress toward the threshold.

Threshold is deliberately ABOVE the anomaly watch's own (5 failures/10min
-> email), so a legitimate parent who mistypes their password a few times
gets a heads-up email before they'd ever actually get locked out — the
lockout is the backstop for a real attack in progress, not the first line
of feedback.

A stale failure count (nothing failed in _FAILURE_WINDOW_SECONDS) resets
on the next attempt rather than accumulating forever — an occasional typo
over months should never eventually add up to a lockout.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import ParentLoginLockout

_KEY = "parent"

FAILURE_THRESHOLD = 10
LOCKOUT_DURATION_SECONDS = 15 * 60
FAILURE_WINDOW_SECONDS = 30 * 60


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Real Postgres round-trips DateTime(timezone=True) columns as
    tz-aware, but SQLite (this project's test-suite engine, see
    tests/conftest.py's demo_db fixture) silently drops tzinfo on read —
    everything this module writes is UTC, so a naive value read back is
    assumed to be UTC rather than compared directly against an aware
    'now' and raising TypeError."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def check_locked(db: AsyncSession) -> Optional[datetime]:
    """Returns the lockout expiry if currently locked, else None. A lockout
    whose expiry has already passed reads as unlocked — the next failure
    (if any) starts a fresh count via record_failure's own staleness check,
    not an immediate re-lock."""
    row = await db.get(ParentLoginLockout, _KEY)
    if row is None or row.locked_until is None:
        return None
    locked_until = _aware(row.locked_until)
    if locked_until <= datetime.now(timezone.utc):
        return None
    return locked_until


async def record_failure(db: AsyncSession) -> Optional[datetime]:
    """Returns the new locked_until if this failure just triggered a
    lockout, else None. Called after a wrong PARENT_PASSWORD, not for
    other roles — this app has exactly one parent identity, so lockout is
    role-scoped rather than per-IP (see ParentLoginLockout's own
    docstring for why that matters)."""
    now = datetime.now(timezone.utc)
    row = await db.get(ParentLoginLockout, _KEY)
    if row is None:
        row = ParentLoginLockout(key=_KEY, failure_count=0, locked_until=None)
        db.add(row)

    updated_at = _aware(row.updated_at)
    locked_until = _aware(row.locked_until)
    stale = updated_at is not None and (now - updated_at).total_seconds() > FAILURE_WINDOW_SECONDS
    lockout_expired = locked_until is not None and locked_until <= now
    if stale or lockout_expired:
        row.failure_count = 0
        row.locked_until = None

    row.failure_count += 1
    triggered: Optional[datetime] = None
    if row.failure_count >= FAILURE_THRESHOLD:
        triggered = now + timedelta(seconds=LOCKOUT_DURATION_SECONDS)
        row.locked_until = triggered

    await db.commit()
    return triggered


async def record_success(db: AsyncSession) -> None:
    """Clears any accumulated failures — a correct password is proof the
    prior wrong attempts weren't (or are no longer) an active attack."""
    row = await db.get(ParentLoginLockout, _KEY)
    if row is not None and (row.failure_count or row.locked_until is not None):
        row.failure_count = 0
        row.locked_until = None
        await db.commit()
