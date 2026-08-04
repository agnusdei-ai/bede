"""
Tests for services/transcription.py's backend selection
(settings.transcription_provider).

The reason this setting exists is a measured memory failure, not a
preference: faster-whisper's ctranslate2 backend imports torch (~480MB of
RSS on import alone) whenever torch is present in the environment, which put
bede-demo-api at 642MB against Render's 512MB free-tier cap and got it
OOM-killed. services/streaming_transcription.py holds its sessions in memory
in a single process, so each of those restarts destroyed every child's
in-flight voice turn — which reached the browser as `startVoiceStream
failed: Load failed` and looked, from the tablet, like a broken microphone.
See docs/DEMO_HOSTING.md's memory section and docs/VOICE_SETUP.md.

So the load-bearing assertion in this file is a NEGATIVE one:
test_openai_backend_never_touches_the_local_model. Routing the audio
elsewhere saves nothing if anything on that path still imports
faster_whisper — the import IS the cost. The rest guard the property that
makes this safe to ship: a deployment that never sets the option behaves
byte for byte as before, because for a family's self-hosted instance local
transcription is the entire point.
"""
import asyncio

import httpx
import pytest

import services.transcription as tr
from core.config import Settings


class _FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload or {}
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=httpx.Request("POST", "http://x"), response=self
            )


class _FakeClient:
    """Stands in for the pooled httpx.AsyncClient. Records every call and
    replays a scripted sequence of responses/exceptions."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self._script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def _reset_module_state():
    tr._inference_semaphore = None
    tr._openai_http_client = None
    yield
    tr._inference_semaphore = None
    tr._openai_http_client = None


def _use_openai(monkeypatch, client):
    monkeypatch.setattr(tr.settings, "transcription_provider", "openai", raising=False)
    monkeypatch.setattr(tr.settings, "openai_api_key", "sk-test", raising=False)
    monkeypatch.setattr(tr, "_get_openai_http_client", lambda: client)


# ── The default is unchanged ─────────────────────────────────────────────────

def test_local_is_the_default():
    """A family's own instance must not have to know this setting exists."""
    assert Settings().transcription_provider == "local"


def test_uses_local_model_follows_the_setting(monkeypatch):
    assert tr.uses_local_model() is True
    monkeypatch.setattr(tr.settings, "transcription_provider", "openai", raising=False)
    assert tr.uses_local_model() is False


@pytest.mark.asyncio
async def test_local_backend_still_runs_whisper_through_the_semaphore(monkeypatch):
    """The whole local path — executor plus the concurrency guard from
    test_transcription.py — has to be untouched by adding a second backend."""
    seen = {}

    def fake_sync(audio_bytes, language):
        seen["audio"] = audio_bytes
        seen["language"] = language
        return {"text": "hello", "language": language}

    monkeypatch.setattr(tr, "_transcribe_sync", fake_sync)
    result = await tr.transcribe_audio(b"AUDIO", language="es")

    assert result == {"text": "hello", "language": "es"}
    assert seen == {"audio": b"AUDIO", "language": "es"}


# ── The saving is the import that does not happen ────────────────────────────

@pytest.mark.asyncio
async def test_openai_backend_never_touches_the_local_model(monkeypatch):
    """The point of the whole setting. _get_model() is the only thing that
    imports faster_whisper (and so, via ctranslate2, torch) — if the openai
    path can reach it, the ~480MB is still paid and nothing was gained."""
    def explode():
        raise AssertionError("the openai backend must never load the local Whisper model")

    monkeypatch.setattr(tr, "_get_model", explode)
    monkeypatch.setattr(tr, "_transcribe_sync", lambda *a, **k: explode())
    _use_openai(monkeypatch, _FakeClient([_FakeResponse({"text": "hello there"})]))

    result = await tr.transcribe_audio(b"AUDIO", language="en")
    assert result["text"] == "hello there"


def test_preload_is_a_no_op_on_the_openai_backend(monkeypatch):
    """preload() is the call that reliably imports faster_whisper at
    startup. main.py guards it too — both, deliberately, so the saving never
    depends on one call site staying correct."""
    monkeypatch.setattr(tr, "_get_model", lambda: (_ for _ in ()).throw(
        AssertionError("preload must not load the model on the openai backend")
    ))
    monkeypatch.setattr(tr.settings, "transcription_provider", "openai", raising=False)
    tr.preload()  # must not raise


