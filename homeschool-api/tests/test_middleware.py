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


# ── The CSP's CONTENT, not just its presence ─────────────────────────────────
#
# Found by mutation audit (docs/GUARD_AUDIT.md): changing frame-ancestors from
# 'none' to * — removing clickjacking protection outright — left all 2181
# tests green. test_security_headers_are_present asserts
#
#     assert "Content-Security-Policy" in resp.headers
#
# which is satisfied by `default-src *` just as happily as by the real policy.
# Presence is not a property worth asserting on its own; a header that exists
# and permits everything is indistinguishable from no header, except that it
# reads as covered.
#
# X-Frame-Options: DENY is asserted properly above and still denies framing in
# browsers that honour it, so the mutation was not a total exposure — but
# frame-ancestors is the modern control and X-Frame-Options is deprecated, so
# the CSP is the one that has to hold on its own.

def _csp_directives() -> dict[str, str]:
    client = TestClient(_headers_app())
    csp = client.get("/ping").headers["Content-Security-Policy"]
    out = {}
    for part in csp.split(";"):
        part = part.strip()
        if not part:
            continue
        name, _, value = part.partition(" ")
        out[name] = value.strip()
    return out


def test_csp_denies_framing_outright():
    """The mutation that went uncaught. 'none' is the whole point: anything
    else here permits some origin to frame a live tutoring session."""
    assert _csp_directives().get("frame-ancestors") == "'none'"


def test_csp_confines_the_directives_that_matter_to_self():
    directives = _csp_directives()
    for name in ("default-src", "script-src", "connect-src", "base-uri", "form-action"):
        assert directives.get(name) == "'self'", (
            f"CSP {name} is {directives.get(name)!r}, not 'self' — this is what "
            "stops a page loading or posting somewhere it should not"
        )


def test_csp_never_permits_unsafe_eval_and_confines_unsafe_inline_to_styles():
    """unsafe-inline is deliberately allowed for style-src only (Tailwind
    needs it — see the _CSP comment). Anywhere else, and especially
    unsafe-eval anywhere at all, is a loosening that must be deliberate."""
    directives = _csp_directives()
    for name, value in directives.items():
        assert "unsafe-eval" not in value, f"CSP {name} permits unsafe-eval"
        if name != "style-src":
            assert "unsafe-inline" not in value, f"CSP {name} permits unsafe-inline"


def test_csp_has_no_wildcard_source():
    """A single '*' anywhere undoes whichever directive it appears in, which
    is exactly how the uncaught mutation worked."""
    for name, value in _csp_directives().items():
        assert "*" not in value, f"CSP {name} contains a wildcard source: {value!r}"
