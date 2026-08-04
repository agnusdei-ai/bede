"""
Device revocation (P9, Option C — docs/DEVICE_IDENTITY_DESIGN.md).

Mirrors core/parent_credential.py's exact shape: a DB-backed fact
(`DeviceRecord.revoked`), cached in-process for the hot per-request check,
re-synced periodically so a revocation made on one replica is honoured by
every replica within seconds rather than "until it happens to restart" —
see that module's docstring for the full multi-replica-staleness argument,
which applies here verbatim.

WHAT THIS IS. `device_id` is a UUID the browser generates once and persists
in localStorage, sent at login and embedded as a JWT claim from then on.
Revoking a device_id makes both its next login AND every outstanding token
carrying that claim stop working — see core/deps.py's per-request check and
routers/auth.py's login-time check.

WHAT THIS IS NOT. `device_id` is client-asserted, not cryptographically
proven. A stolen token carries a valid device_id along with it, so this
defends a KNOWN-lost device (a parent revoking a tablet they know is
missing), not against an attacker impersonating an unreported one. That is
Option A in docs/DEVICE_IDENTITY_DESIGN.md — a real per-device keypair —
and it remains a deliberately deferred, harder decision, not an oversight.

Scope: parent and child roles only. demo_code sessions are anonymous,
already carry their own one-time-code + quota mechanisms
(core/demo_code_session.py), and "revoke that device" has no meaning for a
session nobody registered a device for in the first place.
"""
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import DeviceRecord

log = logging.getLogger(__name__)

# Same bound as core/parent_credential.py's _REFRESH_INTERVAL_SECONDS, for
# the same reason: short enough that "revoke this device" stays
# substantially true across replicas, cheap enough (one small indexed read
# per replica per interval) not to matter on a Raspberry Pi.
_REFRESH_INTERVAL_SECONDS = 10

_lock = threading.Lock()
# The revoked SET, not the whole table — this is the only shape the
# per-request hot path (core/deps.py) needs, and it is small: it only grows
# on an explicit parent revocation, which is a rare, deliberate action.
_revoked_cache: set[str] = set()


def is_revoked(device_id: Optional[str]) -> bool:
    """Synchronous, in-process — this is what core/deps.py calls on every
    authenticated request carrying a device_id claim. A token with no
    device_id (issued before this existed, or by a caller driving the API
    directly with no device_id sent) is never treated as revoked; there is
    nothing to revoke."""
    if not device_id:
        return False
    with _lock:
        return device_id in _revoked_cache


def _set_cache(revoked_ids: set[str]) -> None:
    global _revoked_cache
    with _lock:
        _revoked_cache = revoked_ids


async def refresh_from_db(db: AsyncSession) -> None:
    result = await db.execute(select(DeviceRecord.device_id).where(DeviceRecord.revoked.is_(True)))
    _set_cache(set(result.scalars().all()))


async def periodic_refresh() -> None:
    """Re-sync the revoked-set from the DB on an interval, forever. Started
    as a background task by main.py's lifespan. Deliberately swallows and
    retries rather than dying — see core/parent_credential.py's
    periodic_refresh for why a silently-stopped loop is worse than a
    transient failure."""
    import asyncio

    from core.database import AsyncSessionLocal

    while True:
        await asyncio.sleep(_REFRESH_INTERVAL_SECONDS)
        try:
            async with AsyncSessionLocal() as db:
                await refresh_from_db(db)
        except Exception:
            log.warning("device revocation cache refresh failed — retrying next interval", exc_info=True)


async def touch(db: AsyncSession, device_id: str, role: str, user_agent: str) -> None:
    """Called on every successful login carrying a device_id — creates the
    record on first sight (this IS "onboarding" for Option C: automatic, no
    separate enrollment step, unlike Option A's WebCrypto ceremony) or
    updates last_seen_at/last_role/last_user_agent otherwise.

    Deliberately does NOT touch `revoked` — a caller must check is_revoked()
    (or the DB row directly) BEFORE calling this, since touching a revoked
    device's last_seen_at is a display nicety, not a way to un-revoke it,
    and this function has no business making that decision either way."""
    row = await db.get(DeviceRecord, device_id)
    now = datetime.now(timezone.utc)
    # Truncated defensively — a browser's own User-Agent string is bounded
    # in practice, but nothing enforces that at the HTTP layer, and this is
    # a display label, not a value anything security-relevant depends on.
    ua = user_agent[:200]
    if row is None:
        db.add(DeviceRecord(device_id=device_id, first_seen_at=now, last_seen_at=now, last_role=role, last_user_agent=ua))
    else:
        row.last_seen_at = now
        row.last_role = role
        row.last_user_agent = ua
    await db.commit()


async def revoke(db: AsyncSession, device_id: str) -> bool:
    """Marks a device revoked. Returns False if no such device exists — the
    router turns that into a 404 rather than a silent success, so a typo'd
    device_id doesn't look like it worked. Updates the in-process cache
    immediately (not just on the next periodic_refresh tick) so the
    revoking replica enforces its own change instantly; siblings catch up
    within _REFRESH_INTERVAL_SECONDS, the same trade
    core/parent_credential.py's set_parent_password_override makes."""
    row = await db.get(DeviceRecord, device_id)
    if row is None:
        return False
    row.revoked = True
    row.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    with _lock:
        _revoked_cache.add(device_id)
    return True


async def list_devices(db: AsyncSession) -> list[DeviceRecord]:
    """Newest-first — the device a parent is most likely investigating
    (the one that just showed up, or the one that was just used) is the
    one they want to see without scrolling."""
    result = await db.execute(select(DeviceRecord).order_by(DeviceRecord.last_seen_at.desc()))
    return list(result.scalars().all())
