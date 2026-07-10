"""
Server-side text-to-speech for Bede's spoken voice.

Two backends, tried in order:

1. OpenAI TTS (services/voice_synthesis.py's _synthesize_openai) — used when
   OPENAI_API_KEY is set. A full cloud model; meaningfully more natural than
   Kokoro, and gpt-4o-mini-tts's `instructions` parameter lets us steer
   delivery/character in plain English, which is the main lever for actually
   sounding like a specific persona rather than a generic preset voice.

2. Kokoro (kokoro-onnx — ONNX Runtime, CPU-friendly, ~82M parameters, ~80MB
   quantized) — the free, fully self-hosted fallback when OPENAI_API_KEY
   isn't set. No per-user API key, no cloud dependency at all. Its ceiling is
   real, though: confirmed against actual listening feedback that no amount
   of KOKORO_VOICE/KOKORO_SPEED tuning gets it past "decent small open
   model" — see core/config.py's comments and docs/VOICE_SETUP.md.

Both gracefully return None on any failure or when unconfigured, so callers
(routers/tutor.py) fall back to the browser's own speechSynthesis instead of
erroring — voice output never blocks a session either way.
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
_OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"

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
    """Best-effort, non-blocking check for whether some backend TTS is likely
    usable — the authoritative check happens lazily in synthesize_speech()."""
    if settings.openai_api_key:
        return True
    model_path, voices_path = _model_paths()
    return model_path.exists() and voices_path.exists()


async def _synthesize_openai(text: str) -> Optional[bytes]:
    """OpenAI TTS — returns WAV bytes, or None on any failure (network,
    auth, rate limit) so the caller falls through to Kokoro/browser speech
    instead of breaking the session."""
    import httpx

    payload = {
        "model": settings.openai_tts_model,
        "voice": settings.openai_tts_voice,
        "input": text,
        "response_format": "wav",
    }
    # Only gpt-4o-mini-tts understands `instructions` — the older tts-1/
    # tts-1-hd models reject unrecognized fields, so omit it for those.
    if settings.openai_tts_instructions and "mini-tts" in settings.openai_tts_model:
        payload["instructions"] = settings.openai_tts_instructions

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                _OPENAI_TTS_URL,
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            return resp.content
    except httpx.HTTPError:
        log.exception("OpenAI TTS request failed — falling back to Kokoro/browser speech")
        return None


def _first_voice_name(voice_spec: str) -> str:
    """First component's bare name, ignoring '+' blend separators and ':weight'
    suffixes — used only to guess the right phonemizer accent (see below)."""
    return voice_spec.split("+")[0].split(":")[0].strip()


def _resolve_voice(kokoro, voice_spec: str):
    """
    KOKORO_VOICE is normally a single name (e.g. "bm_george"), passed straight
    through to kokoro.create(). It can also be a '+'-separated blend of two or
    more voices' style vectors — e.g. "bm_george+bm_lewis" (equal blend) or
    "bm_george:0.7+bm_lewis:0.3" (weighted) — a real, supported technique
    (kokoro.create() accepts a raw style-vector ndarray as well as a name) that
    sometimes rounds off a single voice's rough edges. Only worth trying if a
    single voice alone still sounds too mechanical — see docs/VOICE_SETUP.md.
    """
    parts = voice_spec.split("+")
    if len(parts) == 1:
        return voice_spec  # plain name — let kokoro.create() resolve it as before

    import numpy as np

    blended = None
    total_weight = 0.0
    for part in parts:
        name, _, weight_str = part.strip().partition(":")
        weight = float(weight_str) if weight_str else 1.0
        style = kokoro.get_voice_style(name.strip())
        blended = style * weight if blended is None else blended + style * weight
        total_weight += weight
    return (blended / total_weight).astype(np.float32)


def _synthesize_sync(kokoro, text: str) -> bytes:
    """Blocking inference + WAV encoding — run in an executor."""
    import io
    import soundfile as sf

    # Kokoro's `lang` controls the phonemizer's pronunciation rules, separate
    # from the voice's own acoustic model — pairing a British voice (bm_/bf_)
    # with "en-us" phonemization was making George sound like an American
    # accent forced onto a British voice: neither convincingly English nor
    # natural. Match phonemization to the voice's actual accent.
    lang = "en-gb" if _first_voice_name(settings.kokoro_voice).startswith(("bm_", "bf_")) else "en-us"
    voice = _resolve_voice(kokoro, settings.kokoro_voice)
    samples, sample_rate = kokoro.create(text, voice=voice, speed=settings.kokoro_speed, lang=lang)
    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate, format="WAV")
    return buf.getvalue()


async def synthesize_speech(text: str) -> Optional[bytes]:
    """
    Convert text to spoken audio (WAV bytes) using Bede's configured voice.
    Tries OpenAI TTS first if configured (meaningfully more natural), then
    Kokoro, then gives up. Returns None if nothing is available or every
    attempt fails — never raises, so a voice-output hiccup never breaks the
    tutoring session; the caller falls back to the browser's own speech.
    """
    if settings.openai_api_key:
        audio = await _synthesize_openai(text)
        if audio is not None:
            return audio
        # Falls through to Kokoro/None below rather than returning — an
        # OpenAI hiccup shouldn't lose voice output entirely if Kokoro's
        # model files also happen to be present.

    kokoro = await _get_model()
    if kokoro is None:
        return None

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _synthesize_sync, kokoro, text)
    except Exception:
        log.exception("Kokoro synthesis failed, falling back to browser TTS")
        return None
