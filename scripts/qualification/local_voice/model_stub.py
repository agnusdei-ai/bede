#!/usr/bin/env python3
"""Loopback OpenAI-compatible model stub for the local-voice check (sample only).

Binds 127.0.0.1. A streamed tutor turn answers with a short sample reply and,
when the lesson's <practice> note offers it, an `invite_practice` call for
phonics, so the real app opens a real Sound Time round. Every other request
(moderation, safety, summaries) gets the fixed verdict it expects. No model,
no network, no cost. Logs nothing about content.
Usage: model_stub.py <port>
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPLY = "STUB-TUTOR Let us try some sounds together."


def chunk(delta, finish=None):
    return {"id": "x", "object": "chat.completion.chunk", "created": 0, "model": "sample-stub",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            return self._json(200, {"object": "list", "data": [{"id": "sample-stub", "object": "model"}]})
        self._json(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        system = " ".join(str(m.get("content")) for m in body.get("messages", []) if m.get("role") == "system")
        if body.get("stream"):
            tools = {t.get("function", {}).get("name") for t in body.get("tools") or []}
            offer = "invite_practice" in tools and "<practice>" in system and "phonics" in system
            print(json.dumps({"stream": True, "tool": "invite_practice" in tools,
                              "practice_note": "<practice>" in system, "offer": offer}), flush=True)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            parts = [chunk({"role": "assistant", "content": REPLY})]
            if offer:
                parts.append(chunk({"tool_calls": [{"index": 0, "id": "call_practice", "type": "function",
                                                    "function": {"name": "invite_practice",
                                                                 "arguments": json.dumps({"area": "phonics"})}}]}))
            parts.append(chunk({}, "tool_calls" if offer else "stop"))
            for p in parts:
                self.wfile.write(b"data: " + json.dumps(p).encode() + b"\n\n")
                self.wfile.flush()
                time.sleep(0.05)
            self.wfile.write(b"data: [DONE]\n\n")
            self.close_connection = True
            return
        if '{"safe":true}' in system:
            content = json.dumps({"safe": True})
        elif '"flagged"' in system:
            content = json.dumps({"flagged": False, "categories": [], "confidence": "low"})
        else:
            content = "STUB-SUMMARY sample."
        self._json(200, {"id": "x", "object": "chat.completion", "created": int(time.time()), "model": "sample-stub",
                         "choices": [{"index": 0, "finish_reason": "stop",
                                      "message": {"role": "assistant", "content": content}}],
                         "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
