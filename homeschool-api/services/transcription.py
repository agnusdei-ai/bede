"""
Server-side speech-to-text. Two backends behind one `transcribe_audio()`,
selected by settings.transcription_provider (see that setting's own comment
in core/config.py):

  "local"  — faster-whisper (CTranslate2, open-source) in this process. The
             DEFAULT, and the only correct answer for a family's self-hosted
             instance: the entire premise there is that a child's voice never
             leaves the LAN. Everything else in this module describes this
             path.
  "openai" — OpenAI's transcription API. Loads no model, and — critically —
             never imports faster_whisper at all, which is the whole reason
             this option exists. ctranslate2 opportunistically imports torch
             the moment torch is present in the environment, and torch costs
             ~480MB of RSS on import alone; a process measured at 642MB
             warmed does not fit Render's 512MB free-tier web service, and
             bede-demo-api was being OOM-killed, taking every in-flight
             voice session down with it (services/streaming_transcription.py
             is in-memory and single-process). See docs/DEMO_HOSTING.md's
             memory section and docs/VOICE_SETUP.md.

The public demo is the deployment this second backend was added for, and the
reasoning is specific to its shape rather than general: it already sends the
whole conversation to OpenAI's chat models and already uses OpenAI for TTS,
so transcribing locally there was paying 480MB for a privacy property that
deployment does not claim. A family's own instance does claim it, so nothing
changes there unless they deliberately set the option.

Everything below describes the local backend.

Model sizes vs speed (single inference on CPU, int8 quantization):
  tiny   ~39M params   – use for short child utterances
  base   ~74M params   – slightly better accuracy
  small  ~244M params  – best accuracy/speed trade-off for 2h session

We default to 'base' — 'tiny' shipped noticeably worse transcripts once real
sentences (not just isolated enrollment phrases) started flowing through the
fallback path, including every walkie-talkie hold-to-talk turn on a browser
without native SpeechRecognition. faster-whisper's CTranslate2 backend runs
these same 'base' weights several times faster than the original
openai-whisper implementation on CPU (int8 quantization, no torch runtime),
so upgrading to 'small' isn't necessary to hit comfortable per-utterance
latency — see docs/VOICE_SETUP.md.

Everything CPU-bound here (model load AND inference) runs in a thread-pool
executor, never on the asyncio event loop. FastAPI serves every request —
including the /tutor/chat SSE stream — from one event loop; a synchronous
Whisper call used to freeze the entire app (every tablet's chat stream, every
login) for the full duration of a model load + transcription.

transcribe_audio() also serializes actual inference through a semaphore sized
by settings.voice_transcription_max_concurrency (default 1) — see that
setting's own comment in core/config.py. Moving work off the event loop
stopped a slow transcription from freezing the *rest* of the app, but did
nothing to stop multiple transcription passes from running concurrently and
fighting each other for CPU: faster-whisper's CTranslate2 backend is itself
internally multi-threaded, so N concurrent calls don't finish in parallel,
they all slow down together. That's what was actually behind reports of a
hold-to-talk turn's "Transcribing…" spinner taking 10s, then 30s, then never
resolving at all within the same short session — every fresh mic press opens
its own streaming-transcription worker (services/streaming_transcription.py),
and a quick press/release/press sequence left more than one of those workers
mid-inference at once with nothing making them wait their turn. The semaphore
turns that pile-up into a queue: a queued pass still adds latency, but it no
longer compounds into runaway multi-tens-of-seconds stalls. See
docs/VOICE_SETUP.md's transcription-delay section for the investigation.

MODEL_DIR is where the model weights live. In the production Docker image
they're pre-downloaded here at build time (see Dockerfile) — the api
container runs read_only:true with no writable volume outside a 64MB /tmp
tmpfs, so a first-use runtime download has nowhere to write and would fail.
In local dev (no container, filesystem writable) this same path just
downloads on first use instead.
"""
import asyncio
import io
import logging
import os
import threading

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

# faster-whisper model size. "base" is a reasonable CPU default for English,
# but it is materially weaker on Spanish — the same audio that transcribes
# cleanly in English comes back garbled often enough to be noticed. "small" is
# the usual step up for non-English at roughly 3x the compute, which is why
# this is a setting rather than a constant: a deployment teaching in Spanish
# can trade CPU for accuracy without a code change, and English-only
# deployments keep exactly today's behaviour.
_WHISPER_MODEL_SIZE = settings.whisper_model_size
MODEL_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "models", "whisper"))

_model = None
_model_load_attempted = False
# A real lock (not lru_cache) so two concurrent first requests can't both
# load the model — the second waits for the first instead of doubling memory.
_model_lock = threading.Lock()

# Bounds how many transcribe_audio() calls actually run inference at once,
# app-wide — see settings.voice_transcription_max_concurrency's own comment
# in core/config.py and this module's docstring for why. Created lazily
# (not at import time) so it always binds to the event loop that ends up
# running it, rather than whichever loop happened to exist at import.
_inference_semaphore: asyncio.Semaphore | None = None


