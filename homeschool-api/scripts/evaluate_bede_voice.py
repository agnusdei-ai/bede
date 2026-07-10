#!/usr/bin/env python3
"""
One-time voice-selection tool for Bede's spoken voice.

Synthesizes the same short, in-character line with a shortlist of candidate
Kokoro voices, saves each as a WAV file, and ranks them by estimated pitch
(lower = reads as older/deeper, which is what we want for a monk's voice) as
a first-pass filter — NOT a substitute for actually listening. Run this once
after placing the Kokoro model files, listen to the output WAVs yourself,
and set KOKORO_VOICE in .env to whichever one actually sounds right.

Usage:
    cd homeschool-api
    python scripts/evaluate_bede_voice.py

Requires KOKORO_MODEL_DIR (see core/config.py) to contain kokoro-v1.0.onnx
and voices-v1.0.bin — download both from
https://github.com/thewh1teagle/kokoro-onnx/releases before running this.

NOTE: this script has not been executed against real model weights in
development — the sandboxed environment it was written in has no GPU and
cannot reach either huggingface.co or github.com's release-asset CDN, so
there was no way to fetch the model files and validate this end-to-end.
Treat the exact kokoro_onnx API calls below as "written against the
documented interface, not yet run" and adjust if the installed version's
signature differs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import settings  # noqa: E402

SAMPLE_LINE = (
    "Ah, welcome back. Tell me — what did you discover in your reading today?"
)

# Kokoro-82M's English male voices as of this writing (see
# huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md for the current,
# authoritative list — verify these ids still exist before relying on them).
CANDIDATE_VOICES = [
    "bm_george",   # British male — the current default guess for Bede
    "bm_lewis",    # British male
    "am_adam",     # American male
    "am_michael",  # American male
]

OUTPUT_DIR = Path(__file__).resolve().parent / "voice_samples"


def estimate_mean_pitch_hz(samples, sample_rate: int) -> float | None:
    """Rough fundamental-frequency estimate via librosa's pYIN — a cheap
    pre-filter only. Lower = reads as deeper/older. Returns None if librosa
    can't find enough voiced frames to estimate from."""
    import librosa
    import numpy as np

    f0, voiced_flag, _ = librosa.pyin(
        samples, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C6"), sr=sample_rate
    )
    voiced = f0[voiced_flag]
    if voiced.size == 0:
        return None
    return float(np.mean(voiced))


def main():
    from kokoro_onnx import Kokoro
    import soundfile as sf

    model_dir = Path(settings.kokoro_model_dir)
    model_path = model_dir / "kokoro-v1.0.onnx"
    voices_path = model_dir / "voices-v1.0.bin"

    if not model_path.exists() or not voices_path.exists():
        print(f"Model files not found in {model_dir}.")
        print("Download kokoro-v1.0.onnx and voices-v1.0.bin from:")
        print("  https://github.com/thewh1teagle/kokoro-onnx/releases")
        print(f"and place them in {model_dir}, then re-run this script.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(exist_ok=True)
    kokoro = Kokoro(str(model_path), str(voices_path))

    results = []
    for voice in CANDIDATE_VOICES:
        print(f"Synthesizing with voice={voice!r}...")
        # Match phonemization to each candidate's actual accent — en-gb for
        # British voices, en-us for American ones — same rule production uses
        # in voice_synthesis.py. Comparing George/Lewis under en-us (as this
        # script originally did) understates how they actually sound live.
        lang = "en-gb" if voice.startswith(("bm_", "bf_")) else "en-us"
        try:
            samples, sample_rate = kokoro.create(SAMPLE_LINE, voice=voice, speed=0.92, lang=lang)
        except Exception as exc:
            print(f"  FAILED: {exc}")
            continue

        out_path = OUTPUT_DIR / f"{voice}.wav"
        sf.write(str(out_path), samples, sample_rate, format="WAV")

        pitch = estimate_mean_pitch_hz(samples, sample_rate)
        results.append((voice, out_path, pitch))
        pitch_note = f"{pitch:.0f} Hz" if pitch else "unknown"
        print(f"  saved {out_path} (estimated mean pitch: {pitch_note})")

    if not results:
        print("\nNo candidates synthesized successfully.")
        sys.exit(1)

    results.sort(key=lambda r: (r[2] is None, r[2] if r[2] is not None else 0))

    print("\n" + "=" * 60)
    print("Ranked by estimated pitch (lower first — a rough proxy for")
    print("'deeper/older-sounding', NOT a substitute for listening):")
    print("=" * 60)
    for voice, path, pitch in results:
        pitch_note = f"{pitch:.0f} Hz" if pitch else "unknown"
        print(f"  {voice:12s}  {pitch_note:>10s}   {path}")

    print(f"\nListen to the files in {OUTPUT_DIR}, then set in .env:")
    print(f"  KOKORO_VOICE={results[0][0]}   # or whichever one actually sounds right")


if __name__ == "__main__":
    main()
