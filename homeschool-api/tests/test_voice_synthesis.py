"""
Regression tests for services/voice_synthesis.py — the OpenAI TTS voice
backend. No self-hosted fallback model is used; when OpenAI isn't
configured, synthesis is simply unavailable and the caller falls back to
the browser's own speechSynthesis.
"""
import asyncio

import httpx
import pytest

import services.voice_synthesis as vs
from core.config import settings


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Retries sleep between attempts for real — tests shouldn't actually
    wait, and asserting the sleep call count is a cheap way to confirm the
    retry loop ran the expected number of times."""
    calls = []

    async def _fake_sleep(seconds):
        calls.append(seconds)

    monkeypatch.setattr(vs.asyncio, "sleep", _fake_sleep)
    return calls


@pytest.fixture(autouse=True)
def _reset_fake_client():
    yield
    _FakeAsyncClient.response = None
    _FakeAsyncClient.responses = None
    _FakeAsyncClient.call_count = 0


@pytest.fixture(autouse=True)
def _reset_settings():
    """These tests mutate settings.openai_* directly (simplest way to drive
    the module's branching) — restore afterward so other test files don't
    inherit a mutated global settings object."""
    saved = (
        settings.openai_api_key,
        settings.openai_tts_model,
        settings.openai_tts_voice,
        settings.openai_tts_instructions,
    )
    yield
    (
        settings.openai_api_key,
        settings.openai_tts_model,
        settings.openai_tts_voice,
        settings.openai_tts_instructions,
    ) = saved


class _FakeResponse:
    def __init__(self, status_code=200, content=b"FAKEWAVDATA"):
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)


class _FakeAsyncClient:
    """`response` is used for every call when set; `responses` (a list) is
    popped from left-to-right instead when set, one per successive call —
    lets a test script "fail twice, then succeed" to exercise retries.
    `call_count` lets a test assert exactly how many attempts were made."""
    captured = {}
    response = None
    responses = None
    call_count = 0

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        _FakeAsyncClient.captured = {"url": url, "headers": headers, "json": json}
        _FakeAsyncClient.call_count += 1
        if _FakeAsyncClient.responses is not None:
            return _FakeAsyncClient.responses.pop(0)
        return _FakeAsyncClient.response


def test_mini_tts_model_includes_instructions(monkeypatch):
    settings.openai_api_key = "sk-test"
    settings.openai_tts_model = "gpt-4o-mini-tts"
    settings.openai_tts_voice = "fable"
    settings.openai_tts_instructions = "Speak warmly."
    _FakeAsyncClient.response = _FakeResponse()
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    result = asyncio.run(vs._synthesize_openai("hello"))
    assert result == b"FAKEWAVDATA"
    assert "instructions" in _FakeAsyncClient.captured["json"]
    assert _FakeAsyncClient.captured["json"]["voice"] == "fable"
    assert _FakeAsyncClient.captured["headers"]["Authorization"] == "Bearer sk-test"


def test_legacy_tts_model_omits_instructions(monkeypatch):
    settings.openai_api_key = "sk-test"
    settings.openai_tts_model = "tts-1-hd"
    settings.openai_tts_instructions = "Speak warmly."
    _FakeAsyncClient.response = _FakeResponse()
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    asyncio.run(vs._synthesize_openai("hello"))
    assert "instructions" not in _FakeAsyncClient.captured["json"]


def test_synthesize_speech_prefers_openai_when_configured(monkeypatch):
    settings.openai_api_key = "sk-test"
    settings.openai_tts_model = "gpt-4o-mini-tts"
    _FakeAsyncClient.response = _FakeResponse()
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    result = asyncio.run(vs.synthesize_speech("hello"))
    assert result == b"FAKEWAVDATA"


def test_synthesize_speech_returns_none_when_openai_fails(monkeypatch):
    settings.openai_api_key = "sk-test"
    _FakeAsyncClient.response = _FakeResponse(status_code=500)
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    result = asyncio.run(vs.synthesize_speech("hello"))
    assert result is None


def test_synthesize_speech_returns_none_when_openai_not_configured():
    settings.openai_api_key = ""
    result = asyncio.run(vs.synthesize_speech("hello"))
    assert result is None


def test_synthesis_configured_true_when_openai_key_set():
    settings.openai_api_key = "sk-test"
    assert vs.synthesis_configured() is True


def test_synthesis_configured_false_when_nothing_set():
    settings.openai_api_key = ""
    assert vs.synthesis_configured() is False


# ── Retry behavior ────────────────────────────────────────────────────────────
#
# Both frontends deliberately do NOT fall back to browser speech when
# OpenAI TTS is configured but a single call fails (see module docstring) —
# a transient failure here means that turn has no narration at all, not
# just a lower-quality voice. These tests cover the retry loop added to
# reduce how often a momentary rate-limit or network hiccup costs a whole
# turn's narration.

def test_retries_a_transient_rate_limit_and_succeeds(monkeypatch):
    settings.openai_api_key = "sk-test"
    _FakeAsyncClient.responses = [_FakeResponse(status_code=429), _FakeResponse()]
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    result = asyncio.run(vs.synthesize_speech("hello"))
    assert result == b"FAKEWAVDATA"
    assert _FakeAsyncClient.call_count == 2


def test_retries_two_server_errors_before_succeeding_on_the_third_attempt(monkeypatch):
    settings.openai_api_key = "sk-test"
    _FakeAsyncClient.responses = [
        _FakeResponse(status_code=503), _FakeResponse(status_code=502), _FakeResponse(),
    ]
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    result = asyncio.run(vs.synthesize_speech("hello"))
    assert result == b"FAKEWAVDATA"
    assert _FakeAsyncClient.call_count == 3


def test_gives_up_after_exhausting_all_retries_on_persistent_failure(monkeypatch):
    settings.openai_api_key = "sk-test"
    _FakeAsyncClient.response = _FakeResponse(status_code=503)
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    result = asyncio.run(vs.synthesize_speech("hello"))
    assert result is None
    assert _FakeAsyncClient.call_count == 3


def test_does_not_retry_a_non_retryable_client_error(monkeypatch):
    """A bad API key (401) or malformed request (400) will never succeed on
    retry — retrying just adds latency before the inevitable failure."""
    settings.openai_api_key = "sk-test"
    _FakeAsyncClient.response = _FakeResponse(status_code=401)
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    result = asyncio.run(vs.synthesize_speech("hello"))
    assert result is None
    assert _FakeAsyncClient.call_count == 1


def test_retries_a_network_level_error_not_just_a_bad_status(monkeypatch):
    """A timeout or connection error never reaches raise_for_status() at
    all — the retry loop must catch these too, not just bad HTTP statuses."""
    settings.openai_api_key = "sk-test"

    class _FlakyThenOkClient(_FakeAsyncClient):
        async def post(self, url, headers=None, json=None):
            _FakeAsyncClient.call_count += 1
            if _FakeAsyncClient.call_count == 1:
                raise httpx.ConnectTimeout("connection timed out")
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _FlakyThenOkClient)

    result = asyncio.run(vs.synthesize_speech("hello"))
    assert result == b"FAKEWAVDATA"
    assert _FakeAsyncClient.call_count == 2


def test_sleeps_between_retries_using_the_configured_backoff(monkeypatch, _no_real_sleep):
    settings.openai_api_key = "sk-test"
    _FakeAsyncClient.response = _FakeResponse(status_code=503)
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    asyncio.run(vs.synthesize_speech("hello"))
    # 3 attempts means 2 gaps between them, not a sleep after the final
    # (already-given-up) attempt.
    assert _no_real_sleep == list(vs._RETRY_BACKOFF_SECONDS)
