"""
DB-backed CHILD_PIN override — the capability two documents already claimed
existed.

Both CLAUDE.md and docs/SECURITY.md justified having no child-role recovery
scheme on the grounds that the single-tenant design makes the parent the
authority over the one shared credential, so "recovery" for a child is
simply "ask a parent to change CHILD_PIN, a capability that already
exists." It did not exist. routers/auth.py compared straight against
settings.child_pin, there was no endpoint, no UI, and no override table, so
the only way to change a child's PIN was to edit .env on the server and
restart the stack — exactly what a non-technical family cannot do, and
exactly what the graphical installer exists to spare them. The entire
argument for child recovery being out of scope rested on something nobody
had written.

It got sharper the day the installers stopped handing every family the same
PIN. While the wizard printed 602656 as its example, nobody forgot it. Now
a parent invents one their own child can remember, which is right, and
makes "we have forgotten it" a realistic Monday morning.

Mirrors core/parent_credential.py, with two deliberate differences.

NO credentials_version, AND NO SESSION IS ENDED. Changing the parent
password bumps a version embedded in every parent JWT, so every other
parent session dies instantly — that is what makes it able to end a
takeover. Doing the same here would eject a child from a lesson in progress
the moment a parent updated the PIN. A child session is a lesson, not an
administrative foothold; the new PIN applies at the NEXT login and work
already underway is left alone. tests/test_child_credential.py pins that.

VERIFICATION READS A PROCESS-LOCAL CACHE, NOT THE DATABASE. parent_
credential.py does a DB get per login attempt, which is fine because parent
logins are rare. Child login is not: it is the first thing that happens
every school morning, on the family's own hardware, and core/child_throttle
.py already documents why that path avoids per-attempt database work. So
the override is cached in-process, refreshed at startup and whenever it
changes, with the same periodic re-sync parent_credential.py uses to bound
multi-replica staleness. Verification itself stays synchronous.
"""
import hmac
import logging
import threading
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.credential_hash import hash_secret, verify_secret
from core.database import ChildCredentialOverride

log = logging.getLogger(__name__)

_KEY = "pin"

# Same bound and the same reasoning as core/parent_credential.py's: a
# running replica would otherwise never learn that a sibling changed the
# PIN, so a parent who changed it would find the old one still working on
# whichever replica a load balancer happened to pick.
_REFRESH_INTERVAL_SECONDS = 10

_lock = threading.Lock()
# (hash, salt) when an override is set, else None — meaning "fall back to
# the env CHILD_PIN", which is what every deployment that never changes its
# PIN in-app keeps doing, byte for byte as before this module existed.
_cached: Optional[tuple[bytes, bytes]] = None


def _set_cached(value: Optional[tuple[bytes, bytes]]) -> None:
    global _cached
    with _lock:
        _cached = value


def _get_cached() -> Optional[tuple[bytes, bytes]]:
    with _lock:
        return _cached


def has_override() -> bool:
    """Whether a PIN set in-app is currently in force. Reported by
    GET /mfa/status so the settings screen can say whether the PIN in use is
    the one chosen at setup or one changed since, without ever revealing
    either."""
    return _get_cached() is not None


async def refresh_from_db(db: AsyncSession) -> None:
    row = await db.get(ChildCredentialOverride, _KEY)
    _set_cached((row.hash, row.salt) if row else None)


async def periodic_refresh() -> None:
    """Re-sync the cache on an interval, forever. Started by main.py's
    lifespan, exactly like parent_credential.periodic_refresh, and swallows
    errors for the same reason: a loop that dies on one transient database
    error would silently restore the indefinite staleness it exists to
    prevent."""
    import asyncio

    from core.database import AsyncSessionLocal

    while True:
        await asyncio.sleep(_REFRESH_INTERVAL_SECONDS)
        try:
            async with AsyncSessionLocal() as db:
                await refresh_from_db(db)
        except Exception:
            log.warning(
                "child PIN override refresh failed — retrying next interval",
                exc_info=True,
            )


def verify_child_pin(submitted: str) -> bool:
    """DB override wins if set (hash-compared); otherwise the env plaintext,
    compared exactly as routers/auth.py did before this module existed.

    Synchronous and free of I/O on purpose — see the module docstring. Both
    branches are constant-time comparisons: verify_secret hashes the
    candidate with the stored salt before comparing, and the fallback keeps
    hmac.compare_digest."""
    cached = _get_cached()
    if cached is not None:
        digest, salt = cached
        return verify_secret(submitted, digest, salt)
    return hmac.compare_digest(submitted, settings.child_pin)


async def set_child_pin_override(db: AsyncSession, new_pin: str) -> None:
    """Set or replace the in-app PIN. Takes effect at the next child login.

    Nothing is invalidated: no version is bumped and no token is revoked, so
    a child mid-lesson keeps working. That is the whole difference from
    set_parent_password_override, and it is a decision rather than an
    omission — a parent tidying up credentials should not be able to end a
    child's lesson by accident, and a child PIN is not the credential an
    intruder would be holding.

    The caller validates the PIN against core/pin_policy.py first. This
    function does not re-check, for the same reason the parent equivalent
    does not: the endpoint owns the user-facing error message, and a second
    silent rule here would be a fifth copy of a policy this codebase has
    already been bitten by duplicating.
    """
    digest, salt = hash_secret(new_pin)
    row = await db.get(ChildCredentialOverride, _KEY)
    if row is None:
        db.add(ChildCredentialOverride(key=_KEY, hash=digest, salt=salt))
    else:
        row.hash = digest
        row.salt = salt
    await db.commit()
    _set_cached((digest, salt))
