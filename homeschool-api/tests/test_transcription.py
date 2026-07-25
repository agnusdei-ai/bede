"""
Tests for services/transcription.py's inference-concurrency guard.

Regression for a real reported failure: on a rapid sequence of hold-to-talk
presses, faster-whisper transcription passes for DIFFERENT streaming-
transcription sessions (services/streaming_transcription.py) could run
concurrently, and since faster-whisper's CTranslate2 backend is itself
internally multi-threaded, concurrent passes fought each other for CPU
instead of running in parallel — turning a normal few-second transcription
into a 30+ second stall, then never resolving at all. transcribe_audio()
now serializes actual inference through a semaphore
(settings.voice_transcription_max_concurrency) so overlapping callers queue
instead of thrashing. See docs/VOICE_SETUP.md's transcription-delay section.
"""
import asyncio

import pytest

import services.transcription as tr


@pytest.fixture(autouse=True)
def _reset_semaphore():
    """The semaphore is created lazily and cached at module level — reset it
    between tests so each test's settings override actually takes effect."""
    tr._inference_semaphore = None
    yield
    tr._inference_semaphore = None


@pytest.mark.asyncio
async def test_concurrent_transcriptions_are_serialized_by_default(monkeypatch):
    """Two overlapping calls must never run _transcribe_sync at the same
    time — proof the semaphore (default concurrency 1) is actually gating
    the executor call, not just decorating it."""
    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    def fake_sync(audio_bytes, language):
        nonlocal in_flight, max_in_flight
        import time
        # Runs in a real executor thread — a plain int increment/decrement
        # without an asyncio primitive is fine here since we only ever read
        # max_in_flight back on the main thread after both calls finish.
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        time.sleep(0.05)
        in_flight -= 1
        return {"text": "x", "language": language}

    monkeypatch.setattr(tr, "_transcribe_sync", fake_sync)

    await asyncio.gather(
        tr.transcribe_audio(b"a", language="en"),
        tr.transcribe_audio(b"b", language="en"),
    )

    assert max_in_flight == 1


@pytest.mark.asyncio
async def test_concurrency_limit_is_configurable(monkeypatch):
    """Raising settings.voice_transcription_max_concurrency lets that many
    passes genuinely overlap — the cap is a deployment tunable, not a
    hardcoded serialization."""
    import time
    in_flight = 0
    max_in_flight = 0

    def fake_sync(audio_bytes, language):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        time.sleep(0.05)
        in_flight -= 1
        return {"text": "x", "language": language}

    monkeypatch.setattr(tr, "_transcribe_sync", fake_sync)
    monkeypatch.setattr(tr.settings, "voice_transcription_max_concurrency", 2)

    await asyncio.gather(
        tr.transcribe_audio(b"a", language="en"),
        tr.transcribe_audio(b"b", language="en"),
        tr.transcribe_audio(b"c", language="en"),
    )

    assert max_in_flight == 2


@pytest.mark.asyncio
async def test_transcribe_audio_still_returns_the_result(monkeypatch):
    """The semaphore must be transparent to the caller's return value."""
    monkeypatch.setattr(
        tr, "_transcribe_sync",
        lambda audio_bytes, language: {"text": "hello", "language": language},
    )

    result = await tr.transcribe_audio(b"audio", language="en")
    assert result == {"text": "hello", "language": "en"}
