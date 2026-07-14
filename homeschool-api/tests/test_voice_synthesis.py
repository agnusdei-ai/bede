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
    captured = {}

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        _FakeAsyncClient.captured = {"url": url, "headers": headers, "json": json}
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
