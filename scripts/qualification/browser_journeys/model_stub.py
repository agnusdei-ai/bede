#!/usr/bin/env python3
"""Loopback OpenAI-compatible model stub with injected latency (sample only).

Used by run_journeys.py (cross-platform browser journeys, #599/#755). Binds
127.0.0.1 only. Returns one fixed sample worksheet reading, a safety
verdict, a picture-check verdict, a moderation verdict, or streamed tutor text. Every completion waits a random
0.5-3.0 s (non-stream: whole delay before reply; stream: 0.4-1.2 s to first
token, then chunks) so concurrent requests genuinely overlap.
Logs t_start/t_end/kind per request (never content) to <dir>/stub.jsonl.
"""
import json, random, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CTL = Path(sys.argv[2]); LOG = CTL / "stub.jsonl"; LOCK = threading.Lock()
READING = {"subject": "history", "sections": [{
  "label": "Ancient Egypt", "instructions": "Answer each question.", "required_format": "free",
  "items": [
    {"number": 1, "prompt": "Which river flooded every year in Egypt?", "student_response": "Nile", "teacher_mark": "correct"},
    {"number": 2, "prompt": "What was the ruler of Egypt called?", "student_response": "king", "teacher_mark": "incorrect",
     "teacher_correction": "pharoh", "confidence": 0.4, "ask_parent": "Is the teacher's correction spelled pharoh or pharaoh?"},
    {"number": 3, "prompt": "What did Egyptians make paper from?", "student_response": "reeds", "teacher_mark": "incorrect"},
    {"number": 4, "prompt": "On which continent is Egypt?", "student_response": "Africa", "teacher_mark": "correct"}]}]}
# The opening words of content_screen's rules; tests/test_qualification_workflow.py
# checks they still match the real prompt.
SCREEN_MARK = "You check pictures before a K-8 school app"
REPLY = "STUB-TUTOR sample reply. Good thinking. What clue in the question helped you decide?"


def log(entry):
    with LOCK, LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            return self._send(200, {"object": "list", "data": [{"id": "sample-stub", "object": "model"}]})
        self._send(404, {})

    def do_POST(self):
        t0 = time.time()
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        sysmsg = " ".join(str(m.get("content")) for m in body.get("messages", []) if m.get("role") == "system")
        imgs = sum(1 for m in body.get("messages", []) if isinstance(m.get("content"), list)
                   for p in m["content"] if p.get("type") == "image_url")
        if body.get("stream"):
            kind = "stream"
            try:
                self.send_response(200); self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close"); self.end_headers()
                time.sleep(random.uniform(0.4, 1.2))
                words = REPLY.split(" ")
                for i in range(0, len(words), 2):
                    ch = {"id": "x", "object": "chat.completion.chunk", "created": 0, "model": "sample-stub",
                          "choices": [{"index": 0, "delta": {"role": "assistant", "content": " ".join(words[i:i+2]) + " "}, "finish_reason": None}]}
                    self.wfile.write(b"data: " + json.dumps(ch).encode() + b"\n\n"); self.wfile.flush()
                    time.sleep(random.uniform(0.05, 0.2))
                end = {"id": "x", "object": "chat.completion.chunk", "created": 0, "model": "sample-stub", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                self.wfile.write(b"data: " + json.dumps(end).encode() + b"\n\ndata: [DONE]\n\n"); self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                kind = "stream-cancelled"
            self.close_connection = True
            log({"t0": t0, "t1": time.time(), "kind": kind, "images": imgs}); return
        time.sleep(random.uniform(0.5, 3.0))
        if SCREEN_MARK in sysmsg:
            # The upload/lesson picture check (services/content_screen.py)
            # also carries images, so it must be recognised before the
            # reading branch: answered with a reading, the real parser
            # refuses it as unclear and every upload fails closed.
            kind, content = "screen", json.dumps({"verdict": "ok"})
        elif "Subject:" in sysmsg or imgs:
            kind, content = "reading", json.dumps(READING)
        elif '{"safe":true}' in sysmsg:
            kind, content = "safety", json.dumps({"safe": True})
        elif '"flagged"' in sysmsg:
            kind, content = "moderation", json.dumps({"flagged": False, "categories": [], "confidence": "low"})
        else:
            kind, content = "other", "STUB-SUMMARY sample."
        try:
            self._send(200, {"id": "x", "object": "chat.completion", "created": int(time.time()), "model": "sample-stub",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
        except (BrokenPipeError, ConnectionResetError):
            kind += "-cancelled"
        log({"t0": t0, "t1": time.time(), "kind": kind, "images": imgs})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
