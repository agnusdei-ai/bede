# Optional Piper development voice

**Optional, for development and testing only.** Bede's reference voice is OpenAI's, the voice the demo uses (owner direction 2026-11-20, `docs/DECISIONS.md` entry 46). This server is never the default voice, never a fallback for a failed cloud line and not a launch dependency; it speaks only when `TTS_PROVIDER=local` asks for it. Sample-voice checks here verify integration mechanics, not how the real alan voice sounds, and are not approval of it.

A small HTTP server that speaks Bede's lines with [Piper](https://github.com/OHF-Voice/piper1-gpl),
on the family's own computer. Nothing it is asked to say leaves that computer.

**License.** Piper is GPL-3.0-or-later, and so is this directory (`COPYING`).
It is a separate program in its own container. Bede's API, which is under the
repository's own license, talks to it only over HTTP and includes none of its
code. How that applies to the way Bede is distributed is recorded in
`docs/DECISIONS.md` entry 46.

**Bede's voice.** `bede-voice.json` names it: `en_GB-alan-medium`, English and
male, chosen by the owner for Bede's monk persona. Each Piper voice is a
separate model with its own license, separate from Piper's GPL. No voice file
is in this repository: `fetch_voice.py` downloads it while the image is built
and keeps it only if every pinned SHA-256 matches, otherwise none (Bede is
then text-first). Before the hashes are pinned, its license, training lineage
and redistribution terms are read from its own model card and recorded in
`bede-voice.json` (`scripts/voice/pin_bede_voice.py`).

## What it does

- `POST /synthesize` with `{"text": "...", "locale": "en"}` returns `audio/wav`.
  Text is limited to 2000 characters, as in the API.
- `GET /health` returns `{"voices": ["en", "es"]}` for the languages it has.
- Spanish is read in the English voice unless a Spanish one is given (owner
  ruling 2026-11-19). A language with no voice at all gets
  `404 no_voice_for_locale`.
- With no voice at all it still runs and reports none, so Bede is text-first
  rather than a container that restarts forever.

## What it does not do

It does **not** use Piper's bundled `piper.http_server`, which keeps the last
sentence it spoke in memory and shows it at `/info`, and can download voices
from the internet at `/download`. This server:

- logs only the method and path, never the text;
- keeps nothing once a response is sent;
- reads voices only from the image or the paths it was started with, and
  downloads nothing at run time.

## Running it

In `docker-compose.yml` it is the `voice` service, which does not run unless the `piper` profile is started (`COMPOSE_PROFILES=piper`), on
a network with no internet access. The API reaches it at
`LOCAL_TTS_URL=http://voice:5000`, and only with `TTS_PROVIDER=local`.

| Variable | Meaning |
| --- | --- |
| `BEDE_VOICE_EN` | Path to an English Piper `.onnx` (its `.onnx.json` beside it); empty means the built-in voice |
| `BEDE_VOICE_ES` | Path to a Spanish Piper `.onnx`; empty means the English voice reads Spanish |
| `BEDE_VOICE_HOST`, `BEDE_VOICE_PORT` | Where to listen (default `0.0.0.0:5000`) |

`requirements.lock.txt` is hash-locked. After editing `requirements.in`, run
`pip-compile --generate-hashes --strip-extras --output-file=requirements.lock.txt requirements.in`.

Tests: `homeschool-api/tests/test_local_voice.py` drives this server over real
HTTP with a stand-in synthesizer, so it needs no voice model.

**End to end, with real Piper and no download.**
`scripts/qualification/local_voice/run_local_voice_check.py` builds sample
voices from code (`make_sample_voice.py`: a real ONNX model with Piper's
interface that emits a tone, and one that loads then fails every line), then
runs the real API, this server with real Piper, and a Sound Time round in real
Chromium for three cases: Piper works, Piper fails, no voice. Every outbound
connection is refused and recorded, so a pass also shows nothing left the
machine and no paid call was made. Needs a Python with
`requirements.lock.txt` plus `onnx` for `--voice-python`, the API's own
requirements for the script itself, and `npm run build` in `homeschool-tutor`.
