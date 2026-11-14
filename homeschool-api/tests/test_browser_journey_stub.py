"""The browser journeys' model stub must answer the real picture check
(scripts/qualification/browser_journeys/model_stub.py).

The check (services/content_screen.py) sends images, as a worksheet reading
does. The stub once answered it with the reading, which the real parser
correctly refuses as unclear, so every journey's upload failed closed and the
run timed out. This runs the stub as a real server and parses its reply with
the real parser.
"""
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from services import content_screen

STUB = Path(__file__).resolve().parents[2] / "scripts" / "qualification" / "browser_journeys" / "model_stub.py"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _ask(port, system):
    body = {"model": "sample-stub", "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
                                      {"type": "text", "text": "Check these pictures."}]}]}
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as res:
        return json.loads(res.read())["choices"][0]["message"]["content"]


def test_the_stub_answers_the_real_picture_check_with_a_parseable_verdict(tmp_path):
    port = _free_port()
    proc = subprocess.Popen([sys.executable, str(STUB), str(port), str(tmp_path)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        for context in ("worksheet", "lesson"):
            reply = _ask(port, content_screen._rules(context))
            assert content_screen.parse_verdict(reply) is None, reply
        # A reading prompt with images still gets the worksheet reading.
        assert "sections" in json.loads(_ask(port, "Subject: history. Read the pages."))
    finally:
        proc.terminate()
        proc.wait(timeout=5)
