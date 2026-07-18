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

logger = logging.getLogger(__name__)

_WHISPER_MODEL_SIZE = "base"
MODEL_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "models", "whisper"))

_model = None
_model_load_attempted = False
# A real lock (not lru_cache) so two concurrent first requests can't both
# load the model — the second waits for the first instead of doubling memory.
_model_lock = threading.Lock()


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
        segments, info = model.transcribe(
            data,
            language=language,
            condition_on_previous_text=False,
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
    return await loop.run_in_executor(None, _transcribe_sync, audio_bytes, language)
