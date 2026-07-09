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

from core.audit import AuditEvent, log_event

# ── Rate limiting ─────────────────────────────────────────────────────────────
# Sliding window: stores list of timestamps per IP
_rate_windows: dict[str, list[float]] = defaultdict(list)

AUTH_LIMIT = 10       # auth attempts per IP per minute
API_LIMIT = 120       # general API calls per IP per minute
VOICE_LIMIT = 20      # voice enroll/verify per IP per minute


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

        if "/auth/" in path:
            allowed, bucket, limit = _check_rate(ip, "auth", AUTH_LIMIT), "auth", AUTH_LIMIT
        elif "/voice/" in path:
            allowed, bucket, limit = _check_rate(ip, "voice", VOICE_LIMIT), "voice", VOICE_LIMIT
        else:
            allowed, bucket, limit = _check_rate(ip, "api", API_LIMIT), "api", API_LIMIT

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


# ── Session fingerprint helpers (called from route handlers) ─────────────────

def compute_fingerprint(ip: str, user_agent: str) -> str:
    """SHA-256(IP + '|' + UA) → 16-char hex. Binds JWT to device."""
    raw = f"{ip}|{user_agent}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]
