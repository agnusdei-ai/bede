"""
Server-side speech-to-text using OpenAI Whisper (open-source, runs locally).
Used as a fallback when the browser's Web Speech API is unavailable (Firefox,
offline, or low-confidence interim results).

Model sizes vs speed (single inference on CPU):
  tiny   ~39M params   ~0.5s  – use for short child utterances
  base   ~74M params   ~1s    – slightly better accuracy
  small  ~244M params  ~3s    – best accuracy/speed trade-off for 2h session

We default to 'base' — 'tiny' shipped noticeably worse transcripts once real
sentences (not just isolated enrollment phrases) started flowing through the
fallback path, including every walkie-talkie hold-to-talk turn on a browser
without native SpeechRecognition. 'base' roughly doubles inference time
(~1s vs ~0.5s per utterance on CPU) but is still comfortably fast enough for
a single child utterance, and its accuracy jump is worth that trade for a
feature children actually rely on to be understood correctly.

Everything CPU-bound here (model load AND inference) runs in a thread-pool
executor, never on the asyncio event loop. FastAPI serves every request —
including the /tutor/chat SSE stream — from one event loop; a synchronous
Whisper call used to freeze the entire app (every tablet's chat stream, every
login) for the full duration of a model load + transcription.
"""
import asyncio
import io
import logging
import threading

logger = logging.getLogger(__name__)

_WHISPER_MODEL_SIZE = "base"

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
            import whisper  # type: ignore

            logger.info("Loading Whisper model '%s'…", _WHISPER_MODEL_SIZE)
            _model = whisper.load_model(_WHISPER_MODEL_SIZE)
            logger.info("Whisper model ready")
        except ImportError:
            logger.warning("openai-whisper not installed — fallback STT unavailable")
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
    import tempfile, os

    # Whisper expects a file path or numpy array at 16kHz mono float32
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

    # Write to temp WAV so Whisper can read it
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, data, 16000)
        tmp_path = tmp.name

    try:
        result = model.transcribe(
            tmp_path,
            language=language,
            fp16=False,          # safe on CPU
            condition_on_previous_text=False,
        )
        return {
            "text": result.get("text", "").strip(),
            "language": result.get("language", language),
        }
    except Exception as e:
        return {"text": "", "error": str(e), "language": language}
    finally:
        os.unlink(tmp_path)


async def transcribe_audio(audio_bytes: bytes, language: str = "en") -> dict:
    """
    Transcribe audio bytes to text using Whisper.
    Returns {text, language, segments}.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _transcribe_sync, audio_bytes, language)
