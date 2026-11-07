"""
Per-child sign-in PINs (owner decision 2026-11-07, #761 follow-up).

THE GAP. Every child used to sign in with the one shared CHILD_PIN; the token
was then bound to a learner through the tablet's ChildLearnerBinding (device
id + nonce, set by a parent). The device id is a client-held UUID, not a
secret, so anyone holding the shared PIN who learned another tablet's id
could sign in as that tablet's child.

THE FIX. A parent may give a learner a PIN of its own. Then:

- The child signs in by naming the learner and typing THAT learner's PIN.
  The token carries the learner (``learner``) and this row's nonce
  (``learner_pin_nonce``), so core/deps.py's require_learner_access binds
  the session to the learner whose PIN was verified, server-side. No
  client-chosen name and no device id alone decides which child it is.
- The shared CHILD_PIN stops granting that learner, by any route: naming
  the learner with the shared PIN is refused at login, and a binding-path
  token (shared PIN + tablet binding) is refused for that learner's data.
- A learner with no row is untouched: shared PIN + binding, byte for byte.

Composes with hosted pairing (C-23) rather than replacing it: on a hosted
deployment the device must still be parent-approved and present its
per-device token, so a hosted child session needs the learner's PIN AND an
approved tablet.

LOCKOUT. Per child and persisted (the row's failure fields), keyed by the
learner under attack rather than the source address, so rotating IPs buys
nothing and a container restart resets nothing. One child's lockout never
touches a sibling's row. While locked, every attempt — including the right
PIN — gets the same "Invalid credentials" as a wrong PIN, so the lock is
not an oracle for which names have a PIN; a parent sees the lock in setup,
and setting the PIN again clears it. That DoS trade (a sibling can lock a
child out for 15 minutes) is the one core/child_throttle.py refused for the
shared PIN; it is accepted here because the parent can clear it in one
step and because the threat this closes is impersonation, not inconvenience.
"""
from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.credential_hash import hash_secret, verify_secret
from core.database import ChildLearnerBinding, ChildPin
from core.pin_policy import is_published_credential, pin_is_strong

MAX_PIN_LENGTH = 12

FAILURE_THRESHOLD = 10
FAILURE_WINDOW_SECONDS = 30 * 60
LOCKOUT_DURATION_SECONDS = 15 * 60

# Verified against when a login names a learner that has no PIN, so a
# named attempt costs the same PBKDF2 work whether or not the name has a PIN.
_DUMMY_HASH, _DUMMY_SALT = hash_secret(secrets.token_hex(16))


class ChildPinRejected(ValueError):
    """A PIN a parent tried to set that the policy refuses. The message is
    safe to show the parent and never echoes the PIN."""


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_locked(row: ChildPin, now: Optional[datetime] = None) -> bool:
    locked_until = _aware(row.locked_until)
    return locked_until is not None and locked_until > (now or _now())


def burn_dummy_verify(credential: str) -> None:
    """Spend one verify's worth of work so a named attempt against a learner
    with no PIN takes as long as one against a learner that has one."""
    verify_secret(credential, _DUMMY_HASH, _DUMMY_SALT)


async def get(db: AsyncSession, student_name: Optional[str]) -> Optional[ChildPin]:
    if not student_name:
        return None
    return await db.get(ChildPin, student_name)


async def check(db: AsyncSession, row: ChildPin, credential: str) -> bool:
    """Verify ``credential`` against this learner's PIN, recording the
    outcome. Returns True only for the right PIN while not locked. A locked
    row still pays for the hash, so a lock is not visible by timing."""
    now = _now()
    if is_locked(row, now):
        verify_secret(credential, row.pin_hash, row.pin_salt)
        return False

    if verify_secret(credential, row.pin_hash, row.pin_salt):
        if row.failure_count or row.locked_until is not None:
            row.failure_count = 0
            row.locked_until = None
            row.last_failure_at = None
            await db.commit()
        return True

    last = _aware(row.last_failure_at)
    lock_expired = row.locked_until is not None  # not locked now, so any lock has expired
    if lock_expired or last is None or (now - last).total_seconds() > FAILURE_WINDOW_SECONDS:
        row.failure_count = 0
        row.locked_until = None
    row.failure_count += 1
    row.last_failure_at = now
    if row.failure_count >= FAILURE_THRESHOLD:
        row.locked_until = now + timedelta(seconds=LOCKOUT_DURATION_SECONDS)
    await db.commit()
    return False


