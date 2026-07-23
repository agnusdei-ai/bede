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
refresh_from_db() re-syncs the cache at startup (main.py's lifespan) so a
version set before THIS process started (e.g. changed just before a
restart, or by a different replica) is picked up correctly.
"""
import hmac
import threading
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.credential_hash import hash_secret, verify_secret
from core.database import ParentCredentialOverride

_KEY = "password"

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
