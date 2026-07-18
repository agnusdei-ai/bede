"""Adapter router — which concrete provider backs ai_service's `_client`.

Two entry points:

* `get_default_client()` — called once at ai_service import time, it resolves a
  single concrete adapter (exactly today's behavior: one object assigned to
  `_client`). This is what keeps the ~20 tests that
  `patch.object(ai_service._client.messages, "stream", ...)` working unchanged —
  whatever concrete adapter is resolved, it exposes the identical `.messages`
  surface.

* `resolve_with_failover()` — the Phase-6 continuity helper. Returns a
  `FailoverClient` presenting the same `.messages` surface but trying each
  configured adapter in order, tripping a short in-memory circuit breaker on a
  provider that returns auth/rate-limit/connection errors so a downed provider
  isn't retried on every request. Call sites may opt into it; it is deliberately
  NOT the default `_client` so the single-client test contract stays intact.

## The account-closure scenario this exists for

The whole refactor's trigger case is "we can no longer rely on Anthropic at
all" (account closed/denied). So the default order is deliberately
`local,anthropic`, NOT `anthropic`:

* `local` (a self-hosted vLLM server running Qwen3-Coder-30B-A3B-Instruct via
  the OpenAI-compatible adapter) is the practical primary.
* `anthropic` is kept in the code and last in the order so access can be
  restored instantly by re-adding it, but the router NEVER requires
  `anthropic_api_key` to be set or valid in order to start up or serve — an
  adapter that isn't configured is simply skipped.

An adapter is "configured" when the credentials it needs are present:
`local` needs `local_llm_base_url`; `anthropic` needs `anthropic_api_key`;
`openai`/`mistral` need their API key. The router picks the FIRST configured
adapter in the order. Because a deployment that has lost Anthropic access sets
`LOCAL_LLM_BASE_URL`, `local` wins there; a legacy deployment that only has
`ANTHROPIC_API_KEY` set (and the test suite) falls through to `anthropic`.

`openai`/`mistral` are supported secondaries but are intentionally kept OUT of
the zero-config default order: `openai_api_key` already exists in this codebase
for OpenAI **TTS** (services/voice_synthesis.py), and auto-selecting the OpenAI
**chat** adapter merely because a TTS key is present would silently reroute the
tutor. Operators add them explicitly, e.g. `BEDE_ADAPTER_ORDER=local,openai,anthropic`.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.config import settings as _global_settings
from .anthropic_adapter import build_anthropic_client
from .openai_compatible_adapter import OpenAICompatibleClient

log = logging.getLogger(__name__)

# Mistral's OpenAI-compatible endpoint. OpenAI itself needs no base_url (the SDK
# default); vLLM/local uses whatever LOCAL_LLM_BASE_URL points at.
_MISTRAL_BASE_URL = "https://api.mistral.ai/v1"

_KNOWN_ADAPTERS = ("local", "openai", "mistral", "anthropic")


def _order(settings: Any) -> List[str]:
    """Effective adapter order. A non-empty BEDE_FORCE_ADAPTER overrides the
    order/failover entirely (a manual pin to one provider)."""
    forced = (settings.bede_force_adapter or "").strip()
    if forced:
        return [forced]
    return [x.strip() for x in settings.bede_adapter_order.split(",") if x.strip()]


def _is_configured(name: str, settings: Any) -> bool:
    if name == "anthropic":
        return bool(settings.anthropic_api_key)
    if name == "local":
        return bool(settings.local_llm_base_url)
    if name == "openai":
        return bool(settings.openai_api_key)
    if name == "mistral":
        return bool(settings.mistral_api_key)
    return False


def _build(name: str, settings: Any) -> Any:
    if name == "anthropic":
        return build_anthropic_client(settings.anthropic_api_key)
    if name == "local":
        return OpenAICompatibleClient(
            base_url=settings.local_llm_base_url,
            api_key=settings.local_llm_api_key,
            model=settings.local_llm_model,
        )
    if name == "openai":
        return OpenAICompatibleClient(
            base_url="",  # SDK default → api.openai.com
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )
    if name == "mistral":
        return OpenAICompatibleClient(
            base_url=_MISTRAL_BASE_URL,
            api_key=settings.mistral_api_key,
            model=settings.mistral_model,
        )
    raise ValueError(f"Unknown adapter {name!r} — expected one of {_KNOWN_ADAPTERS}")


def _configured_order(settings: Any) -> List[str]:
    return [name for name in _order(settings) if _is_configured(name, settings)]


def get_default_client(settings: Any = _global_settings) -> Any:
    """Resolve the single concrete adapter used as ai_service._client.

    Never raises on a missing/closed Anthropic account: if the first-choice
    provider isn't configured it's skipped, and if NOTHING in the order is
    configured we still return a constructed adapter (the last one listed, or
    anthropic) so the app boots — construction is lazy and only an actual
    request would surface the misconfiguration, exactly as before."""
    order = _order(settings)
    for name in order:
        if _is_configured(name, settings):
            log.info("Bede adapter resolved to %r (order=%s)", name, order)
            return _build(name, settings)

    fallback = order[-1] if order else "anthropic"
    log.warning(
        "No configured Bede adapter in order=%s — constructing %r unconfigured; "
        "requests will fail until credentials are set",
        order,
        fallback,
    )
    try:
        return _build(fallback, settings)
    except Exception:
        return build_anthropic_client(settings.anthropic_api_key)


# ── Phase 6: failover router with a short in-memory circuit breaker ───────────

_FAILOVER_ERRORS: tuple = ()


def _failover_error_types() -> tuple:
    """The exception classes that should trip failover: auth (401/403), rate
    limit (429), and connection/timeout errors from the primary. Resolved lazily
    and cached so importing this module never forces `openai`/`anthropic` error
    classes to import in an Anthropic-only or offline deployment."""
    global _FAILOVER_ERRORS
    if _FAILOVER_ERRORS:
        return _FAILOVER_ERRORS
    types: List[type] = [ConnectionError, TimeoutError]
    try:
        import anthropic

        types += [
            anthropic.AuthenticationError,
            anthropic.PermissionDeniedError,
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
        ]
    except Exception:
        pass
    try:
        import openai

        types += [
            openai.AuthenticationError,
            openai.PermissionDeniedError,
            openai.RateLimitError,
            openai.APIConnectionError,
        ]
    except Exception:
        pass
    _FAILOVER_ERRORS = tuple(types)
    return _FAILOVER_ERRORS


class _CircuitBreaker:
    """Per-adapter cooldown. After a provider fails, skip it for `cooldown_s`
    rather than paying its timeout on every subsequent request."""

    def __init__(self, cooldown_s: float = 60.0) -> None:
        self._cooldown_s = cooldown_s
        self._down_until: Dict[str, float] = {}

    def is_open(self, name: str) -> bool:
        import time

        until = self._down_until.get(name)
        return until is not None and time.monotonic() < until

    def trip(self, name: str) -> None:
        import time

        self._down_until[name] = time.monotonic() + self._cooldown_s

    def reset(self, name: str) -> None:
        self._down_until.pop(name, None)


async def _best_effort_failover_alert(primary: str, chosen: str) -> None:
    """Nice-to-have from the plan: tell the operator a failover happened. Uses
    the existing email_service (PARENT_EMAIL/Resend) and is fully best-effort —
    never raises, no-op if email isn't configured."""
    try:
        from services import email_service

        if not email_service.email_configured() or not _global_settings.parent_email:
            return
        html_body = (
            "<p>Bede switched AI providers automatically.</p>"
            f"<p>Primary provider <b>{primary}</b> was unavailable; now serving "
            f"from <b>{chosen}</b>. Sessions continue uninterrupted — this is an "
            "FYI so you know the primary needs attention.</p>"
        )
        await email_service.send_email(
            _global_settings.parent_email,
            subject=f"Bede failed over to {chosen}",
            html_body=html_body,
        )
    except Exception:
        log.debug("Failover alert email suppressed", exc_info=True)


