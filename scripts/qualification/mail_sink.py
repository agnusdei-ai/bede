#!/usr/bin/env python3
"""Loopback mail sink — the SECOND and last stubbed dependency.

The real ``POST /auth/educator-passkey/invite`` route delivers a one-time
enrollment ticket only by email. With RESEND_API_BASE_URL pointed here
(core/config.py accepts only a loopback URL, and nothing in production), the
application's own ``send_email`` makes its ordinary Resend-shaped request to
this process instead of api.resend.com. The harness then reads the ticket
from the captured message and runs the real register and login ceremony.

  POST /emails   Resend's request shape. Requires ``Authorization: Bearer``
                 equal to the run's synthetic key (QUAL_MAIL_SINK_KEY) and a
                 recipient in the synthetic institution domain; anything
                 else is refused with 4xx, exactly as a real provider would
                 refuse it, so a misdirected send fails visibly.

Raw messages are written ONLY under --store (the run's temp directory, never
the evidence directory), because they contain live enrollment tickets. A
redacted line per message (recipient domain, subject, body SHA-256, never the
body) goes to --log, which IS evidence. package.py covers both: it scans the
store with the credential patterns and refuses any evidence file containing
a ticket token captured here.

    python scripts/qualification/mail_sink.py --port 8767 --store DIR --log FILE
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOOPBACK = ("127.0.0.1", "localhost", "::1")


class Sink(BaseHTTPRequestHandler):
    store: Path
    log_path: Path
    key: str
    domain: str
    lock = threading.Lock()
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _reply(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802 — readiness probe only; exposes nothing
        self._reply(200 if self.path == "/health" else 404, {"ok": self.path == "/health"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        if self.path.rstrip("/") != "/emails":
            self._reply(404, {"error": "not found"})
            return
        auth = self.headers.get("Authorization", "")
        if not hmac.compare_digest(auth, f"Bearer {self.key}"):
            self._reply(401, {"error": "bad key"})
            return
        try:
            msg = json.loads(raw)
            to = msg["to"]
            if not (isinstance(to, list) and len(to) == 1 and isinstance(to[0], str)):
                raise ValueError("one recipient")
        except (ValueError, KeyError, TypeError):
            self._reply(422, {"error": "malformed"})
            return
        if not to[0].lower().endswith("@" + self.domain):
            self._reply(422, {"error": "recipient outside the synthetic domain"})
            return
        ident = str(uuid.uuid4())
        with self.lock:
            (self.store / f"{time.time():.6f}-{ident}.json").write_text(json.dumps(msg))
            with self.log_path.open("a") as fh:
                fh.write(json.dumps({
                    "t": time.time(), "id": ident,
                    "recipient_domain": to[0].split("@", 1)[1],
                    "subject": msg.get("subject", ""),
                    "body_sha256": hashlib.sha256(msg.get("html", "").encode()).hexdigest(),
                }) + "\n")
        self._reply(200, {"id": ident})


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8767)
    p.add_argument("--store", required=True)
    p.add_argument("--log", required=True)
    p.add_argument("--domain", required=True)
    a = p.parse_args()
    if a.host not in LOOPBACK:
        print("mail_sink: refusing to bind anything but loopback", file=sys.stderr)
        return 2
    key = os.environ.get("QUAL_MAIL_SINK_KEY", "")
    if not key.startswith("synthetic-"):
        print("mail_sink: QUAL_MAIL_SINK_KEY must be a synthetic- key", file=sys.stderr)
        return 2
    store = Path(a.store)
    store.mkdir(parents=True, exist_ok=True)
    os.chmod(store, 0o700)
    Sink.store, Sink.log_path, Sink.key, Sink.domain = store, Path(a.log), key, a.domain.lower()
    server = ThreadingHTTPServer((a.host, a.port), Sink)
    print(f"mail_sink listening on http://{a.host}:{a.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def captured(store: Path) -> list[dict]:
    """Every captured message, oldest first (harness and package.py use this)."""
    if not store.exists():
        return []
    return [json.loads(p.read_text()) for p in sorted(store.glob("*.json"))]


if __name__ == "__main__":
    sys.exit(main())