async def _rotate_bindings(db: AsyncSession, student_name: str) -> None:
    """End this child's shared-PIN (binding-path) sessions: every tablet
    bound to the learner gets a fresh nonce, so tokens minted before the
    change no longer match. The binding itself is kept, so the parent does
    not have to reassign tablets."""
    rows = (await db.execute(
        select(ChildLearnerBinding).where(ChildLearnerBinding.student_name == student_name)
    )).scalars().all()
    for binding in rows:
        binding.nonce = secrets.token_hex(24)


async def validate_new_pin(db: AsyncSession, student_name: str, pin: str) -> None:
    """Raise ChildPinRejected for a PIN this learner may not have."""
    from core.parent_credential import verify_parent_password

    if not pin_is_strong(pin) or len(pin) > MAX_PIN_LENGTH:
        raise ChildPinRejected(
            "Use 6 to 12 digits that are not an easy pattern (no runs like 123456, "
            "no repeats like 121212, and not the same forwards and backwards)."
        )
    if is_published_credential(pin):
        raise ChildPinRejected("That PIN is published as an example. Please choose another.")
    reserved = [settings.child_pin, settings.demo_pin, settings.sandbox_pin]
    if any(r and hmac.compare_digest(pin, r) for r in reserved) or await verify_parent_password(db, pin):
        raise ChildPinRejected(
            "That PIN is already used for another sign-in on this deployment. Please choose another."
        )
    others = (await db.execute(select(ChildPin).where(ChildPin.student_name != student_name))).scalars().all()
    if any(verify_secret(pin, other.pin_hash, other.pin_salt) for other in others):
        raise ChildPinRejected("Another child already uses that PIN. Each child needs their own.")


async def set_pin(db: AsyncSession, student_name: str, pin: str) -> None:
    """Set or replace a learner's PIN. Rotates the nonce (ending every token
    the old PIN issued), clears any lockout, and rotates the learner's
    tablet bindings (ending shared-PIN sessions). Caller validates first."""
    digest, salt = hash_secret(pin)
    row = await db.get(ChildPin, student_name)
    if row is None:
        row = ChildPin(student_name=student_name, pin_hash=digest, pin_salt=salt,
                       nonce=secrets.token_hex(24), failure_count=0)
        db.add(row)
    else:
        row.pin_hash = digest
        row.pin_salt = salt
        row.nonce = secrets.token_hex(24)
        row.failure_count = 0
        row.last_failure_at = None
        row.locked_until = None
        row.changed_at = _now()
    await _rotate_bindings(db, student_name)
    await db.commit()


async def clear_pin(db: AsyncSession, student_name: str) -> bool:
    """Remove a learner's PIN, returning it to the shared PIN. Ends every
    session the PIN issued (the row and its nonce are gone) and rotates the
    learner's tablet bindings so pre-PIN shared-PIN tokens stay ended too."""
    row = await db.get(ChildPin, student_name)
    if row is None:
        return False
    await db.delete(row)
    await _rotate_bindings(db, student_name)
    await db.commit()
    return True


async def status(db: AsyncSession) -> dict[str, dict]:
    """Parent view: which learners have a PIN and whether one is locked.
    Never returns a PIN, hash, salt or nonce."""
    now = _now()
    rows = (await db.execute(select(ChildPin))).scalars().all()
    return {
        r.student_name: {
            "has_pin": True,
            "locked": is_locked(r, now),
            "changed_at": _aware(r.changed_at).isoformat() if r.changed_at else None,
        }
        for r in rows
    }


async def token_is_live(db: AsyncSession, payload: dict) -> bool:
    """For a token issued by a learner's own PIN: the row still exists and
    still carries the nonce the token was minted with."""
    name = payload.get("learner")
    nonce = payload.get("learner_pin_nonce")
    if not name or not nonce:
        return False
    row = await db.get(ChildPin, name)
    return row is not None and hmac.compare_digest(row.nonce, nonce)
