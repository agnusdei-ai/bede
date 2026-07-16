"""
Server-side text-to-speech for Bede's spoken voice.

OpenAI TTS (_synthesize_openai below) — used when OPENAI_API_KEY is set. A
full cloud model; gpt-4o-mini-tts's `instructions` parameter lets us steer
delivery/character in plain English, which is the main lever for actually
sounding like a specific persona rather than a generic preset voice.

Returns None on any failure or when unconfigured. Both frontends
(homeschool-tutor's and the demo's own useTextToSpeech.ts) deliberately do
NOT fall back to the browser's speechSynthesis when TTS is configured but
one call fails — that line just stays silent rather than audibly switching
voices mid-conversation (see either frontend's own comment on this). That
makes a transient failure here more costly than it looks: it isn't
"degrade gracefully to a different voice," it's "this turn has no spoken
narration at all." _synthesize_openai retries transient failures (a
timeout, a rate limit, a 5xx) a couple of times before giving up, since a
brief network hiccup or momentary rate-limit shouldn't cost a whole turn's
narration when a second attempt would likely succeed.
"""
import asyncio
import logging
from typing import Optional

from core.config import settings

log = logging.getLogger(__name__)

_OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"

# Retried: a rate limit or transient server error is worth a second try.
# NOT retried: 400 (bad request — e.g. text too long) and 401/403 (bad key)
# will never succeed on retry, so retrying them only adds latency before
# the inevitable failure.
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = (0.5, 1.0)


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
    """OpenAI TTS — returns WAV bytes, or None if every attempt fails
    (network error, auth failure, or a non-retryable/exhausted-retry
    status). See module docstring for why retrying transient failures
    matters here specifically."""
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

    for attempt in range(_MAX_ATTEMPTS):
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
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _RETRYABLE_STATUS_CODES:
                log.warning("OpenAI TTS request failed with a non-retryable status: %s", exc.response.status_code)
                return None
            log.warning("OpenAI TTS request failed with status %s (attempt %d/%d)", exc.response.status_code, attempt + 1, _MAX_ATTEMPTS)
        except httpx.HTTPError:
            log.warning("OpenAI TTS request failed (attempt %d/%d)", attempt + 1, _MAX_ATTEMPTS, exc_info=True)
        if attempt < _MAX_ATTEMPTS - 1:
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS[attempt])
    log.error("OpenAI TTS request failed after %d attempts — this turn will have no spoken narration", _MAX_ATTEMPTS)
    return None


async def synthesize_speech(text: str) -> Optional[bytes]:
    """Convert text to spoken audio (WAV bytes) using Bede's configured
    voice. None when OpenAI TTS isn't configured or every retry attempt
    fails — the caller stays silent for that line rather than degrading to
    a different, lower-quality voice mid-conversation."""
    if not settings.openai_api_key:
        return None
    return await _synthesize_openai(text)
