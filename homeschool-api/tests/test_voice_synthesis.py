"""
Regression tests for services/voice_synthesis.py — the OpenAI-TTS-first,
Kokoro-fallback voice backend chain.
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


def test_synthesize_speech_falls_back_to_none_when_openai_fails_and_no_kokoro(monkeypatch):
    settings.openai_api_key = "sk-test"
    _FakeAsyncClient.response = _FakeResponse(status_code=500)
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    async def fake_get_model():
        return None
    monkeypatch.setattr(vs, "_get_model", fake_get_model)

    result = asyncio.run(vs.synthesize_speech("hello"))
    assert result is None


def test_synthesize_speech_never_tries_kokoro_when_openai_is_configured(monkeypatch):
    """Regression: a configured OpenAI TTS that fails must never silently
    degrade to Kokoro's noticeably different voice mid-conversation — the
    caller should get None (stay silent for that line), not a surprise
    switch to a different voice. This asserts Kokoro is never even reached,
    not just that the end result happens to be None."""
    settings.openai_api_key = "sk-test"
    _FakeAsyncClient.response = _FakeResponse(status_code=500)
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    async def fail_if_called():
        raise AssertionError("Kokoro must not be tried when OpenAI is configured")
    monkeypatch.setattr(vs, "_get_model", fail_if_called)

    result = asyncio.run(vs.synthesize_speech("hello"))
    assert result is None


def test_synthesis_configured_true_when_openai_key_set():
    settings.openai_api_key = "sk-test"
    assert vs.synthesis_configured() is True


def test_synthesis_configured_false_when_nothing_set(monkeypatch):
    settings.openai_api_key = ""
    monkeypatch.setattr(settings, "kokoro_model_dir", "/nonexistent/path/xyz")
    assert vs.synthesis_configured() is False


def test_resolve_voice_blend():
    import numpy as np

    class FakeKokoro:
        voices = {
            "bm_george": np.array([1.0, 2.0], dtype=np.float32),
            "bm_lewis": np.array([3.0, 4.0], dtype=np.float32),
        }

        def get_voice_style(self, name):
            return self.voices[name]

    k = FakeKokoro()
    assert vs._resolve_voice(k, "bm_george") == "bm_george"

    blended = vs._resolve_voice(k, "bm_george+bm_lewis")
    assert np.allclose(blended, [2.0, 3.0])

    weighted = vs._resolve_voice(k, "bm_george:0.75+bm_lewis:0.25")
    assert np.allclose(weighted, 0.75 * k.voices["bm_george"] + 0.25 * k.voices["bm_lewis"])


@pytest.mark.parametrize("voice_spec,expected_lang", [
    ("bm_george", "en-gb"),
    ("bm_lewis", "en-gb"),
    ("am_adam", "en-us"),
    ("bm_george+bm_lewis", "en-gb"),
    ("am_adam+af_bella", "en-us"),
])
def test_first_voice_name_drives_correct_accent(voice_spec, expected_lang):
    name = vs._first_voice_name(voice_spec)
    lang = "en-gb" if name.startswith(("bm_", "bf_")) else "en-us"
    assert lang == expected_lang