# ── The OpenAI request itself ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_openai_request_carries_the_audio_model_and_language(monkeypatch):
    client = _FakeClient([_FakeResponse({"text": "  spaced  "})])
    _use_openai(monkeypatch, client)
    monkeypatch.setattr(tr.settings, "openai_transcription_model", "gpt-4o-mini-transcribe", raising=False)

    result = await tr.transcribe_audio(b"WAVBYTES", language="es")

    assert result == {"text": "spaced", "language": "es"}
    url, kwargs = client.calls[0]
    assert url == tr._OPENAI_TRANSCRIPTION_URL
    assert kwargs["files"]["file"][1] == b"WAVBYTES"
    assert kwargs["data"]["model"] == "gpt-4o-mini-transcribe"
    # A Spanish session transcribed as English comes back garbled whichever
    # engine does it — the hint has to survive the switch of backend.
    assert kwargs["data"]["language"] == "es"
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test"


@pytest.mark.asyncio
async def test_a_transient_failure_is_retried_once(monkeypatch):
    """Same reasoning as voice_synthesis.py's TTS retry, and it matters more
    here: a failed TTS call costs one spoken line, a failed transcription
    costs the child's whole answer."""
    client = _FakeClient([httpx.ConnectError("boom"), _FakeResponse({"text": "second try"})])
    _use_openai(monkeypatch, client)
    monkeypatch.setattr(tr, "_OPENAI_RETRY_BACKOFF_SECONDS", (0,))

    result = await tr.transcribe_audio(b"AUDIO")
    assert result["text"] == "second try"
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_a_non_retryable_status_is_not_retried(monkeypatch):
    """A bad key or malformed audio will fail identically on a second
    attempt — retrying only makes the child wait longer to be told."""
    client = _FakeClient([_FakeResponse(status_code=401)])
    _use_openai(monkeypatch, client)

    result = await tr.transcribe_audio(b"AUDIO")
    assert result["text"] == ""
    assert "error" in result
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_exhausted_retries_return_the_empty_shape_callers_expect(monkeypatch):
    """routers/voice.py and services/streaming_transcription.py already read
    an empty text as "nothing was heard" — a failure here must not need them
    to learn which backend produced it."""
    client = _FakeClient([httpx.ConnectError("a"), httpx.ConnectError("b")])
    _use_openai(monkeypatch, client)
    monkeypatch.setattr(tr, "_OPENAI_RETRY_BACKOFF_SECONDS", (0,))

    result = await tr.transcribe_audio(b"AUDIO", language="en")
    assert result["text"] == ""
    assert result["language"] == "en"
    assert len(client.calls) == tr._OPENAI_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_aclose_is_safe_when_no_client_was_ever_created():
    """The local backend never builds one — shutdown must not care."""
    await tr.aclose_http_client()


# ── Fail at boot, not at the first child who presses the mic ─────────────────

def test_an_unknown_provider_is_rejected_at_startup():
    with pytest.raises(ValueError, match="TRANSCRIPTION_PROVIDER"):
        Settings(transcription_provider="whisper.cpp")


def test_openai_without_a_key_is_rejected_at_startup():
    """There is deliberately no local model loaded on this setting, so there
    is nothing to fall back to — and a silent fallback would reintroduce the
    very import the setting exists to avoid."""
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        Settings(transcription_provider="openai", openai_api_key="")


def _run_in_fresh_interpreter(provider: str) -> dict:
    """Import services.transcription and run one transcription in a brand-new
    interpreter, reporting which heavyweight modules ended up loaded.

    A subprocess because sys.modules is process-global: some other test in
    this session may legitimately have imported faster_whisper, which would
    make an in-process check meaningless.
    """
    import json
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent(
        f"""
        import asyncio, json, os, sys
        os.environ["TRANSCRIPTION_PROVIDER"] = {provider!r}
        os.environ["OPENAI_API_KEY"] = "sk-test"
        os.environ.setdefault("SECRET_KEY", "test-secret-key-" + "x" * 32)
        os.environ.setdefault("MASTER_SECRET", "test-master-secret-" + "y" * 32)
        os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/t")

        import services.transcription as tr

        class _Resp:
            status_code = 200
            def json(self): return {{"text": "hello"}}
            def raise_for_status(self): pass

        class _Client:
            async def post(self, *a, **k): return _Resp()

        tr._get_openai_http_client = lambda: _Client()
        # The local path genuinely loads the model here; we only care THAT it
        # imported, not that inference produced anything sensible.
        result = asyncio.run(tr.transcribe_audio(b"AUDIO", "en"))

        print("REPORT " + json.dumps({{
            "text": result.get("text"),
            "faster_whisper": "faster_whisper" in sys.modules,
            "ctranslate2": "ctranslate2" in sys.modules,
            "torch": "torch" in sys.modules,
        }}))
        """
    )
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("REPORT "))
    return json.loads(line[len("REPORT "):])


