"""
Server-side text-to-speech: Bede's spoken voice.

Owner decisions 2026-11-18 (docs/DECISIONS.md entry 46): every feature speaks
in Bede's voice and never in another. Bede's voice comes from exactly one
place per deployment, chosen by `active_provider()`:

- **openai** (`_synthesize_openai`): OpenAI's TTS, Bede's reference voice, the
  default whenever OPENAI_API_KEY is set (installed Bede and the demo alike).
- **local** (`_synthesize_local`): an OPTIONAL Piper voice server,
  `voice-service/`, run as a separate process, used only when
  TTS_PROVIDER=local asks for it. It is development and testing, never the
  default, never a fallback for a failed cloud line, and never a launch
  dependency. When it is asked for, a cloud voice is NOT used for that
  deployment, not even when a line fails.
- **none**: no voice. Bede is silent; neither frontend substitutes the
  browser's own voice, because it is not Bede's.

Returns None on any failure or when unconfigured, and the line stays silent
rather than switching voice. A transient failure therefore costs that line's
narration, so each provider retries transient failures once.

No text is logged and nothing is kept after the request, on either path.
"""
import asyncio
import logging
from typing import NamedTuple, Optional

import httpx

from core.config import settings

log = logging.getLogger(__name__)

_OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"

# This used to request "wav", which is uncompressed PCM — at OpenAI's 24kHz
# 16-bit mono that is 48KB for every single second of speech, so a 30-second
# line of Bede's is ~1.4MB on the wire. The whole utterance is synthesized,
# buffered, and only then sent (routers/tutor.py's /speak returns one body),
# so those bytes land squarely between the child asking and hearing anything.
# On a slow home connection that is seconds of silence per turn, and it hurts
# a Spanish session hardest: Spanish runs roughly 15-25% longer than English
# for the same content, so the same lesson produces proportionally more audio
# seconds and therefore proportionally more bytes.
#
# First tried MP3 (~6x smaller for speech, "no perceptible quality cost"
# assumed rather than confirmed). Reported back from real use as sounding
# "like a lisp," with "a residual echo" — that description is close to a
# textbook match for an MP3-specific artifact, not a coincidence. MP3's
# transform coding is well known to spread quantization noise backward in
# time around a sharp transient ("pre-echo"), and sibilants/consonants
# (s, sh, f, t — exactly what a lisp complaint calls out) are the sharpest,
# most transient-heavy content in speech. Bede's voice is slow, measured,
# and softly spoken (see openai_tts_instructions below) — lots of soft
# consonants, lots of quiet space around them for pre-echo smearing to be
# audible in, close to a worst case for this specific artifact.
#
# AAC uses temporal noise shaping specifically to control this class of
# artifact, so it should not exhibit it the same way at a similar bitrate,
# while keeping most of MP3's size win over WAV. It is also Apple's own
# preferred/native audio codec, which reinforces rather than fights the
# tablet-first reasoning below that already ruled out Opus.
#
# Not verified by ear from this change alone — same caveat as the MP3
# change it replaces. If a lisp/echo report recurs against AAC, that points
# away from codec choice entirely: two different lossy codecs producing the
# same complaint would argue for reverting to WAV and looking at playback
# overlap instead (see docs/VOICE_SETUP.md's "Diagnosing a reported speech
# echo," a separate, still-open investigation into overlapping clips on the
# shared <audio> element — this change addresses a codec-artifact
# hypothesis, not that one).
#
# Changes nothing about pacing — that is settings.openai_tts_speed, a
# separate lever. Opus would be smaller still (~16x) and, like AAC, avoids
# MP3's pre-echo behavior, but Safari/iOS support for it in <audio> is
# patchy and this is a tablet-first product, so it's not the first thing to
# reach for. The frontends read the response with res.blob() and hand it to
# createObjectURL, so the blob inherits whatever Content-Type /speak sets
# and no client change is needed — but the two must agree, which is why the
# media type is derived here rather than restated.
AUDIO_FORMAT = "aac"
AUDIO_MEDIA_TYPE = "audio/aac"
# The local voice server answers with WAV: it runs on the same machine or
# network, so the size that made AAC worth it over the internet costs little.
LOCAL_AUDIO_MEDIA_TYPE = "audio/wav"
# A local voice runs on the family's own CPU, where a long line can take a
# few seconds to synthesize; this bounds a hung server, not a slow sentence.
_LOCAL_REQUEST_TIMEOUT_SECONDS = 30.0
_HEALTH_TIMEOUT_SECONDS = 2.0


