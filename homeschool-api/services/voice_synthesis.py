"""
Server-side text-to-speech for Bede's spoken voice.

OpenAI TTS (_synthesize_openai below) — used when OPENAI_API_KEY is set. A
full cloud model; gpt-4o-mini-tts's `instructions` parameter lets us steer
delivery/character in plain English, which is the main lever for actually
sounding like a specific persona rather than a generic preset voice.

Returns None on any failure or when unconfigured, so the caller
(routers/tutor.py) falls back to the browser's own speechSynthesis instead
of erroring — voice output never blocks a session either way.
"""
import logging
from typing import Optional

from core.config import settings

log = logging.getLogger(__name__)

_OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"


async def preload() -> None:
    """No-op placeholder — kept so main.py's startup warm-up call site
    doesn't need to change if a local model is ever reintroduced. OpenAI
    TTS is a live API call with nothing to pre-load locally."""
    return None


def synthesis_configured() -> bool:
    """Whether backend TTS is usable at all — currently just whether
    OPENAI_API_KEY is set."""
    return bool(settings.openai_api_key)


async def _synthesize_openai(text: str) -> Optional[bytes]:
    """OpenAI TTS — returns WAV bytes, or None on any failure (network,
    auth, rate limit) so the caller falls through to browser speech
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
        log.exception("OpenAI TTS request failed — falling back to browser speech")
        return None


async def synthesize_speech(text: str) -> Optional[bytes]:
    """Convert text to spoken audio (WAV bytes) using Bede's configured
    voice. None when OpenAI TTS isn't configured or the call fails — the
    caller stays silent for that line rather than degrading to a
    different, lower-quality voice mid-conversation."""
    if not settings.openai_api_key:
        return None
    return await _synthesize_openai(text)