def test_the_local_backend_really_does_import_faster_whisper():
    """The positive control, and the reason the next test means anything.

    Without this, a negative assertion about sys.modules would pass just as
    happily in an environment where faster_whisper was never installed —
    proving nothing about the code. This pins that the import genuinely
    happens on the default path, so its ABSENCE on the other path is a fact
    about the routing rather than about the environment.
    """
    report = _run_in_fresh_interpreter("local")
    assert report["faster_whisper"] is True
    assert report["ctranslate2"] is True


def test_the_openai_backend_leaves_the_local_stack_unimported():
    """The strongest form of the claim, checked for real rather than through
    a mock.

    Every other test here proves the code does not CALL the loader. This one
    proves the process does not PAY for it, which is the thing that was
    actually failing: ~480MB of torch (pulled in by ctranslate2) against a
    512MB cap.

    Note what is and isn't load-bearing here. faster_whisper and ctranslate2
    are direct dependencies and always installed, so those two assertions
    bite everywhere. torch arrives transitively via resemblyzer and is
    installed from a separate CPU-only wheel index in the Docker image (see
    the Dockerfile), so in an environment without it that third assertion
    passes for free — it is checked because it is the one that costs the
    memory, not because it is the one doing the work here.
    """
    report = _run_in_fresh_interpreter("openai")

    assert report["text"] == "hello", "the transcription itself has to still work"
    assert report["faster_whisper"] is False
    assert report["ctranslate2"] is False
    assert report["torch"] is False


# ── What a metered backend must not do five times per turn ───────────────────

@pytest.mark.asyncio
async def test_partials_are_skipped_on_a_metered_backend(monkeypatch):
    """Every pass re-transcribes the WHOLE growing buffer, so at the client's
    4s chunk cadence a 20-second answer would bill roughly five requests and
    re-upload everything captured so far each time — with four of the five
    discarded the instant the final pass lands. The final pass is what
    reaches Bede and is never skipped; only the live preview is."""
    import services.streaming_transcription as st

    calls = []

    async def fake_transcribe(audio, language="en"):
        calls.append(len(audio))
        return {"text": "heard it", "language": language}

    monkeypatch.setattr(st, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(st, "partial_passes_are_affordable", lambda: False)

    session_id = st.start_session(language="en")
    st.push_chunk(session_id, b"\x00\x01" * 8000)   # a partial's worth of audio
    await asyncio.sleep(0.05)
    assert calls == [], "a metered backend must not pay for a discarded preview"

    st.push_chunk(session_id, b"\x00\x01" * 8000)
    st.finish_session(session_id)

    events = [e async for e in st.events(session_id)]
    kinds = [e["type"] for e in events]

    assert len(calls) == 1, "the final pass still runs, exactly once"
    assert "final" in kinds and "done" in kinds
    assert "partial" not in kinds
    assert next(e for e in events if e["type"] == "final")["text"] == "heard it"


@pytest.mark.asyncio
async def test_partials_still_run_on_the_local_backend(monkeypatch):
    """Guards against 'fixing' the cost above by removing live partials for
    everyone — locally the pass costs idle CPU we already own, and the live
    preview is the whole reason the streaming design exists."""
    import services.streaming_transcription as st

    calls = []

    async def fake_transcribe(audio, language="en"):
        calls.append(len(audio))
        return {"text": "heard it", "language": language}

    monkeypatch.setattr(st, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(st, "partial_passes_are_affordable", lambda: True)

    session_id = st.start_session(language="en")
    st.push_chunk(session_id, b"\x00\x01" * 8000)
    await asyncio.sleep(0.05)

    assert calls, "a local backend should still compute a live partial"
    st.finish_session(session_id)
    [_ async for _ in st.events(session_id)]