class _FailoverStreamContext:
    """Opens a stream against the first healthy adapter, trying the next on an
    open-time failover error. Failover only happens BEFORE any event is yielded
    — once streaming to the child starts, switching mid-stream isn't safe."""

    def __init__(self, client: "FailoverClient", kwargs: Dict[str, Any]) -> None:
        self._client = client
        self._kwargs = kwargs
        self._active_ctx: Optional[Any] = None

    async def __aenter__(self) -> Any:
        errs = _failover_error_types()
        candidates = self._client._live_order()
        primary = candidates[0] if candidates else None
        last_exc: Optional[Exception] = None
        for name in candidates:
            adapter = self._client._adapter(name)
            ctx = adapter.messages.stream(**self._kwargs)
            try:
                stream = await ctx.__aenter__()
            except errs as exc:  # type: ignore[misc]
                last_exc = exc
                self._client._breaker.trip(name)
                log.warning("Adapter %r failed to open stream: %s", name, exc)
                continue
            self._active_ctx = ctx
            self._client._breaker.reset(name)
            if primary is not None and name != primary:
                await _best_effort_failover_alert(primary, name)
            return stream
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("No configured Bede adapter available for streaming")

    async def __aexit__(self, *exc: Any) -> Any:
        if self._active_ctx is not None:
            return await self._active_ctx.__aexit__(*exc)
        return None


class _FailoverMessages:
    def __init__(self, client: "FailoverClient") -> None:
        self._client = client

    def stream(self, **kwargs: Any) -> _FailoverStreamContext:
        return _FailoverStreamContext(self._client, kwargs)

    async def create(self, **kwargs: Any) -> Any:
        errs = _failover_error_types()
        candidates = self._client._live_order()
        primary = candidates[0] if candidates else None
        last_exc: Optional[Exception] = None
        for name in candidates:
            adapter = self._client._adapter(name)
            try:
                result = await adapter.messages.create(**kwargs)
            except errs as exc:  # type: ignore[misc]
                last_exc = exc
                self._client._breaker.trip(name)
                log.warning("Adapter %r failed on create: %s", name, exc)
                continue
            self._client._breaker.reset(name)
            if primary is not None and name != primary:
                await _best_effort_failover_alert(primary, name)
            return result
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("No configured Bede adapter available for create")


class FailoverClient:
    """Anthropic-shaped `_client` that fails over across configured adapters.

    Presents the same `.messages.stream()`/`.messages.create()` surface as any
    single adapter, so it's a drop-in for `_client`. Adapters are built once and
    reused; a circuit breaker skips a provider that recently failed."""

    def __init__(self, settings: Any = _global_settings, cooldown_s: float = 60.0) -> None:
        self._settings = settings
        self._breaker = _CircuitBreaker(cooldown_s)
        self._built: Dict[str, Any] = {}
        self.messages = _FailoverMessages(self)

    def _adapter(self, name: str) -> Any:
        if name not in self._built:
            self._built[name] = _build(name, self._settings)
        return self._built[name]

    def _live_order(self) -> List[str]:
        """Configured adapters, skipping any currently in circuit-breaker
        cooldown — unless every one is cooling down, in which case fall back to
        the full configured order rather than refusing service."""
        configured = _configured_order(self._settings)
        live = [n for n in configured if not self._breaker.is_open(n)]
        return live or configured


def resolve_with_failover(settings: Any = _global_settings) -> FailoverClient:
    return FailoverClient(settings)
