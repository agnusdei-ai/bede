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
    InstanceIdHeaderMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    _check_rate,
)
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient


def setup_function():
    """Module-level sliding-window state, shared across every app instance —
    reset it so one test's requests can't push another test over its limit."""
    middleware.reset_rate_limiter()


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


# ── ExfiltrationGuard + GZip, assembled in main.py's real order ─────────────
# The per-middleware tests above each build a throwaway app with ONE
# middleware, so they can't see an ordering bug that only exists when
# multiple middlewares are stacked together. This section reconstructs the
# real main.py stack (ExfiltrationGuard, then GZip added last/outermost —
# see main.py's ordering comment) to guard against exactly that: an earlier
# revision had GZip added FIRST, making it the innermost layer instead of
# the outermost one, so it compressed responses before ExfiltrationGuard
# ever inspected them — every _BLOCKED_PATTERNS check silently stopped
# matching on any gzip-eligible response (which is any response over
# `minimum_size` bytes from a client sending `Accept-Encoding: gzip`, i.e.
# effectively every browser).

def _guarded_and_compressed_app() -> FastAPI:
    app = FastAPI()
    # Same relative order as main.py: ExfiltrationGuard added first (more
    # inner), GZip added last (outermost) — GZip must see ExfiltrationGuard's
    # already-scanned output, not the reverse.
    app.add_middleware(ExfiltrationGuard)
    app.add_middleware(GZipMiddleware, minimum_size=500)

    @app.get("/leaky-and-big")
    def leaky_json():
        # Padded well past GZipMiddleware's minimum_size=500 so compression
        # actually engages — the bug only manifests once GZip has something
        # worth compressing.
        return JSONResponse({"data_key": "should-never-leave-the-server", "pad": "x" * 800})

    return app


def test_exfiltration_guard_still_scans_a_gzip_eligible_response_in_the_assembled_stack():
    client = TestClient(_guarded_and_compressed_app())
    # Explicitly request gzip, matching every real browser — the bug was
    # invisible to httpx's default TestClient behavior otherwise not
    # sending Accept-Encoding, so this must be explicit to actually exercise
    # the failure mode.
    resp = client.get("/leaky-and-big", headers={"accept-encoding": "gzip"})
    assert resp.status_code == 500
    assert "should-never-leave-the-server" not in resp.text


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


# ── InstanceIdHeaderMiddleware ───────────────────────────────────────────────
# Diagnostic added after a real report: a family's voice-stream session
# opened fine, then the very next chunk/finish call against that SAME
# session id 404'd seconds later ("Unknown or finished streaming session"),
# well under services/streaming_transcription.py's 180s TTL — exactly the
# shape cross-instance routing under Render autoscaling produces. This
# middleware exists to make that provable from a browser trace instead of
# argued from timing alone. See core/instance_id.py.

def _instance_id_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(InstanceIdHeaderMiddleware)

    @app.get("/voice/stream/{session_id}/events")
    def voice_events(session_id: str):
        return {"ok": True}

    @app.post("/voice/stream/{session_id}/chunk")
    def voice_chunk(session_id: str):
        # Mirrors routers/voice.py's own 404 on an unknown/cross-instance
        # session — the exact case this header has to survive, since it's
        # the one that actually needs diagnosing.
        raise HTTPException(status_code=404, detail="Unknown or finished streaming session")

    @app.get("/pod/configs")
    def pod_configs():
        return {"configs": []}

    return app


def test_instance_id_header_present_on_voice_stream_success():
    client = TestClient(_instance_id_app())
    resp = client.get("/voice/stream/abc123/events")
    assert resp.status_code == 200
    assert resp.headers["X-Bede-Instance"]  # non-empty, whatever the value


def test_instance_id_header_present_on_voice_stream_404():
    # The case that actually matters: a 404 from routers/voice.py is
    # produced by raising HTTPException, a different code path than a
    # normal 2xx return. If this header only survived the success path, the
    # one response that needs it most would be silent.
    client = TestClient(_instance_id_app())
    resp = client.post("/voice/stream/abc123/chunk")
    assert resp.status_code == 404
    assert resp.headers["X-Bede-Instance"]


def test_instance_id_header_absent_outside_voice_stream():
    # Deliberately scoped, not a general fingerprinting surface — see the
    # middleware's own docstring. An ordinary endpoint must not gain a new
    # identifying header just because this diagnostic exists.
    client = TestClient(_instance_id_app())
    resp = client.get("/pod/configs")
    assert resp.status_code == 200
    assert "X-Bede-Instance" not in resp.headers


def test_instance_id_is_stable_across_requests_within_one_process():
    # core/instance_id.py resolves INSTANCE_ID once at import time — two
    # requests to the same running process must report the identical value,
    # or the diagnostic couldn't tell "different instance" from "same
    # instance, value changed for no reason".
    client = TestClient(_instance_id_app())
    first = client.get("/voice/stream/abc123/events").headers["X-Bede-Instance"]
    second = client.get("/voice/stream/xyz789/events").headers["X-Bede-Instance"]
    assert first == second


# ── InstanceIdHeaderMiddleware + CORS, assembled in main.py's real order ────
# A cross-origin fetch() silently drops any response header that isn't
# CORS-safelisted or explicitly exposed — res.headers.get('X-Bede-Instance')
# would return null forever on the demo's split-origin setup (Cloudflare
# Pages frontend, Render backend) without expose_headers naming it. This is
# exactly the ExfiltrationGuard+GZip lesson above repeated for a second pair
# of middleware: a single-middleware test can't see an assembly-order or
# cross-cutting-config bug that only exists once real middleware is stacked.

def _instance_id_with_cors_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(InstanceIdHeaderMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://agnusdei.ai"],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Bede-Instance"],
    )

    @app.get("/voice/stream/{session_id}/events")
    def voice_events(session_id: str):
        return {"ok": True}

    return app


def test_instance_id_header_is_exposed_across_origins():
    client = TestClient(_instance_id_with_cors_app())
    resp = client.get(
        "/voice/stream/abc123/events",
        headers={"Origin": "https://agnusdei.ai"},
    )
    assert resp.status_code == 200
    assert resp.headers["X-Bede-Instance"]
    exposed = {h.strip() for h in resp.headers.get("access-control-expose-headers", "").split(",")}
    assert "X-Bede-Instance" in exposed


def test_instance_id_header_is_dropped_without_expose_headers():
    # The regression this whole section exists to prevent: build the SAME
    # stack with expose_headers omitted, and confirm the browser-visible
    # contract actually breaks — proving the assertion above is testing
    # something real, not a tautology.
    app = FastAPI()
    app.add_middleware(InstanceIdHeaderMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://agnusdei.ai"],
        allow_methods=["GET"],
    )

    @app.get("/voice/stream/{session_id}/events")
    def voice_events(session_id: str):
        return {"ok": True}

    client = TestClient(app)
    resp = client.get(
        "/voice/stream/abc123/events",
        headers={"Origin": "https://agnusdei.ai"},
    )
    assert resp.status_code == 200
    # The header is genuinely on the wire (this IS the raw HTTP response,
    # unlike a browser's fetch()) — what's missing is the CORS opt-in that
    # would let client-side JS actually read it.
    assert resp.headers["X-Bede-Instance"]
    assert "access-control-expose-headers" not in {k.lower() for k in resp.headers.keys()}
