#!/usr/bin/env python3
"""Local OpenAI-compatible model stub — the ONLY stubbed dependency.

Everything else in a qualification run is the real application: real
uvicorn, real lifespan, real Postgres, real routes. The model vendor is the
one thing replaced, because a synthetic run must never reach a commercial
API and must be deterministic.

Speaks just enough of /v1 for services/adapters/openai_compatible_adapter.py:
  GET  /v1/models            — the health check the lifespan task pings
  POST /v1/chat/completions  — streamed (SSE) or not; returns fixed synthetic
                               text in small chunks, slowly enough that a
                               revocation can land mid-stream.

Every request is appended to <out>/ai-stub-requests.jsonl (path, model,
stream flag, message count — never message content) so the run can show the
stub was reached and nothing else was.

    python scripts/qualification/ai_stub.py --host 127.0.0.1 --port 8766
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SYNTHETIC_REPLY = ("This is a synthetic qualification reply. "
                   "What do you notice about the example? ") * 3
CHUNK_DELAY_S = 0.25


class Handler(BaseHTTPRequestHandler):
    log_path: Path | None = None
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet; the jsonl log is the record
        pass

    def _record(self, body: dict | None) -> None:
        if self.log_path is None:
            return
        entry = {"t": time.time(), "method": self.command, "path": self.path}
        if body:
            entry.update(model=body.get("model"), stream=bool(body.get("stream")),
                         messages=len(body.get("messages") or []))
        with self.log_path.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        self._record(None)
        if self.path.rstrip("/").endswith("/models"):
            self._json(200, {"object": "list", "data": [
                {"id": "synthetic-stub", "object": "model", "owned_by": "qualification"}]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            body = {}
        self._record(body)
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._json(404, {"error": "not found"})
            return
        model = body.get("model") or "synthetic-stub"
        created = int(time.time())
        if not body.get("stream"):
            self._json(200, {
                "id": "chatcmpl-synthetic", "object": "chat.completion", "created": created,
                "model": model,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": SYNTHETIC_REPLY}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            })
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def emit(obj: dict) -> None:
            self.wfile.write(b"data: " + json.dumps(obj).encode() + b"\n\n")
            self.wfile.flush()

        try:
            words = SYNTHETIC_REPLY.split(" ")
            for i in range(0, len(words), 3):
                emit({"id": "chatcmpl-synthetic", "object": "chat.completion.chunk",
                      "created": created, "model": model,
                      "choices": [{"index": 0, "delta": {"content": " ".join(words[i:i + 3]) + " "},
                                   "finish_reason": None}]})
                time.sleep(CHUNK_DELAY_S)
            emit({"id": "chatcmpl-synthetic", "object": "chat.completion.chunk", "created": created,
                  "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
            emit({"id": "chatcmpl-synthetic", "object": "chat.completion.chunk", "created": created,
                  "model": model, "choices": [],
                  "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # the caller cancelled; that is a legitimate outcome under test
        self.close_connection = True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--log", default="")
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("ai_stub: refusing to bind anything but loopback", file=sys.stderr)
        return 2
    Handler.log_path = Path(args.log) if args.log else None
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"ai_stub listening on http://{args.host}:{args.port}/v1", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
