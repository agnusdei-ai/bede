"""
Server-side speech-to-text using faster-whisper (CTranslate2, open-source,
runs locally). Used as a fallback when the browser's Web Speech API is
unavailable (Firefox, offline, or low-confidence interim results).

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
    startup warm-up task)."""
    _get_model()


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


async def transcribe_audio(audio_bytes: bytes, language: str = "en") -> dict:
    """
    Transcribe audio bytes to text using faster-whisper.
    Returns {text, language, segments}.
    """
    loop = asyncio.get_running_loop()
    async with _get_inference_semaphore():
        return await loop.run_in_executor(None, _transcribe_sync, audio_bytes, language)
