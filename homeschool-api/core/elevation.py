"""
Privileged access elevation — step-up for the management plane
(docs/ARCHITECTURE_PRINCIPLES.md P8).

THE PROBLEM. "Parent" was simultaneously the ordinary account identity —
adjusting today's plan, sitting with a child, reading a narration — and the
fully-privileged administrative one: reading the audit log, repointing the
AI provider at a different vendor, deleting a security key, permanently
destroying a student's data. Same token, same scope, always, for the whole
8-hour session. There was no privilege boundary to enforce even in the
places the network could have enforced one.

Concretely, that meant a session left open on an unattended tablet was not
just "logged in", it was administrator. Anyone reaching it could read every
security event, disable the second factor, or point the AI provider
somewhere of their choosing — and none of those needed the password the
parent typed once that morning.

THE MECHANISM. Management-plane actions require an elevation grant that is
separate from the session, recent, and short. The parent re-presents their
password (and their second factor, if one is enrolled) at
`POST /auth/elevate`; that records a row valid for
`ELEVATION_TTL_MINUTES` (default 10) against this session's `jti`.

Three properties worth being explicit about, because each rules out a
tempting simpler design:

  * **Per-session, not per-parent.** The grant is keyed on the token's
    `jti`. Elevating on the desktop does not elevate the tablet that is
    still logged in in the kitchen.
  * **Database-backed, not in-process.** An in-memory grant is invisible to
    sibling replicas, so the same session would be elevated on the replica
    that granted it and rejected by the next one. That presents as a
    flaky step-up, and the obvious fix — making it sticky — is worse than
    the bug.
  * **Time-boxed, not sticky.** Expiry is absolute from the moment of
    elevation, not a sliding window on use. A sliding window would let a
    single password entry hold administrator rights for the whole session
    as long as the attacker kept clicking, which is the property this
    exists to remove.

WHAT THIS IS NOT. It is not a defense against an attacker who has the
parent's password — they can elevate too. It raises the cost of a *stolen
session*: a token lifted from an open tab, a shared device, an XSS payload
replaying a bearer token. Those are the realistic ones on a LAN appliance,
and none of them carry the password.

REVOCATION. Elevations do not need explicit revocation on password change:
the `cv` (credentials_version) claim already invalidates every outstanding
parent token when the password changes (core/parent_credential.py), so the
`jti` those grants are keyed to becomes unusable at the same moment.
`drop()` exists for the deliberate "I'm done administering" action and is
called on logout.
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings

log = logging.getLogger(__name__)


def new_jti() -> str:
    """A session identifier for a parent token.

    128 bits from `secrets` — this is the name an elevation grant is keyed
    on, so guessing one must be infeasible even though holding a valid
    signed token for it is also required.
    """
    return secrets.token_urlsafe(16)


def _ttl() -> timedelta:
    return timedelta(minutes=settings.elevation_ttl_minutes)


async def grant(db: AsyncSession, jti: str) -> datetime:
    """Elevate this session. Returns when the grant expires.

    Re-elevating an already-elevated session resets the clock rather than
    stacking, which is what a parent re-entering their password means.
    """
    from core.database import PrivilegedElevation

    now = datetime.now(timezone.utc)
    expires = now + _ttl()

    row = await db.get(PrivilegedElevation, jti)
    if row is None:
        db.add(PrivilegedElevation(jti=jti, granted_at=now, expires_at=expires))
    else:
        row.granted_at = now
        row.expires_at = expires
    await db.commit()
    return expires


async def is_elevated(db: AsyncSession, jti: Optional[str]) -> bool:
    """Whether this session currently holds management-plane privilege.

    A token with no `jti` is never elevated. That covers tokens issued
    before P8 existed and every non-parent role, and it fails in the safe
    direction: the parent re-enters their password once, rather than an
    unidentifiable session silently counting as elevated.
    """
    if not jti:
        return False

    from core.database import PrivilegedElevation

    row = await db.get(PrivilegedElevation, jti)
    if row is None:
        return False

    expires = row.expires_at
    # SQLite hands back naive datetimes even for timezone=True columns;
    # Postgres does not. Comparing a naive to an aware datetime raises, so
    # normalize rather than assume the backend.
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        return False
    return True


async def drop(db: AsyncSession, jti: Optional[str]) -> bool:
    """End this session's elevation early. Returns whether one existed."""
    if not jti:
        return False

    from core.database import PrivilegedElevation

    row = await db.get(PrivilegedElevation, jti)
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def purge_expired(db: AsyncSession) -> int:
    """Delete elevations that have expired. Returns how many.

    Expired rows are already inert — `is_elevated` checks the timestamp, so
    this is hygiene rather than a security control. Without it the table
    grows by one row per elevation forever on an appliance nobody prunes.
    """
    from core.database import PrivilegedElevation

    result = await db.execute(
        delete(PrivilegedElevation).where(PrivilegedElevation.expires_at <= datetime.now(timezone.utc))
    )
    await db.commit()
    count = result.rowcount or 0
    if count:
        log.info("Purged %d expired privileged elevation(s)", count)
    return count


async def active_count(db: AsyncSession) -> int:
    """Currently-valid elevations. For the admin status view — an operator
    should be able to see that a privileged session is open somewhere."""
    from core.database import PrivilegedElevation

    result = await db.execute(
        select(PrivilegedElevation).where(PrivilegedElevation.expires_at > datetime.now(timezone.utc))
    )
    return len(result.scalars().all())
