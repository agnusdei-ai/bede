#!/usr/bin/env python3
"""
One-time, maintainer-run script that generates the setup wizard's spoken
narration clips using Bede's actual configured voice (OpenAI TTS,
gpt-4o-mini-tts, voice=fable — see docs/VOICE_SETUP.md) and writes them into
scripts/setup_wizard/audio/ as committed static assets.

This is NOT run by end users and NOT run inside the wizard's Docker image —
the wizard container stays pure-stdlib on purpose (see wizard.py's module
docstring). Run this once on a machine with network access and an
OPENAI_API_KEY, commit the resulting .wav files, and the wizard plays them
back with zero API calls or network access at install time. If a family
never runs this and the audio/ directory is empty, the wizard simply skips
playback — narration is a bonus, not a requirement.

Usage:
    OPENAI_API_KEY=sk-... python3 scripts/setup_wizard/generate_narration.py
"""
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

AUDIO_DIR = Path(__file__).resolve().parent / "audio"

# Same persona instructions as the live app (docs/VOICE_SETUP.md) so the
# install experience sounds like the same Bede the family will actually
# talk to, not a generic narrator.
_TTS_MODEL = "gpt-4o-mini-tts"
_TTS_VOICE = "fable"
_TTS_INSTRUCTIONS = "Speak as an elderly, warm, unhurried Southern English monk."
_TTS_URL = "https://api.openai.com/v1/audio/speech"

# Keep this list short and purposeful — one line to greet, one to close.
# Narrating every field turns a quick form into a chore; these two bookend
# the experience without slowing anyone down.
LINES = {
    "welcome": (
        "Pax vobiscum. I'm Bede. Let's get you set up together — just a few "
        "questions, and I'll take care of everything else."
    ),
    "success": (
        "Well done. Everything's saved safely. Give me a couple of minutes "
        "to wake up, and I'll be ready for your student."
    ),
}


def synthesize(text: str, api_key: str) -> bytes:
    payload = {
        "model": _TTS_MODEL,
        "voice": _TTS_VOICE,
        "input": text,
        "instructions": _TTS_INSTRUCTIONS,
        "response_format": "wav",
    }
    import json

    req = urllib.request.Request(
        _TTS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def main() -> int:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        print(
            "Set OPENAI_API_KEY first, e.g.:\n"
            "  OPENAI_API_KEY=sk-... python3 scripts/setup_wizard/generate_narration.py",
            file=sys.stderr,
        )
        return 1

    AUDIO_DIR.mkdir(exist_ok=True)
    for name, text in LINES.items():
        out_path = AUDIO_DIR / f"{name}.wav"
        print(f"Generating {out_path.name}...")
        try:
            audio = synthesize(text, api_key)
        except urllib.error.HTTPError as e:
            print(f"  Failed ({e.code}): {e.read().decode(errors='replace')}", file=sys.stderr)
            return 1
        except urllib.error.URLError as e:
            print(f"  Failed: {e.reason}", file=sys.stderr)
            return 1
        out_path.write_bytes(audio)
        print(f"  Wrote {out_path} ({len(audio)} bytes)")

    print("\nDone. Commit the .wav files in scripts/setup_wizard/audio/ to ship narration.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
