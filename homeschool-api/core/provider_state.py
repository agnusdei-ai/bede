"""
DB-backed AI-provider primary/secondary override — mirrors core/license_state.py's
and core/parent_credential.py's "a DB value wins over the env default, live, no
restart" precedent, applied to WHICH already-configured adapters
(services/adapters/) serve as primary and, optionally, secondary (the first
failover tried if primary errors).

Why this exists: BEDE_ADAPTER_ORDER/BEDE_FORCE_ADAPTER (core/config.py) are
plain env-loaded Settings, read once at process startup — switching from,
say, a degraded local Ollama model to Mistral used to mean editing .env and
restarting the API. This module lets a parent make that switch from the UI
(routers/admin.py's POST /admin/ai-provider) and have it take effect on the
very next request, the same way a license renewal or password change
already does.

The secondary override answers a narrower question than primary: with 3+
adapters configured (e.g. openai, mistral, anthropic), which ONE should be
tried first if primary fails — a family might prefer Claude over Mistral as
their backup, or vice versa, and previously had no way to express that
short of editing BEDE_ADAPTER_ORDER and restarting. Setting only primary
(secondary left unset) reorders exactly as before this existed — the rest
of the configured list simply follows in its original relative order.

Deliberately narrow: this only ever stores the NAME of an adapter that is
already configured (has real credentials in settings/.env) — never a
credential itself. Picking a provider with no credentials configured is
rejected before it ever reaches the DB (see routers/admin.py). A stored name
that later becomes unconfigured (credential removed) is silently ignored by
effective_order() below rather than breaking service.

_cached_primary/_cached_secondary are cached in-process (module-level, like
license_state.py's own _state and parent_credential.py's _cached_version)
rather than queried from the DB on every request — services/adapters/
router.py's FailoverClient consults them on every single tutoring turn, so
this has to be a synchronous in-memory read, not a DB round trip on that hot
path. refresh_from_db() re-syncs both caches at startup (main.py's lifespan)
so a value set just before this process started (or by a different
replica) is picked up correctly.
"""
import threading
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AIProviderOverride

_KEY_PRIMARY = "primary"
_KEY_SECONDARY = "secondary"

_lock = threading.Lock()
_cached_primary: Optional[str] = None
_cached_secondary: Optional[str] = None


def current_primary() -> Optional[str]:
    with _lock:
        return _cached_primary


def current_secondary() -> Optional[str]:
    with _lock:
        return _cached_secondary


def _set_cached_primary(name: Optional[str]) -> None:
    global _cached_primary
    with _lock:
        _cached_primary = name


def _set_cached_secondary(name: Optional[str]) -> None:
    global _cached_secondary
    with _lock:
        _cached_secondary = name


async def refresh_from_db(db: AsyncSession) -> None:
    primary_row = await db.get(AIProviderOverride, _KEY_PRIMARY)
    _set_cached_primary(primary_row.provider if primary_row else None)
    secondary_row = await db.get(AIProviderOverride, _KEY_SECONDARY)
    _set_cached_secondary(secondary_row.provider if secondary_row else None)


async def set_primary(db: AsyncSession, provider: str) -> None:
    """Set/replace the DB override and apply it in-process immediately —
    live, no restart, same shape as core/parent_credential.py's
    set_parent_password_override(). Caller (routers/admin.py) is
    responsible for validating `provider` is a known, configured adapter
    before calling this — this module stores whatever name it's given."""
    row = await db.get(AIProviderOverride, _KEY_PRIMARY)
    if row is None:
        db.add(AIProviderOverride(key=_KEY_PRIMARY, provider=provider))
    else:
        row.provider = provider
    await db.commit()
    _set_cached_primary(provider)


async def clear_primary(db: AsyncSession) -> None:
    """Remove the override — reverts to the env-configured
    BEDE_ADAPTER_ORDER/BEDE_FORCE_ADAPTER preference, live, no restart."""
    row = await db.get(AIProviderOverride, _KEY_PRIMARY)
    if row is not None:
        await db.delete(row)
        await db.commit()
    _set_cached_primary(None)


async def set_secondary(db: AsyncSession, provider: str) -> None:
    """Set/replace which configured adapter is tried first if primary
    errors — same live, no-restart shape as set_primary(). Caller
    (routers/admin.py) validates `provider` is known/configured first."""
    row = await db.get(AIProviderOverride, _KEY_SECONDARY)
    if row is None:
        db.add(AIProviderOverride(key=_KEY_SECONDARY, provider=provider))
    else:
        row.provider = provider
    await db.commit()
    _set_cached_secondary(provider)


async def clear_secondary(db: AsyncSession) -> None:
    """Remove the secondary override — the failover-after-primary reverts
    to whichever configured adapter comes next in the env order."""
    row = await db.get(AIProviderOverride, _KEY_SECONDARY)
    if row is not None:
        await db.delete(row)
        await db.commit()
    _set_cached_secondary(None)


def effective_order(configured_order: List[str]) -> List[str]:
    """Reorder `configured_order` (already-configured adapters, in their
    settings.bede_adapter_order preference) so the DB-overridden primary —
    if set and itself currently configured — comes first, then the
    DB-overridden secondary (if set, configured, and distinct from
    primary) comes second, with the rest following in their original
    relative order as further fallback.

    Crucially, a secondary override set WITHOUT a primary override must
    not bump anything into the first slot — the effective primary in that
    case is still whatever `configured_order`'s own first entry is (the
    env preference), exactly as if no override existed at all. Only the
    second slot is claimed by the secondary override. Getting this wrong
    once meant "pick a failover" silently also became "pick a primary,"
    which is not what a secondary-only choice means.

    A stale override — naming a provider that's unconfigured, unknown, or
    (for secondary) identical to the effective primary — is silently
    skipped rather than breaking service, exactly like the primary-only
    version this generalizes. Returns `configured_order` unchanged when
    neither override is set."""
    primary = current_primary()
    secondary = current_secondary()

    if primary is not None and primary in configured_order:
        effective_primary: Optional[str] = primary
    else:
        effective_primary = configured_order[0] if configured_order else None

    ordered: List[str] = []
    if effective_primary is not None:
        ordered.append(effective_primary)
    if secondary is not None and secondary in configured_order and secondary != effective_primary:
        ordered.append(secondary)
    ordered.extend(name for name in configured_order if name not in ordered)
    return ordered