class SpokenAudio(NamedTuple):
    audio: bytes
    media_type: str

# Retried: a rate limit or transient server error is worth a second try.
# NOT retried: 400 (bad request — e.g. text too long) and 401/403 (bad key)
# will never succeed on retry, so retrying them only adds latency before
# the inevitable failure.
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
# Deliberately capped tight: this whole call sits in the middle of a live
# conversational turn, not a background job — every extra second here is a
# second the child watches a spinner. 2 attempts (1 retry) at a 10s
# per-attempt ceiling bounds the worst case at roughly 20s instead of the
# ~90s three 30s-timeout attempts could reach; a genuinely hung connection
# should fail fast enough here to still feel responsive, and the frontend
# no longer blocks the whole UI on this call regardless (see
# homeschool-tutor's/demo's send() — TTS is fire-and-forget there now).
_REQUEST_TIMEOUT_SECONDS = 10.0
_MAX_ATTEMPTS = 2
_RETRY_BACKOFF_SECONDS = (0.5,)

# A fresh httpx.AsyncClient() per call — the previous pattern here — pays a
# full new TCP+TLS handshake to OpenAI on every single line Bede speaks,
# with the connection then torn down immediately after one request: fast
# and short-lived, the opposite of what a connection to the same host
# repeatedly should be. Reusing one pooled client keeps a warm connection
# alive between calls (real latency savings on the common path) and, via
# max_connections, doubles as throttling: a request past the cap WAITS for
# a free pooled connection rather than firing immediately, capping how many
# concurrent requests this process ever sends to OpenAI regardless of how
# much concurrent user traffic Render is handling. ai_service.py's
# Anthropic client already follows this shared-singleton pattern; this
# brings TTS in line with it.
#
# Scoped to one process: on a single Render instance this is a real,
# global cap. If the deployment is horizontally scaled across multiple
# instances, each instance holds its own independent pool — the true
# fleet-wide concurrent request count is instance_count × max_connections,
# not max_connections alone. A cross-instance cap would need a shared
# store (Redis, a Postgres-backed token bucket) this app doesn't have;
# out of scope here, called out so it isn't assumed to be a global
# guarantee it isn't.
_http_client: Optional[httpx.AsyncClient] = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT_SECONDS,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _http_client


async def aclose_http_client() -> None:
    """Called from main.py's lifespan shutdown — closes the pooled
    connections cleanly rather than leaving them for the OS to reclaim."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


async def preload() -> None:
    """No-op: neither voice loads anything inside this process. The local
    voice's model lives in its own process (voice-service/)."""
    return None


def active_provider() -> Optional[str]:
    """"local", "openai" or None. See the module docstring and
    Settings.tts_provider; the config validator has already refused an
    unknown provider or a non-local LOCAL_TTS_URL."""
    choice = (settings.tts_provider or "").strip().lower()
    if choice == "none":
        return None
    if choice == "local":
        return "local" if settings.local_tts_url else None
    if choice == "openai":
        return "openai" if settings.openai_api_key else None
    # Auto (the default) never picks the local voice: Piper is an optional
    # development voice that has to be asked for with TTS_PROVIDER=local
    # (owner direction 2026-11-20, docs/DECISIONS.md entry 46). Merely having
    # a LOCAL_TTS_URL set changes nothing.
    return "openai" if settings.openai_api_key else None


def unconfigured_reason() -> Optional[str]:
    """Why Bede has no voice, for Parent Setup: "off" when an operator turned
    speech off on purpose (TTS_PROVIDER=none), "not_set_up" when nothing is
    configured yet (no OpenAI key, or the optional Piper voice asked for with
    no URL), and None when a voice is configured. Names no provider, key or
    address."""
    if active_provider() is not None:
        return None
    if (settings.tts_provider or "").strip().lower() == "none":
        return "off"
    return "not_set_up"


