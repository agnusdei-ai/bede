# SPDX-License-Identifier: GPL-3.0-or-later
"""
Bede's local voice: a small HTTP server that speaks a line with Piper.

This program uses Piper (GPL-3.0-or-later) and is distributed under the same
license, as its own program in its own container (`voice-service/`). Bede's
API talks to it only over HTTP and links none of its code. See
voice-service/README.md and docs/DECISIONS.md entry 46, whose distribution
review must clear before this ships to families.

It deliberately does NOT use Piper's bundled `piper.http_server`, which keeps
the most recent sentence it spoke in memory and serves it back at /info, and
which has a /download route that fetches voices from the internet. Here:

- POST /synthesize {"text": ..., "locale": "en"|"es"} -> audio/wav.
- GET /health -> {"voices": [locales that have a voice]}.
- Nothing else. No text is logged or kept once the response is sent: the
  request body, the text and the audio are local to one request and released
  when it returns. (Python cannot scrub freed memory; nothing here holds a
  reference to it.)
- Voices are read from fixed paths given at start-up (BEDE_VOICE_EN,
  BEDE_VOICE_ES) and never downloaded.
"""
from __future__ import annotations

import io
import json
import logging
import os
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, Optional

log = logging.getLogger("bede.voice")

MAX_TEXT_CHARS = 2000          # the API's own SpeakRequest limit
MAX_BODY_BYTES = 16 * 1024     # comfortably above 2000 characters of JSON
LOCALES = ("en", "es")

# A synthesizer takes text and returns WAV bytes. The real one wraps a
# PiperVoice; tests pass a fake, so this module never needs Piper to be tested.
Synthesizer = Callable[[str], bytes]


def piper_synthesizer(model_path: str) -> Synthesizer:
    from piper import PiperVoice  # imported here so tests need no Piper

    quiet_piper()
    voice = PiperVoice.load(model_path)
    lock = threading.Lock()  # one synthesis at a time per voice

    def speak(text: str) -> bytes:
        with lock, io.BytesIO() as out:
            with wave.open(out, "wb") as wav:
                voice.synthesize_wav(text, wav)
            return out.getvalue()

    return speak


def load_voices(env: Dict[str, str], factory: Callable[[str], Synthesizer] = piper_synthesizer) -> Dict[str, Synthesizer]:
    voices: Dict[str, Synthesizer] = {}
    for locale in LOCALES:
        path = env.get(f"BEDE_VOICE_{locale.upper()}", "").strip()
        if path:
            voices[locale] = factory(path)
    return voices


def quiet_piper() -> None:
    """Piper logs pieces of the text it is speaking, such as
    "Missing phoneme from id map: <phoneme>" at WARNING. Only its errors are
    kept, which carry no text."""
    logging.getLogger("piper").setLevel(logging.ERROR)


def make_handler(voices: Dict[str, Synthesizer]) -> type:
    class Handler(BaseHTTPRequestHandler):
        server_version = "bede-voice"
        sys_version = ""

        def log_message(self, fmt: str, *args) -> None:  # never the body
            log.info("%s %s", self.command, self.path.split("?", 1)[0])

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, reason: str) -> None:
            self._send(status, json.dumps({"error": reason}).encode(), "application/json")

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send(200, json.dumps({"voices": sorted(voices)}).encode(), "application/json")
            else:
                self._error(404, "not_found")

        def do_POST(self) -> None:
            if self.path != "/synthesize":
                self._error(404, "not_found")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if length <= 0 or length > MAX_BODY_BYTES:
                self._error(413 if length > MAX_BODY_BYTES else 400, "bad_length")
                return
            try:
                data = json.loads(self.rfile.read(length))
                text = data.get("text") if isinstance(data, dict) else None
                locale = data.get("locale", "en") if isinstance(data, dict) else None
            except (ValueError, UnicodeDecodeError):
                self._error(400, "bad_json")
                return
            if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
                self._error(400, "bad_text")
                return
            if not isinstance(locale, str):
                self._error(400, "bad_locale")
                return
            speak = voices.get(locale.split("-", 1)[0].lower())
            if speak is None:
                # No voice for this language: silence, never another language's voice.
                self._error(404, "no_voice_for_locale")
                return
            try:
                audio = speak(text.strip())
            except Exception as exc:  # noqa: BLE001 - report the type, never the text
                log.error("synthesis failed: %s", type(exc).__name__)
                self._error(500, "synthesis_failed")
                return
            self._send(200, audio, "audio/wav")

    return Handler


def serve(host: str, port: int, voices: Dict[str, Synthesizer]) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(voices))


def main(env: Optional[Dict[str, str]] = None) -> None:
    env = dict(os.environ if env is None else env)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    quiet_piper()
    voices = load_voices(env)
    if not voices:
        raise SystemExit("No voice configured: set BEDE_VOICE_EN and/or BEDE_VOICE_ES to a Piper .onnx file")
    host = env.get("BEDE_VOICE_HOST", "0.0.0.0")
    port = int(env.get("BEDE_VOICE_PORT", "5000"))
    log.info("Bede's voice listening on %s:%d with voices %s", host, port, ", ".join(sorted(voices)))
    serve(host, port, voices).serve_forever()


if __name__ == "__main__":
    main()
