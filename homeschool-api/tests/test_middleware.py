"""
Regression tests for core/middleware.py — previously untested despite being
the security-critical layer (rate limiting, exfiltration guard, security
headers) applied to every single request. Exercises real ASGI dispatch via
FastAPI's TestClient against minimal throwaway apps, not the full app (which
needs a live DB at startup).
"""
import core.middleware as middleware
from core.middleware import (
    ExfiltrationGuard,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    _check_rate,
)
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient


def setup_function():
    """Module-level sliding-window state, shared across every app instance —
    reset it so one test's requests can't push another test over its limit."""
    middleware._rate_windows = middleware.defaultdict(list)


# ── _check_rate (sliding window) ────────────────────────────────────────────

def test_check_rate_allows_up_to_the_limit():
    for _ in range(5):
        assert _check_rate("1.2.3.4", "test", limit=5) is True


def test_check_rate_denies_once_over_the_limit():
    for _ in range(5):
        _check_rate("1.2.3.4", "test", limit=5)
    assert _check_rate("1.2.3.4", "test", limit=5) is False


def test_check_rate_is_scoped_per_ip_and_bucket():
    for _ in range(5):
        _check_rate("1.2.3.4", "test", limit=5)
    # A different IP, and the same IP in a different bucket, must not be
    # affected by another key's window filling up.
    assert _check_rate("5.6.7.8", "test", limit=5) is True
    assert _check_rate("1.2.3.4", "other-bucket", limit=5) is True


def test_check_rate_allows_again_once_the_window_rolls(monkeypatch):
    fake_now = [1000.0]
    monkeypatch.setattr(middleware.time, "monotonic", lambda: fake_now[0])
    for _ in range(3):
        _check_rate("1.2.3.4", "test", limit=3, window_sec=10)
    assert _check_rate("1.2.3.4", "test", limit=3, window_sec=10) is False
    fake_now[0] += 11  # past the 10s window
    assert _check_rate("1.2.3.4", "test", limit=3, window_sec=10) is True


# ── RateLimitMiddleware ──────────────────────────────────────────────────────

def _rate_limited_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.get("/auth/login")
    def auth_login():
        return {"ok": True}

    @app.get("/voice/verify")
    def voice_verify():
        return {"ok": True}

    @app.get("/tutor/chat")
    def other():
        return {"ok": True}

    return app


def test_rate_limit_middleware_uses_the_auth_bucket_limit(monkeypatch):
    monkeypatch.setattr(middleware, "AUTH_LIMIT", 2)
    client = TestClient(_rate_limited_app())
    assert client.get("/auth/login").status_code == 200
    assert client.get("/auth/login").status_code == 200
    resp = client.get("/auth/login")
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "60"


def test_rate_limit_middleware_buckets_are_independent(monkeypatch):
    # Exhausting the (tiny, patched) auth bucket must not affect a wholly
    # different bucket (voice, or general API) for the same client.
    monkeypatch.setattr(middleware, "AUTH_LIMIT", 1)
    client = TestClient(_rate_limited_app())
    assert client.get("/auth/login").status_code == 200
    assert client.get("/auth/login").status_code == 429
    assert client.get("/voice/verify").status_code == 200
    assert client.get("/tutor/chat").status_code == 200


# ── ExfiltrationGuard ────────────────────────────────────────────────────────

def _guarded_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ExfiltrationGuard)

    @app.get("/export")
    def export_route():
        return {"data": "should never be reached"}

    @app.get("/pod/configs")
    def clean_json():
        return {"student_name": "Ellie"}

    @app.get("/leaky")
    def leaky_json():
        return JSONResponse({"data_key": "should-never-leave-the-server"})

    @app.get("/tutor/chat")
    def sse_route():
        # Deliberately includes a blocked-pattern string in the SSE body —
        # proves the guard really does skip scanning streaming responses,
        # matching the documented behavior in CLAUDE.md's Security Constraints.
        def gen():
            yield 'data: {"data_key": "leaked-if-this-were-scanned"}\n\n'
        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


def test_exfiltration_guard_blocks_known_exfil_endpoints():
    client = TestClient(_guarded_app())
    resp = client.get("/export")
    assert resp.status_code == 404


def test_exfiltration_guard_passes_clean_json_through():
    client = TestClient(_guarded_app())
    resp = client.get("/pod/configs")
    assert resp.status_code == 200
    assert resp.json() == {"student_name": "Ellie"}
    assert resp.headers["content-disposition"] == "inline"


def test_exfiltration_guard_blocks_leaked_key_material_in_json():
    client = TestClient(_guarded_app())
    resp = client.get("/leaky")
    assert resp.status_code == 500
    assert "should-never-leave-the-server" not in resp.text


def test_exfiltration_guard_does_not_scan_sse_streams():
    """Documents the real, current behavior (see CLAUDE.md's Security
    Constraints): SSE responses are never buffered or pattern-scanned — the
    blocked pattern in the stream body passes straight through untouched."""
    client = TestClient(_guarded_app())
    resp = client.get("/tutor/chat")
    assert resp.status_code == 200
    assert "leaked-if-this-were-scanned" in resp.text


# ── SecurityHeadersMiddleware ────────────────────────────────────────────────

def _headers_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return app


def test_security_headers_are_present():
    client = TestClient(_headers_app())
    resp = client.get("/ping")
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert "Strict-Transport-Security" in resp.headers
    assert "Content-Security-Policy" in resp.headers
    assert "server" not in {k.lower() for k in resp.headers.keys()}