def _get_inference_semaphore() -> asyncio.Semaphore:
    global _inference_semaphore
    if _inference_semaphore is None:
        _inference_semaphore = asyncio.Semaphore(max(1, settings.voice_transcription_max_concurrency))
    return _inference_semaphore


def _get_model():
    """Blocking — only call from a worker thread (or preload())."""
    global _model, _model_load_attempted
    if _model is not None or _model_load_attempted:
        return _model
    with _model_lock:
        if _model is not None or _model_load_attempted:
            return _model
        try:
            from faster_whisper import WhisperModel  # type: ignore

            logger.info("Loading faster-whisper model '%s'…", _WHISPER_MODEL_SIZE)
            _model = WhisperModel(
                _WHISPER_MODEL_SIZE,
                device="cpu",
                compute_type="int8",
                download_root=MODEL_DIR,
            )
            logger.info("faster-whisper model ready")
        except ImportError:
            logger.warning("faster-whisper not installed — fallback STT unavailable")
        except Exception:
            # Any other load failure (corrupted/missing baked weights, a
            # disk issue, ...) should degrade the same way a missing package
            # does, not crash the caller — see transcribe_audio's "not
            # available" response and preload()'s own broad catch in
            # main.py's _warm_voice_models.
            logger.exception("faster-whisper model load failed — fallback STT unavailable")
        finally:
            _model_load_attempted = True
        return _model


def preload() -> None:
    """Best-effort warm-up so the first child to use the mic fallback doesn't
    pay the model-load latency. Blocking — run in an executor (see main.py's
    startup warm-up task).

    A no-op unless the local backend is actually selected. This guard is not
    just tidiness: preload() is the one call that reliably imports
    faster_whisper at startup, and on the "openai" backend that import is
    precisely the ~480MB this module's docstring exists to avoid. main.py
    also checks before calling — both, because either one alone would make
    the saving depend on a single call site staying correct."""
    if not uses_local_model():
        return
    _get_model()


def uses_local_model() -> bool:
    """Whether speech-to-text runs in this process. Callers use this to
    decide whether loading/warming a local model is worth doing at all —
    see main.py's _warm_voice_models."""
    return settings.transcription_provider == "local"


def partial_passes_are_affordable() -> bool:
    """Whether it is worth transcribing a hold BEFORE the child lets go, just
    to show them a live preview of what was heard.

    Locally: yes. The pass costs CPU cycles on a machine we already own and
    are not otherwise using mid-hold, so a discarded partial is close to
    free — services/streaming_transcription.py caps them by duration rather
    than forbidding them.

    Against a metered API: no. Every pass re-transcribes the WHOLE growing
    buffer (nothing here has an incremental mode), so a 20-second answer at
    the client's 4s chunk cadence becomes roughly five billed requests, each
    re-uploading everything captured so far — and four of the five are
    thrown away the moment the final pass lands. That is several times the
    cost and the egress of the one pass that actually reaches Bede, spent on
    a preview. The child still sees "Transcribing…" and then their words;
    what they lose is only the live word-by-word settle, which is exactly
    what already happens today on any hold shorter than one chunk interval.
    """
    return uses_local_model()