def synthesis_configured() -> bool:
    """Whether Bede has a voice at all on this deployment."""
    return active_provider() is not None


async def voice_available(locale: str) -> bool:
    """Whether Bede can speak right now in this language, so a screen can
    choose not to serve items that only work by ear. For the local voice this
    asks its /health (no text is sent) and needs a voice for the language;
    a down or slow server answers False. For the cloud voice it answers
    whether one is configured, since checking would itself be a billed call."""
    provider = active_provider()
    if provider == "openai":
        return True
    if provider != "local":
        return False
    from core.voice_url import parse_voice_url
    base = parse_voice_url(settings.local_tts_url)
    try:
        resp = await _get_http_client().get(f"{base}/health", timeout=_HEALTH_TIMEOUT_SECONDS)
        resp.raise_for_status()
        voices = resp.json().get("voices", [])
    except (httpx.HTTPError, ValueError, AttributeError):
        return False
    return (locale or "en").split("-", 1)[0].lower() in voices


async def _synthesize_local(text: str, locale: str) -> Optional[bytes]:
    """Bede's local voice: POST the line to voice-service/'s /synthesize and
    get WAV back. Never falls back to another voice. The text goes only to
    LOCAL_TTS_URL, which core/voice_url.py has already held to this machine or
    its private network, and is never logged."""
    from core.voice_url import parse_voice_url
    base = parse_voice_url(settings.local_tts_url)
    if not base:
        return None
    client = _get_http_client()
    for attempt in range(_MAX_ATTEMPTS):
        try:
            resp = await client.post(
                f"{base}/synthesize",
                json={"text": text, "locale": locale},
                timeout=_LOCAL_REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            if not resp.content:
                log.warning("Local voice returned no audio")
                return None
            return resp.content
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _RETRYABLE_STATUS_CODES:
                log.warning("Local voice request failed with a non-retryable status: %s", exc.response.status_code)
                return None
            log.warning("Local voice request failed with status %s (attempt %d/%d)", exc.response.status_code, attempt + 1, _MAX_ATTEMPTS)
        except httpx.HTTPError as exc:
            log.warning("Local voice request failed (attempt %d/%d): %s", attempt + 1, _MAX_ATTEMPTS, type(exc).__name__)
        if attempt < _MAX_ATTEMPTS - 1:
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS[attempt])
    log.error("Local voice failed after %d attempts; this line will be silent", _MAX_ATTEMPTS)
    return None


async def _synthesize_openai(text: str) -> Optional[bytes]:
    from core.coppa_provider_policy import require_external_feature
    require_external_feature("speech synthesis")
    """OpenAI TTS — returns AAC bytes (see AUDIO_FORMAT), or None if every attempt fails
    (network error, auth failure, or a non-retryable/exhausted-retry
    status). See module docstring for why retrying transient failures
    matters here specifically."""
    payload = {
        "model": settings.openai_tts_model,
        "voice": settings.openai_tts_voice,
        "input": text,
        "response_format": AUDIO_FORMAT,
        "speed": settings.openai_tts_speed,
    }
    # Only gpt-4o-mini-tts understands `instructions` — the older tts-1/
    # tts-1-hd models reject unrecognized fields, so omit it for those.
    if settings.openai_tts_instructions and "mini-tts" in settings.openai_tts_model:
        payload["instructions"] = settings.openai_tts_instructions

    client = _get_http_client()
    for attempt in range(_MAX_ATTEMPTS):
        try:
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


async def synthesize_speech(text: str, locale: str = "en") -> Optional[SpokenAudio]:
    """Speak `text` in Bede's voice. None when no voice is configured or the
    configured one fails: the caller stays silent for that line rather than
    switching to another voice."""
    provider = active_provider()
    if provider == "local":
        audio = await _synthesize_local(text, locale)
        return SpokenAudio(audio, LOCAL_AUDIO_MEDIA_TYPE) if audio else None
    if provider == "openai":
        audio = await _synthesize_openai(text)
        return SpokenAudio(audio, AUDIO_MEDIA_TYPE) if audio else None
    return None
