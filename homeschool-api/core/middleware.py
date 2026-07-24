"""
Security middleware stack applied in order:

1. ExfiltrationGuard    — blocks download endpoints, caps response size, strips embedding arrays
2. SecurityHeadersMiddleware — CSP, HSTS, X-Frame-Options, no-sniff, no-cache on API
3. RateLimitMiddleware  — per-IP sliding-window counter (auth routes stricter)
4. FingerprintValidator — validated inside route handlers, not middleware (needs JWT parse)

None of these can be disabled by env var or request header.
"""

import hashlib
import re
import time
from collections import defaultdict
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from core import license_state
from core.audit import AuditEvent, log_event
from core.config import settings

# ── Rate limiting ─────────────────────────────────────────────────────────────
# Sliding window: stores list of timestamps per IP
_rate_windows: dict[str, list[float]] = defaultdict(list)

# Per-minute limits come from settings (RATE_LIMIT_*_PER_MINUTE env vars —
# see core/config.py), so an operator expecting a crowd behind one shared IP
# can raise them from the deployment dashboard instead of editing code.
# Defaults: auth 10, api 120, voice 20, voice_stream_session 120 per IP per minute.

# Matches the sub-resource calls of an already-started streaming-transcription
# session — POST /voice/stream/{id}/chunk, POST /voice/stream/{id}/finish,
# GET /voice/stream/{id}/events — but not POST /voice/stream/start itself
# (no session id segment there), which stays in the stricter "voice" bucket
# as the real new-attempt signal. See the dispatch() comment below.
_VOICE_STREAM_SESSION_PATH = re.compile(r"/voice/stream/[^/]+/(chunk|finish|events)$")


def _check_rate(ip: str, bucket: str, limit: int, window_sec: int = 60) -> bool:
    """Returns True if the request is allowed."""
    key = f"{ip}:{bucket}"
    now = time.monotonic()
    window = _rate_windows[key]
    # Purge old timestamps
    cutoff = now - window_sec
    _rate_windows[key] = [t for t in window if t > cutoff]
    if len(_rate_windows[key]) >= limit:
        return False
    _rate_windows[key].append(now)
    return True


# ── Blocked response patterns (non-exfiltration) ────────────────────────────
# These patterns must not appear in any API response body
_BLOCKED_PATTERNS = [
    re.compile(r'"embedding"\s*:\s*\['),       # raw voice embedding arrays
    re.compile(r'"data_key"'),                  # encryption key material
    re.compile(r'"device_salt"'),
    re.compile(r'SAGE[\x00-\xFF]{4}'),          # encrypted file magic in response
]

# Endpoints that could return large binary blobs are blocked at route level,
# but we double-check here
_BLOCKED_ENDPOINTS = {"/export", "/download", "/dump", "/backup", "/debug"}

_MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2 MB hard cap on API responses