def _transcribe_sync(audio_bytes: bytes, language: str) -> dict:
    """Blocking load + inference — run in an executor, never on the event loop."""
    model = _get_model()
    if model is None:
        return {"text": "", "error": "Whisper not available", "language": language}

    import numpy as np
    import soundfile as sf

    # faster-whisper accepts a numpy array directly (16kHz mono float32) —
    # no need to round-trip through a temp WAV file the way openai-whisper's
    # own path-based loader required.
    buf = io.BytesIO(audio_bytes)
    try:
        data, sr = sf.read(buf, dtype="float32", always_2d=False)
    except Exception as e:
        return {"text": "", "error": f"Audio read failed: {e}", "language": language}

    if data.ndim > 1:
        data = data.mean(axis=1)

    # Resample to 16kHz if needed
    if sr != 16000:
        try:
            from scipy.signal import resample_poly
            from math import gcd
            g = gcd(16000, sr)
            data = resample_poly(data, 16000 // g, sr // g).astype(np.float32)
        except Exception:
            pass

    try:
        # beam_size: faster-whisper defaults to 5 (beam search). Greedy
        # decoding is several times faster and, for short single-language
        # child utterances where the language is already known, gives up very
        # little. This is the biggest pure-speed lever here and costs no
        # audio, unlike VAD below.
        #
        # vad_filter: skips silence rather than decoding it, which is a real
        # saving on a press-and-hold recording full of pauses. Defaults OFF
        # because the risk is asymmetric — a child who answers quietly can be
        # clipped by VAD, and losing a word is far worse than waiting for it.
        # Enable per deployment once you have heard it work on your own
        # hardware with your own children.
        segments, info = model.transcribe(
            data,
            language=language,
            condition_on_previous_text=False,
            beam_size=settings.whisper_beam_size,
            vad_filter=settings.whisper_vad_filter,
        )
        text = "".join(segment.text for segment in segments).strip()
        return {
            "text": text,
            "language": info.language or language,
        }
    except Exception as e:
        return {"text": "", "error": str(e), "language": language}


# ── OpenAI transcription backend ─────────────────────────────────────────────
# Same shape as services/voice_synthesis.py's OpenAI TTS call, deliberately:
# one pooled client rather than a fresh handshake per utterance, a short
# timeout, and one retry for transient failures only. The failure cost here is
# higher than TTS's, though — a failed TTS call costs one line of spoken
# narration, a failed transcription costs the child's entire answer, which
# they then have to say again.
_OPENAI_TRANSCRIPTION_URL = "https://api.openai.com/v1/audio/transcriptions"
# A child's utterance is seconds long, so a request that hasn't come back in
# 30s is not going to be useful even if it eventually arrives — the child is
# already looking at a stuck "Transcribing…".
_OPENAI_REQUEST_TIMEOUT_SECONDS = 30.0
_OPENAI_MAX_ATTEMPTS = 2
_OPENAI_RETRY_BACKOFF_SECONDS = (0.5,)
# 429 and 5xx can succeed on a second try; 4xx (bad key, malformed audio)
# cannot, so retrying them only makes the child wait longer to be told.
_OPENAI_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

_openai_http_client: httpx.AsyncClient | None = None


def _get_openai_http_client() -> httpx.AsyncClient:
    global _openai_http_client
    if _openai_http_client is None:
        _openai_http_client = httpx.AsyncClient(
            timeout=_OPENAI_REQUEST_TIMEOUT_SECONDS,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _openai_http_client


async def aclose_http_client() -> None:
    """Called from main.py's lifespan shutdown, alongside voice_synthesis's
    own — closes the pooled connections cleanly instead of leaving them for
    the OS to reclaim. Safe to call when the local backend is in use and no
    client was ever created."""
    global _openai_http_client
    if _openai_http_client is not None:
        await _openai_http_client.aclose()
        _openai_http_client = None


async def _transcribe_openai(audio_bytes: bytes, language: str) -> dict:
    """Returns the same {text, language} shape the local backend does, with
    an added "error" key on failure — callers (routers/voice.py's
    /transcribe, services/streaming_transcription.py's worker) already treat
    an empty text as "nothing was heard" and must not need to know which
    backend produced it."""
    if not settings.openai_api_key:
        # core/config.py's reject_unusable_transcription_provider makes this
        # unreachable through normal startup; kept so a directly-constructed
        # Settings in a test or script degrades rather than raising here.
        return {"text": "", "error": "OpenAI transcription not configured", "language": language}

    client = _get_openai_http_client()
    for attempt in range(_OPENAI_MAX_ATTEMPTS):
        try:
            resp = await client.post(
                _OPENAI_TRANSCRIPTION_URL,
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                # The frontend records 16kHz mono WAV (see the demo's and
                # homeschool-tutor's useVoiceRecorder.ts), and the streaming
                # worker assembles the same — so the filename is just the
                # container hint the multipart API wants, not a real file.
                files={"file": ("speech.wav", audio_bytes, "audio/wav")},
                data={
                    "model": settings.openai_transcription_model,
                    # Same hint the local backend passes to faster-whisper: a
                    # Spanish session transcribed as English comes back
                    # garbled regardless of which engine did it.
                    "language": language,
                },
            )
            resp.raise_for_status()
            body = resp.json()
            return {"text": (body.get("text") or "").strip(), "language": language}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _OPENAI_RETRYABLE_STATUS_CODES:
                logger.warning(
                    "OpenAI transcription failed with a non-retryable status: %s",
                    exc.response.status_code,
                )
                return {"text": "", "error": f"Transcription failed ({exc.response.status_code})", "language": language}
            logger.warning(
                "OpenAI transcription failed with status %s (attempt %d/%d)",
                exc.response.status_code, attempt + 1, _OPENAI_MAX_ATTEMPTS,
            )
        except Exception:
            logger.warning(
                "OpenAI transcription request failed (attempt %d/%d)",
                attempt + 1, _OPENAI_MAX_ATTEMPTS, exc_info=True,
            )
        if attempt < _OPENAI_MAX_ATTEMPTS - 1:
            await asyncio.sleep(_OPENAI_RETRY_BACKOFF_SECONDS[attempt])
    logger.error("OpenAI transcription failed after %d attempts", _OPENAI_MAX_ATTEMPTS)
    return {"text": "", "error": "Transcription unavailable", "language": language}


async def transcribe_audio(audio_bytes: bytes, language: str = "en") -> dict:
    """
    Transcribe audio bytes to text using whichever backend this deployment
    selected (settings.transcription_provider — see the module docstring).
    Returns {text, language}, plus "error" when something went wrong.
    """
    if not uses_local_model():
        # No semaphore and no executor: the concurrency limit below exists
        # because faster-whisper's CTranslate2 backend is internally
        # multi-threaded and concurrent local passes thrash the same cores.
        # An HTTP request has neither problem — serializing these would just
        # make two children wait for each other for no reason. The pooled
        # client's own max_connections is the cap that does apply.
        return await _transcribe_openai(audio_bytes, language)
    loop = asyncio.get_running_loop()
    async with _get_inference_semaphore():
        return await loop.run_in_executor(None, _transcribe_sync, audio_bytes, language)
