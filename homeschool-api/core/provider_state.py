"""
DB-backed AI-provider primary override — mirrors core/license_state.py's and
core/parent_credential.py's "a DB value wins over the env default, live, no
restart" precedent, applied to WHICH already-configured adapter
(services/adapters/) serves as primary.

Why this exists: BEDE_ADAPTER_ORDER/BEDE_FORCE_ADAPTER (core/config.py) are
plain env-loaded Settings, read once at process startup — switching from,
say, a degraded local Ollama model to Mistral used to mean editing .env and
restarting the API. This module lets a parent make that switch from the UI
(routers/admin.py's POST /admin/ai-provider) and have it take effect on the
very next request, the same way a license renewal or password change
already does.

Deliberately narrow: this only ever stores the NAME of an adapter that is
already configured (has real credentials in settings/.env) — never a
credential itself. Picking a provider with no credentials configured is
rejected before it ever reaches the DB (see routers/admin.py). A stored name
that later becomes unconfigured (credential removed) is silently ignored by
effective_order() below rather than breaking service.

_cached_primary is cached in-process (module-level, like license_state.py's
own _state and parent_credential.py's _cached_version) rather than queried
from the DB on every request — services/adapters/router.py's FailoverClient
consults it on every single tutoring turn, so this has to be a synchronous
in-memory read, not a DB round trip on that hot path. refresh_from_db()
re-syncs the cache at startup (main.py's lifespan) so a value set just before
this process started (or by a different replica) is picked up correctly.
"""
import threading
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AIProviderOverride

_KEY = "primary"

_lock = threading.Lock()
_cached_primary: Optional[str] = None


def current_primary() -> Optional[str]:
    with _lock:
        return _cached_primary


def _set_cached_primary(name: Optional[str]) -> None:
    global _cached_primary
    with _lock:
        _cached_primary = name


async def refresh_from_db(db: AsyncSession) -> None:
    row = await db.get(AIProviderOverride, _KEY)
    _set_cached_primary(row.provider if row else None)


async def set_primary(db: AsyncSession, provider: str) -> None:
    """Set/replace the DB override and apply it in-process immediately —
    live, no restart, same shape as core/parent_credential.py's
    set_parent_password_override(). Caller (routers/admin.py) is
    responsible for validating `provider` is a known, configured adapter
    before calling this — this module stores whatever name it's given."""
    row = await db.get(AIProviderOverride, _KEY)
    if row is None:
        db.add(AIProviderOverride(key=_KEY, provider=provider))
    else:
        row.provider = provider
    await db.commit()
    _set_cached_primary(provider)


async def clear_primary(db: AsyncSession) -> None:
    """Remove the override — reverts to the env-configured
    BEDE_ADAPTER_ORDER/BEDE_FORCE_ADAPTER preference, live, no restart."""
    row = await db.get(AIProviderOverride, _KEY)
    if row is not None:
        await db.delete(row)
        await db.commit()
    _set_cached_primary(None)


def effective_order(configured_order: List[str]) -> List[str]:
    """Reorder `configured_order` (already-configured adapters, in their
    settings.bede_adapter_order preference) so the DB-overridden primary —
    if set and itself currently configured — comes first, with the rest
    following as fallback. Returns `configured_order` unchanged when no
    override is set, or when the stored override names a provider that
    isn't in `configured_order` (unconfigured or unknown) — silently, not
    an error, so a stale override never breaks service."""
    primary = current_primary()
    if primary is None or primary not in configured_order:
        return configured_order
    return [primary] + [name for name in configured_order if name != primary]
