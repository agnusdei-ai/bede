"""
Server-side speech-to-text using OpenAI Whisper (open-source, runs locally).
Used as a fallback when the browser's Web Speech API is unavailable (Firefox,
offline, or low-confidence interim results).

Model sizes vs speed (single inference on CPU):
  tiny   ~39M params   ~0.5s  – use for short child utterances
  base   ~74M params   ~1s    – slightly better accuracy
  small  ~244M params  ~3s    – best accuracy/speed trade-off for 2h session

We default to 'tiny' so the first download is fast and CPU usage stays low.
"""
import io
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

_WHISPER_MODEL_SIZE = "tiny"


@lru_cache(maxsize=1)
def _get_model():
    try:
        import whisper  # type: ignore

        logger.info("Loading Whisper model '%s'…", _WHISPER_MODEL_SIZE)
        model = whisper.load_model(_WHISPER_MODEL_SIZE)
        logger.info("Whisper model ready")
        return model
    except ImportError:
        logger.warning("openai-whisper not installed — fallback STT unavailable")
        return None


async def transcribe_audio(audio_bytes: bytes, language: str = "en") -> dict:
    """
    Transcribe audio bytes to text using Whisper.
    Returns {text, language, segments}.
    """
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
