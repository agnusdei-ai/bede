"""
DB-backed parent password override — mirrors core/license_state.py's "a DB
value wins over the env default, live, no restart" precedent, applied to
PARENT_PASSWORD for the same reason: it used to live only in .env, which
meant there was no way to change it from inside the running app at all,
forgotten or not. This module is the single source every consumer reads —
routers/auth.py's login(), routers/mfa.py's change-password/recovery
endpoints, and core/deps.py's per-request credentials_version check.

credentials_version is cached in-process (module-level, like
license_state.py's own _state) rather than queried from the DB on every
authenticated request — it only changes when the password actually
changes, so core/deps.py's check on every parent/parent_pending request is
a synchronous int comparison, not an added DB round trip on the hot path.
That property is worth keeping: it runs on every authenticated request, on
a Raspberry Pi.

refresh_from_db() re-syncs the cache at startup (main.py's lifespan) so a
version set before THIS process started is picked up correctly.

MULTI-REPLICA STALENESS — the reason for the periodic refresh below.
Startup sync alone is NOT sufficient once more than one process serves
traffic, and an earlier revision of this docstring claimed it covered "a
version set by a different replica", which was wrong in the case that
matters. A replica only learns a sibling's bump when it *starts*. A
running replica keeps its own cached value indefinitely.

The consequence is a silent failure of the exact control this module
exists to provide: a parent changes their password (or completes recovery)
on replica A, A bumps the DB and its own cache — and replica B keeps
accepting the attacker's stolen token until B happens to restart, which
may be days. "Change your password to end a takeover" would be true on one
replica and false on the others, with nothing anywhere reporting a problem.

Not a live issue on either deployment shape this app actually runs today
(a self-hosted single-family instance, or the demo's single-instance
Render service — see docs/DEPLOYMENT_TOPOLOGY.md), but it is a landmine
for anyone who scales it, and one that would be very hard to diagnose from
symptoms. _REFRESH_INTERVAL_SECONDS bounds the staleness to seconds
instead of "until restart", at a cost of one small query per replica per
interval rather than one per request. A local bump still applies to the
bumping replica instantly.
"""
import hmac
import threading
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.credential_hash import hash_secret, verify_secret
from core.database import ParentCredentialOverride

_KEY = "password"

# Upper bound on how long a running replica can keep accepting a token that
# a sibling replica has already invalidated. Short enough that "change the
# password to end a takeover" stays substantially true under replication;
# long enough that the query is negligible (one small indexed read per
# replica per interval, versus one per authenticated request if the cache
# were removed entirely).
_REFRESH_INTERVAL_SECONDS = 10

_lock = threading.Lock()
_cached_version = 0


def current_credentials_version() -> int:
    with _lock:
        return _cached_version


def _set_cached_version(v: int) -> None:
    global _cached_version
    with _lock:
        _cached_version = v


async def refresh_from_db(db: AsyncSession) -> None:
    row = await db.get(ParentCredentialOverride, _KEY)
    _set_cached_version(row.credentials_version if row else 0)


async def periodic_refresh() -> None:
    """Re-sync the cache from the DB on an interval, forever.

    Started as a background task by main.py's lifespan. Exists solely to
    bound multi-replica staleness — see this module's docstring. On a
    single-instance deployment it is a cheap no-op that re-reads a value
    that never changed.

    Deliberately swallows and retries rather than dying: a transient DB
    error must not permanently stop the refresh loop, because a silently
    stopped loop would restore exactly the indefinite-staleness behavior
    this is here to prevent, and would do so invisibly."""
    import asyncio
    import logging

    log = logging.getLogger(__name__)
    from core.database import AsyncSessionLocal

    while True:
        await asyncio.sleep(_REFRESH_INTERVAL_SECONDS)
        try:
            async with AsyncSessionLocal() as db:
                await refresh_from_db(db)
        except Exception:
            log.warning(
                "credentials_version refresh failed — retrying next interval",
                exc_info=True,
            )


async def has_override(db: AsyncSession) -> bool:
    return await db.get(ParentCredentialOverride, _KEY) is not None


async def verify_parent_password(db: AsyncSession, submitted: str) -> bool:
    """DB override wins if set (hash-compared); otherwise falls back to the
    env plaintext, compared exactly as before this module existed
    (hmac.compare_digest) — a deployment that never changes its password
    in-app sees zero behavior change."""
    row = await db.get(ParentCredentialOverride, _KEY)
    if row is not None:
        return verify_secret(submitted, row.hash, row.salt)
    return hmac.compare_digest(submitted, settings.parent_password)


async def set_parent_password_override(db: AsyncSession, new_password: str) -> int:
    """Sets/replaces the DB override and bumps credentials_version. Every
    outstanding parent/parent_pending JWT (which embeds the version at
    issuance — see routers/auth.py, routers/mfa.py) stops validating the
    moment this commits, ending any session that isn't the one making this
    change — including, deliberately, an attacker's stolen token if this
    call is the legitimate parent recovering access. Returns the new
    version."""
    row = await db.get(ParentCredentialOverride, _KEY)
    digest, salt = hash_secret(new_password)
    new_version = (row.credentials_version if row else 0) + 1
    if row is None:
        db.add(ParentCredentialOverride(key=_KEY, hash=digest, salt=salt, credentials_version=new_version))
    else:
        row.hash = digest
        row.salt = salt
        row.credentials_version = new_version
    await db.commit()
    _set_cached_version(new_version)
    return new_version
