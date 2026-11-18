# Bede's local voice

A small HTTP server that speaks Bede's lines with [Piper](https://github.com/OHF-Voice/piper1-gpl),
on the family's own computer. Nothing it is asked to say leaves that computer.

**Licence.** Piper is GPL-3.0-or-later, and so is this directory (`COPYING`).
It is a separate program in its own container. Bede's API, which is under the
repository's own licence, talks to it only over HTTP and includes none of its
code. Whether that separation is enough for how Bede is distributed is the
distribution review recorded in `docs/DECISIONS.md` entry 46, and **this voice
is not installed for families until that review clears.**

**Voices.** Each Piper voice is a separate model with its own licence, separate
from Piper's. No voice file is in this repository. Which English and Spanish
voices Bede uses is part of the same review, and is chosen only from voices
whose licence has been read and recorded.

## What it does

- `POST /synthesize` with `{"text": "...", "locale": "en"}` returns `audio/wav`.
  Text is limited to 2000 characters, as in the API.
- `GET /health` returns `{"voices": ["en", "es"]}` for the languages it has.
- A language with no voice gets `404 no_voice_for_locale`. It is never spoken
  in another language's voice.

## What it does not do

It does **not** use Piper's bundled `piper.http_server`, which keeps the last
sentence it spoke in memory and shows it at `/info`, and can download voices
from the internet at `/download`. This server:

- logs only the method and path, never the text;
- keeps nothing once a response is sent;
- reads voices only from the paths it was started with, and downloads nothing.

## Running it

In `docker-compose.yml` it is the `voice` service, under the `local-voice`
profile, on a network with no internet access. The API reaches it at
`LOCAL_TTS_URL=http://voice:5000`.

| Variable | Meaning |
| --- | --- |
| `BEDE_VOICE_EN` | Path to the English Piper `.onnx` (its `.onnx.json` beside it) |
| `BEDE_VOICE_ES` | Path to the Spanish Piper `.onnx` |
| `BEDE_VOICE_HOST`, `BEDE_VOICE_PORT` | Where to listen (default `0.0.0.0:5000`) |

`requirements.lock.txt` is hash-locked. After editing `requirements.in`, run
`pip-compile --generate-hashes --strip-extras --output-file=requirements.lock.txt requirements.in`.

Tests: `homeschool-api/tests/test_local_voice.py` drives this server over real
HTTP with a stand-in synthesizer, so it needs no voice model.