class ExfiltrationGuard(BaseHTTPMiddleware):
    """Prevent any path that could exfiltrate stored data."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path.rstrip("/").lower()

        # Block known exfiltration endpoints unconditionally
        for blocked in _BLOCKED_ENDPOINTS:
            if blocked in path:
                await log_event(
                    AuditEvent.SUSPICIOUS_REQUEST,
                    ip=request.client.host if request.client else "unknown",
                    user_agent=request.headers.get("user-agent", ""),
                    success=False,
                    detail=f"Blocked endpoint: {path}",
                )
                return JSONResponse({"detail": "Not found"}, status_code=404)

        response = await call_next(request)

        # For streaming (SSE tutor) don't buffer — just add headers
        if response.headers.get("content-type", "").startswith("text/event-stream"):
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Cache-Control"] = "no-store"
            return response

        # Buffer and inspect JSON responses
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
            if len(body) > _MAX_RESPONSE_BYTES:
                await log_event(
                    AuditEvent.SUSPICIOUS_REQUEST,
                    ip=request.client.host if request.client else "unknown",
                    success=False,
                    detail=f"Response too large: {path}",
                )
                return JSONResponse({"detail": "Response too large"}, status_code=500)

        # Scan for blocked patterns in JSON responses
        if "application/json" in response.headers.get("content-type", ""):
            text = body.decode("utf-8", errors="replace")
            for pattern in _BLOCKED_PATTERNS:
                if pattern.search(text):
                    await log_event(
                        AuditEvent.SUSPICIOUS_REQUEST,
                        ip=request.client.host if request.client else "unknown",
                        success=False,
                        detail=f"Blocked pattern in response: {path}",
                    )
                    return JSONResponse(
                        {"detail": "Response blocked by data policy"}, status_code=500
                    )

        # Enforce inline-only, no attachment downloads
        headers = dict(response.headers)
        headers.pop("content-disposition", None)
        headers["content-disposition"] = "inline"
        headers["x-content-type-options"] = "nosniff"

        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach strict security headers to every response."""

    # Content-Security-Policy: self-only, no inline scripts or eval
    _CSP = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "   # Tailwind needs inline styles
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "media-src 'self' blob:; "               # audio playback
        "worker-src 'self' blob:; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "base-uri 'self';"
    )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        h = response.headers
        h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        h["X-Frame-Options"] = "DENY"
        h["X-Content-Type-Options"] = "nosniff"
        h["Referrer-Policy"] = "no-referrer"
        h["Permissions-Policy"] = (
            "camera=(), geolocation=(), payment=(), usb=(), "
            "microphone=(self)"  # microphone allowed only for voice auth
        )
        h["Content-Security-Policy"] = self._CSP
        h["Cache-Control"] = "no-store, no-cache, must-revalidate"
        h["Pragma"] = "no-cache"
        # Prevent MIME type sniffing on API responses
        h["X-Permitted-Cross-Domain-Policies"] = "none"
        # Remove server fingerprinting
        if "server" in h:
            del h["server"]
        if "x-powered-by" in h:
            del h["x-powered-by"]

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP sliding-window rate limiter."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        ip = request.client.host if request.client else "0.0.0.0"
        path = request.url.path

        if "/auth/recovery/" in path:
            # Own bucket, separate from plain "auth" — see config.py's
            # rate_limit_account_recovery_per_minute comment for why a
            # shared bucket with /auth/login was a real bug: the exact
            # failed-login burst that trips parent_lockout.py also
            # exhausted the budget the parent's very next recovery attempt
            # needed.
            bucket, limit = "auth_recovery", settings.rate_limit_account_recovery_per_minute
        elif "/auth/" in path:
            bucket, limit = "auth", settings.rate_limit_auth_per_minute
        elif _VOICE_STREAM_SESSION_PATH.search(path):
            # Mechanics of a session /voice/stream/start already approved —
            # NOT a new attempt. A single hold can only ever produce a
            # bounded number of these (a handful of chunk uploads capped by
            # useHybridVoiceInput's own upload interval and max hold
            # duration, one finish, one events stream), so counting them
            # against the same budget as new-session starts punishes
            # ordinary multi-turn conversation, not abuse. Real regression
            # this fixes: the streaming-transcription rewrite (see
            # docs/VOICE_SETUP.md) turned one voice utterance into ~4
            # requests instead of the old single-shot /voice/transcribe's 1,
            # so as few as 5 taps in a minute could exhaust the 20/min
            # "voice" bucket outright — confirmed live on the public demo via
            # a debug-panel trace showing startVoiceStream failing on every
            # attempt after a handful of presses.
            bucket, limit = "voice_stream_session", settings.rate_limit_voice_stream_session_per_minute
        elif "/voice/" in path:
            bucket, limit = "voice", settings.rate_limit_voice_per_minute
        else:
            bucket, limit = "api", settings.rate_limit_api_per_minute
        allowed = _check_rate(ip, bucket, limit)

        if not allowed:
            await log_event(
                AuditEvent.RATE_LIMITED,
                ip=ip,
                success=False,
                detail=f"bucket={bucket} limit={limit}",
            )
            return JSONResponse(
                {"detail": "Too many requests — please wait before trying again"},
                status_code=429,
                headers={"Retry-After": "60"},
            )

        return await call_next(request)


class LicenseGateMiddleware(BaseHTTPMiddleware):
    """When a production instance has no usable license (missing, invalid,
    or expired — see core/license_state.py), restrict the API to exactly
    the surface a parent needs to FIX that in-app: logging in (auth + any
    enrolled second factor) and the license endpoints themselves. This
    replaces the old refuse-to-boot behavior — an expired license used to
    brick the instance until someone edited .env on the server; now the
    parent pastes the renewed key into the UI and the gate lifts live, no
    restart. Never active in dev or on the public demo (same exemptions
    the old startup check had)."""

    _ALLOWED_PREFIXES = ("/auth/", "/mfa/", "/admin/license")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not license_state.is_gated():
            return await call_next(request)
        path = request.url.path
        if (
            request.method == "OPTIONS"  # CORS preflight must always answer
            or path == "/health"
            or any(path.startswith(p) for p in self._ALLOWED_PREFIXES)
        ):
            return await call_next(request)
        return JSONResponse(
            {
                "detail": license_state.current().problem
                or "A valid license is required — a parent can apply one from Setup.",
                "code": "license_required",
            },
            status_code=403,
        )


# ── Session fingerprint helpers (called from route handlers) ─────────────────

def compute_fingerprint(ip: str, user_agent: str) -> str:
    """SHA-256(IP + '|' + UA) → 16-char hex. Binds JWT to device."""
    raw = f"{ip}|{user_agent}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]
