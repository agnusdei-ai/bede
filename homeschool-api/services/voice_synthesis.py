"""
Server-side text-to-speech for Bede's spoken voice, via ElevenLabs.

Self-hosted neural voice cloning (Chatterbox, XTTS) was considered instead, but
needs a real GPU (~8GB+ VRAM) for real-time latency — not realistic on the
Raspberry Pi-class hardware this app targets. A cloud API keeps the host
lightweight: it just proxies the request and streams back audio bytes.

Gracefully returns None when unconfigured so callers (routers/tutor.py) can
fall back to the browser's own speechSynthesis instead of erroring.
"""
import logging

import httpx

from core.config import settings

log = logging.getLogger(__name__)

_ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


def synthesis_configured() -> bool:
    return bool(settings.elevenlabs_api_key and settings.elevenlabs_voice_id)


async def synthesize_speech(text: str) -> bytes | None:
    """
    Convert text to spoken audio (MP3 bytes) using Bede's configured voice.
    Returns None if unconfigured or the request fails — never raises, so a
    voice-output hiccup never breaks the tutoring session itself.
    """
    if not synthesis_configured():
        return None

    url = _ELEVENLABS_TTS_URL.format(voice_id=settings.elevenlabs_voice_id)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                headers={
                    "xi-api-key": settings.elevenlabs_api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json={
                    "text": text,
                    "model_id": "eleven_turbo_v2_5",
                    "voice_settings": {"stability": 0.55, "similarity_boost": 0.8},
                },
            )
            resp.raise_for_status()
            return resp.content
    except httpx.HTTPError as exc:
        log.warning("ElevenLabs synthesis failed, falling back to browser TTS: %s", exc)
        return None
