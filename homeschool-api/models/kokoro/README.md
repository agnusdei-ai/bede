Place `kokoro-v1.0.onnx` and `voices-v1.0.bin` here if you want the
self-hosted Kokoro fallback (see `core/config.py`'s `kokoro_*` settings and
`services/voice_synthesis.py`) — not part of the documented setup path
(`docs/VOICE_SETUP.md` covers OpenAI TTS only), just an internal
zero-cloud-dependency option for anyone building from source.

This directory is intentionally empty in git (the model files are large
binaries and are gitignored). Nothing breaks if you leave it empty — Bede
just falls back to the browser's own built-in voice.
