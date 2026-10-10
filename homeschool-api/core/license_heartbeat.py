"""
Optional license-server heartbeat client — the outbound half of the
server-tracked validity model (docs/PRODUCTION_SETUP.md#licensing,
docs/LICENSE_SERVER_DESIGN.md §6.4).

A deployment opts in by setting LICENSE_SERVER_URL. When set, a background
task activates this install once (POST /v1/activate) and then revalidates
daily (POST /v1/validate), sending only {license_key, install_id}. Every
successful answer is cached tamper-evidently — HMAC under a SECRET_KEY-
derived key, the same digest-pin idea as core/constitution.py's pinned
constitution digest: the cache is not secret (it says only what the server
already told this instance) but it must not be editable — and fed to
core/license_state.refresh(), where it outranks the signed payload's
nominal expiry in both directions: a renewal arrives without re-pasting a
key, and a refund/cancellation gates the instance.

Failures are never fatal. A heartbeat that cannot reach the server logs
and retries — the last good answer carries the instance for a uniform
30-day offline grace (SERVER_GRACE_DAYS in core/license_state.py), and
only then does it fall back to the existing gated mode. Nothing here ever
blocks a request or fails one: the heartbeat runs in its own task, and a
transient outage is invisible to the household until the grace window
closes.

Leaving LICENSE_SERVER_URL unset (the default) is a permanent opt-out and
byte-for-byte today's offline behavior: this module is never enabled, no
task is started, and NO outbound license traffic of any kind exists. That
guarantee is asserted as code in tests/test_license_heartbeat.py
(test_opt_out_issues_no_http_requests), which records every attempt at the
httpx layer itself.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import random

import httpx

from core import encryption, license_state
from core.config import settings
from core.database import EncryptionConfig, LicenseConfig

log = logging.getLogger(__name__)

_ACTIVATE_PATH = "/v1/activate"    # once per key, first contact — registers this install
_VALIDATE_PATH = "/v1/validate"    # daily thereafter — picks up renewals and revocations
_REQUEST_TIMEOUT = 15.0            # seconds; two tiny JSON POSTs
_INTERVAL_SECONDS = 24 * 60 * 60   # daily
_JITTER_SECONDS = 3600             # ± up to an hour: a thousand families must not check in at the same second
_INITIAL_JITTER_SECONDS = 600      # ≤10 min after boot — prompt enough, still de-synchronized
_CACHE_ROW_KEY = "license_heartbeat_cache"  # in encryption_config, next to device_salt
_CACHE_MAC_INFO = b"bede/license-heartbeat-cache/v1"  # domain separation, core/identity.py's pattern

_kick: asyncio.Event | None = None  # created by run_periodic on its own loop


def kick() -> None:
    """Request an immediate heartbeat cycle — called when the parent
    applies a new key, so activation/revalidation doesn't wait up to a
    day. Purely an optimization: never raises, and the daily loop runs
    regardless. A no-op before the loop has started (the loop's first
    cycle runs within its initial jitter anyway)."""
    event = _kick
    if event is None:
        return
    try:
        event.set()
    except Exception as exc:  # a kick must never fail the request that triggered it
        log.debug("license heartbeat kick skipped: %s", exc)


def enabled() -> bool:
    """Whether this instance participates in license-server tracking.
    False when LICENSE_SERVER_URL is unset (the permanent opt-out) and for
    demo deployments (license-exempt by design — they must never acquire
    an outbound license channel)."""
    return bool(settings.license_server_url.strip()) and not settings.is_demo_deployment


def kick() -> None:
    """Request an immediate heartbeat cycle — called when the parent
    applies a new key, so activation/revalidation doesn't wait up to a
    day. Purely an optimization: never raises, and the daily loop runs
    regardless."""
    try:
        _kick.set()
    except Exception as exc:  # a kick must never fail the request that triggered it
        log.debug("license heartbeat kick skipped: %s", exc)


async def _post_json(path: str, body: dict) -> tuple[int, dict]:
    """One POST to the license server: (status_code, parsed json body —
    {} when the body isn't JSON). Raises on network failure; callers treat
    every exception as a transient outage. Module-level so tests can
    substitute the transport — but the no-traffic guarantee is asserted
    one level lower, at httpx itself."""
    base = settings.license_server_url.strip().rstrip("/")
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        response = await client.post(f"{base}{path}", json=body)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return response.status_code, payload


async def current_license_text(db) -> str | None:
    """The key text the heartbeat should present: the applied DB key when
    one exists (it outranks env in license_state), else the env key. None
    when the instance has no key configured at all (nothing to activate)."""
    row = await db.get(LicenseConfig, "license")
    if row is not None and row.license_text:
        return row.license_text
    return settings.license_key or None


def _cache_mac(report_payload: dict) -> str:
    """HMAC-SHA256 over the canonical cached JSON, keyed by a SECRET_KEY-
    derived value (core/identity.py's derivation pattern). The cached
    answer gates and un-gates the app, so a casual edit — 'revoked'
    rewritten to 'active' — must fail this check and be treated as
    absent."""
    blob = json.dumps(report_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    key = hmac.new(settings.secret_key.encode("utf-8"), _CACHE_MAC_INFO, hashlib.sha256).digest()
    return hmac.new(key, blob, hashlib.sha256).hexdigest()


async def write_cache(db, report: license_state.ServerReport) -> None:
    """Persist the last successful answer, integrity-sealed. Keyed by the
    well-known encryption_config row (never a new table — see the
    no-ALTER-TABLE refusal); the row holds bytes like device_salt does."""
    payload = {
        "status": report.status,
        "valid_until": report.valid_until.isoformat() if report.valid_until else None,
        "reported_at": report.reported_at.isoformat(),
        "key_digest": report.key_digest,
        "activations_used": report.activations_used,
        "max_activations": report.max_activations,
    }
    blob = json.dumps(
        {"report": payload, "mac": _cache_mac(payload)}, separators=(",", ":")
    ).encode("utf-8")
    row = await db.get(EncryptionConfig, _CACHE_ROW_KEY)
    if row is None:
        db.add(EncryptionConfig(key=_CACHE_ROW_KEY, value=blob))
    else:
        row.value = blob
    await db.commit()


async def read_cached_report(db) -> license_state.ServerReport | None:
    """The last successful heartbeat answer, integrity-checked. None when
    the heartbeat is disabled (an instance that later opts OUT must revert
    to pure signed-payload behavior — a stale cached answer must not keep
    gating it), when no answer was ever received, or when the cached blob
    fails its integrity check (logged, then treated as absent — never
    trusted, never fatal)."""
    if not enabled():
        return None
    row = await db.get(EncryptionConfig, _CACHE_ROW_KEY)
    if row is None:
        return None
    try:
        parsed = json.loads(row.value.decode("utf-8"))
        payload = parsed["report"]
        if not hmac.compare_digest(parsed["mac"], _cache_mac(payload)):
            raise ValueError("HMAC mismatch")
        status = payload["status"]
        if status not in ("active", "revoked", "unknown"):
            raise ValueError(f"unknown cached status {status!r}")
        reported_at = license_state.parse_server_datetime(payload["reported_at"])
        if reported_at is None:
            raise ValueError("missing reported_at")
        report = license_state.ServerReport(
            status=status,
            valid_until=license_state.parse_server_datetime(payload.get("valid_until")),
            reported_at=reported_at,
            key_digest=payload["key_digest"],
            activations_used=payload.get("activations_used"),
            max_activations=payload.get("max_activations"),
        )
        return report
    except Exception as exc:
        log.warning(
            "License heartbeat cache failed its integrity check and is treated as absent: %s", exc
        )
        return None


async def _refresh_with_report(db, report: license_state.ServerReport | None) -> None:
    """Re-run the license resolution with the server's answer included —
    the same inputs main.py's startup path gathers."""
    row = await db.get(LicenseConfig, "license")
    license_state.refresh(
        settings.license_key,
        row.license_text if row is not None else None,
        required=settings.is_production and not settings.is_demo_deployment,
        server_report=report,
    )


async def heartbeat_cycle(
    db,
    *,
    license_text: str,
    install_id: str,
    activate: bool,
) -> tuple[bool, license_state.ServerReport | None]:
    """One activate-or-validate exchange.

    Returns (spoke, report): `spoke` is True when the server answered at
    all (even to refuse — see 409), `report` is the parsed answer when one
    changes license state (also written to the tamper-evident cache and
    applied via license_state.refresh). Never raises: network failures,
    unexpected statuses, and malformed bodies all log and return
    (False, None) — the last good answer holds within the offline grace."""
    path = _ACTIVATE_PATH if activate else _VALIDATE_PATH
    body = {"license_key": license_text, "install_id": install_id}
    try:
        status_code, payload = await _post_json(path, body)
        if status_code == 200 and (not isinstance(payload, dict) or "status" not in payload):
            raise ValueError("malformed 200 response (missing status)")
        if status_code not in (200, 409, 410):
            raise ValueError(f"unexpected HTTP {status_code}")
    except Exception as exc:
        log.warning(
            "License %s could not reach the server (transient — the last good "
            "answer holds within the offline grace): %s",
            "activation" if activate else "validation", exc,
        )
        return False, None

    if status_code == 409:
        # A DIFFERENT install_id at this key's activation cap — the
        # casual-copy case the cap exists for. The server heard us; this
        # install keeps governing itself by the signed payload (this is
        # casual-copy resistance, not DRM), and support can see the log.
        error = payload.get("error") if isinstance(payload, dict) else None
        log.warning("License activation rejected (%s) — this key's activation cap is reached", error)
        return True, None

    if status_code == 410:
        # The server's unambiguous answer for a revoked/nonexistent
        # license ({"error": "revoked"}). Persist it — revocation must
        # survive restarts, not just the process lifetime.
        report = license_state.server_report_from_payload({"status": "revoked"}, license_text)
        await write_cache(db, report)
        await _refresh_with_report(db, report)
        return True, report

    report = license_state.server_report_from_payload(payload, license_text)
    await write_cache(db, report)
    await _refresh_with_report(db, report)
    return True, report


async def run_periodic() -> None:
    """The background loop — started from main.py's lifespan ONLY when
    enabled(). Activates once, then validates daily with jitter; a kick()
    (new key applied) wakes it early. Failures log and retry; they never
    gate anyone — the cached answer holds within the 30-day grace."""
    if not enabled():
        log.info(
            "License server not configured (LICENSE_SERVER_URL empty) — heartbeat "
            "disabled; licenses verify fully offline"
        )
        return
    # A fresh Event per run: a module-level one would bind to whichever
    # event loop first touched it (asyncio primitives are loop-bound), and
    # kick() fires from the request path on the lifespan's loop.
    global _kick
    _kick = asyncio.Event()
    await asyncio.sleep(random.uniform(0, _INITIAL_JITTER_SECONDS))
    activated = False
    while True:
        try:
            # Imported here, not at module top, so test fixtures that swap
            # core.database.AsyncSessionLocal (conftest.py's demo_db pattern)
            # are picked up — the same convention core/demo_code_session.py uses.
            from core.database import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                install = await encryption.get_or_create_install_id(db)
                license_text = await current_license_text(db)
                if license_text and install:
                    if not activated:
                        spoke, _report = await heartbeat_cycle(
                            db, license_text=license_text, install_id=install, activate=True
                        )
                        activated = spoke  # a failed activation retries next cycle
                    if activated:
                        # Validate in the same pass: activation alone doesn't
                        # fetch the term/status answer the instance caches.
                        await heartbeat_cycle(
                            db, license_text=license_text, install_id=install, activate=False
                        )
                else:
                    log.debug("License heartbeat: no license key configured yet")
        except Exception as exc:
            # Same contract as the exchange itself: a cycle that can't run
            # is an outage, not an error the household should ever see.
            log.warning("License heartbeat cycle failed (last good answer holds): %s", exc)
        try:
            await asyncio.wait_for(_kick.wait(), timeout=_INTERVAL_SECONDS + random.uniform(0, _JITTER_SECONDS))
            _kick.clear()  # a new key was applied — revalidate immediately
        except asyncio.TimeoutError:
            pass
