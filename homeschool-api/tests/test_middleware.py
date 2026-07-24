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

    @app.post("/voice/stream/start")
    def voice_stream_start():
        return {"ok": True}

    @app.post("/voice/stream/{session_id}/chunk")
    def voice_stream_chunk(session_id: str):
        return {"ok": True}

    @app.post("/voice/stream/{session_id}/finish")
    def voice_stream_finish(session_id: str):
        return {"ok": True}

    @app.get("/voice/stream/{session_id}/events")
    def voice_stream_events(session_id: str):
        return {"ok": True}

    @app.get("/tutor/chat")
    def other():
        return {"ok": True}

    @app.get("/auth/recovery/methods")
    def recovery_methods():
        return {"ok": True}

    return app


def test_rate_limit_middleware_uses_the_auth_bucket_limit(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "rate_limit_auth_per_minute", 2)
    client = TestClient(_rate_limited_app())
    assert client.get("/auth/login").status_code == 200
    assert client.get("/auth/login").status_code == 200
    resp = client.get("/auth/login")
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "60"


def test_rate_limit_middleware_buckets_are_independent(monkeypatch):
    from core.config import settings

    # Exhausting the (tiny, patched) auth bucket must not affect a wholly
    # different bucket (voice, or general API) for the same client.
    monkeypatch.setattr(settings, "rate_limit_auth_per_minute", 1)
    client = TestClient(_rate_limited_app())
    assert client.get("/auth/login").status_code == 200
    assert client.get("/auth/login").status_code == 429
    assert client.get("/voice/verify").status_code == 200
    assert client.get("/tutor/chat").status_code == 200


# Regression coverage for a real failure confirmed live on the public demo
# via a debug-panel trace: startVoiceStream failing on every attempt after
# only a handful of mic presses. Root cause — one voice utterance under the
# streaming-transcription rewrite costs ~4 requests (start, events, at least
# one chunk, finish) against what used to be a "20 utterances/minute" budget
# sized for the old single-shot /voice/transcribe (1 request per utterance).
def test_voice_stream_start_uses_the_stricter_voice_bucket(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "rate_limit_voice_per_minute", 2)
    client = TestClient(_rate_limited_app())
    assert client.post("/voice/stream/start").status_code == 200
    assert client.post("/voice/stream/start").status_code == 200
    assert client.post("/voice/stream/start").status_code == 429


def test_voice_stream_session_mechanics_do_not_share_the_new_session_bucket(monkeypatch):
    from core.config import settings

    # A tiny "voice" (new-session) budget, exhausted immediately — but the
    # already-approved session's own chunk/finish/events calls must still go
    # through, since they aren't new attempts. This is the actual regression:
    # before the fix, these shared the same bucket as /voice/stream/start and
    # a real multi-turn conversation could exhaust it after only a few taps.
    monkeypatch.setattr(settings, "rate_limit_voice_per_minute", 1)
    client = TestClient(_rate_limited_app())
    assert client.post("/voice/stream/start").status_code == 200
    assert client.post("/voice/stream/start").status_code == 429

    for _ in range(10):
        assert client.post("/voice/stream/sess-1/chunk").status_code == 200
    assert client.post("/voice/stream/sess-1/finish").status_code == 200
    assert client.get("/voice/stream/sess-1/events").status_code == 200


def test_voice_stream_session_bucket_has_its_own_limit(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "rate_limit_voice_stream_session_per_minute", 2)
    client = TestClient(_rate_limited_app())
    assert client.post("/voice/stream/sess-1/chunk").status_code == 200
    assert client.post("/voice/stream/sess-1/chunk").status_code == 200
    assert client.post("/voice/stream/sess-1/chunk").status_code == 429
    # Still independent from the "voice" (new-session) bucket.
    assert client.post("/voice/stream/start").status_code == 200


# Regression coverage for a real failure found during live browser
# verification of the account-lockout/recovery feature: the 10 failed
# /auth/login attempts that trip parent_lockout.py's own lockout also
# exhausted the shared "auth" bucket, so the parent's very next call to
# GET /auth/recovery/methods 429'd too — and AccountRecovery.tsx had no way
# to tell that transient 429 apart from "recovery isn't configured",
# showing a misleading permanent-looking error at exactly the moment
# recovery exists to help. /auth/recovery/* now gets its own bucket.
def test_auth_recovery_has_its_own_bucket_independent_of_login(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "rate_limit_auth_per_minute", 1)
    client = TestClient(_rate_limited_app())
    assert client.get("/auth/login").status_code == 200
    assert client.get("/auth/login").status_code == 429
    # Exhausting the login bucket must not touch the recovery bucket.
    assert client.get("/auth/recovery/methods").status_code == 200


def test_auth_recovery_bucket_has_its_own_limit(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "rate_limit_account_recovery_per_minute", 2)
    client = TestClient(_rate_limited_app())
    assert client.get("/auth/recovery/methods").status_code == 200
    assert client.get("/auth/recovery/methods").status_code == 200
    resp = client.get("/auth/recovery/methods")
    assert resp.status_code == 429
    # Still independent from the plain "auth" (login) bucket.
    assert client.get("/auth/login").status_code == 200


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
