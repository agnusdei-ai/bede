"""
Server-side text-to-speech for Bede's spoken voice, via a self-hosted Kokoro
model (kokoro-onnx — ONNX Runtime, CPU-friendly, ~80MB quantized).

Replaces the earlier ElevenLabs cloud integration: no per-user API key, no
per-request network call, no cloud dependency at all — Kokoro runs locally
as part of this same process. The tradeoff is real-time latency without a
GPU is genuinely uncertain on Raspberry Pi-class hardware; that's exactly
what scripts/evaluate_bede_voice.py is for — run it once on the real
deployment target to confirm it's fast enough and to pick KOKORO_VOICE,
before relying on this in a live session.

Gracefully returns None whenever the model isn't loaded or the model files
aren't present (see docs/VOICE_SETUP.md), so callers (routers/tutor.py) fall
back to the browser's own speechSynthesis instead of erroring.
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional

from core.config import settings

log = logging.getLogger(__name__)

_MODEL_FILENAME = "kokoro-v1.0.onnx"
_VOICES_FILENAME = "voices-v1.0.bin"
_SAMPLE_RATE = 24000

_kokoro = None
_load_attempted = False
_load_lock = asyncio.Lock()


def _model_paths() -> tuple[Path, Path]:
    base = Path(settings.kokoro_model_dir)
    return base / _MODEL_FILENAME, base / _VOICES_FILENAME


def _load_model_sync():
    """Blocking model load — run in an executor, never on the event loop."""
    from kokoro_onnx import Kokoro

    model_path, voices_path = _model_paths()
    return Kokoro(str(model_path), str(voices_path))


async def _get_model():
    """Lazily loads the model on first use and caches it. Returns None (and
    logs once) if the model files aren't present or loading fails for any
    reason — never raises, matching this module's fallback contract."""
    global _kokoro, _load_attempted
    if _kokoro is not None:
        return _kokoro
    if _load_attempted:
        return None

    async with _load_lock:
        if _kokoro is not None or _load_attempted:
            return _kokoro
        _load_attempted = True

        model_path, voices_path = _model_paths()
        if not model_path.exists() or not voices_path.exists():
            log.info(
                "Kokoro model files not found at %s — voice output will use the "
                "browser's built-in speech instead. See docs/VOICE_SETUP.md.",
                settings.kokoro_model_dir,
            )
            return None

        try:
            loop = asyncio.get_running_loop()
            _kokoro = await loop.run_in_executor(None, _load_model_sync)
            log.info("Kokoro TTS model loaded from %s", settings.kokoro_model_dir)
        except Exception:
            log.exception("Failed to load Kokoro TTS model — falling back to browser speech")
            return None

        return _kokoro


def synthesis_configured() -> bool:
    """Best-effort, non-blocking check for whether Kokoro is likely usable —
    the authoritative check happens lazily in synthesize_speech(), since
    actually loading the model requires the executor thread."""
    model_path, voices_path = _model_paths()
    return model_path.exists() and voices_path.exists()


def _synthesize_sync(kokoro, text: str) -> bytes:
    """Blocking inference + WAV encoding — run in an executor."""
    import io
    import soundfile as sf

    samples, sample_rate = kokoro.create(text, voice=settings.kokoro_voice, speed=1.0, lang="en-us")
    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate, format="WAV")
    return buf.getvalue()


async def synthesize_speech(text: str) -> Optional[bytes]:
    """
    Convert text to spoken audio (WAV bytes) using Bede's configured voice.
    Returns None if the model isn't available or synthesis fails — never
    raises, so a voice-output hiccup never breaks the tutoring session.
    """
    kokoro = await _get_model()
    if kokoro is None:
        return None

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _synthesize_sync, kokoro, text)
    except Exception:
        log.exception("Kokoro synthesis failed, falling back to browser TTS")
        return None
