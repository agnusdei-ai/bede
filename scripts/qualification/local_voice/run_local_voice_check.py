#!/usr/bin/env python3
"""Installed Bede's voice, checked as a child experiences it (sample only).

Owner rulings 2026-11-18 and 2026-11-19 (docs/DECISIONS.md entry 46):
installed Bede speaks only in its local Piper voice, and cloud speech is never
used in the product. When Piper is not set up, switched off, failing or not
answering, a round and the chat continue without narration with every prompt
and piece of feedback on screen, and neither OpenAI's voice nor the browser's
own voice is used. Where Bede's voice cannot speak at all, the page makes no
speech request.

For each case this starts the real pieces on loopback and plays one Sound Time
round, then one chat turn, in real Chromium (check_round.cjs):

  works     voice-service/server.py with real Piper and a sample voice built here
  fails     the same server and Piper with a voice that loads and fails every line
  none      no voice at all (LOCAL_TTS_URL empty)
  disabled  TTS_PROVIDER=none, with a Piper URL and an OpenAI key both present
  hang      a voice server whose health check answers and whose lines never do

The API is the real `uvicorn main:app` on a throwaway SQLite database, with
TTS_PROVIDER=local as docker-compose.yml pins it, a loopback model stub for the
tutor, and an OPENAI_API_KEY that is set (to prove it is not used) but sample
and useless. Its HTTP(S) proxy is a local recorder that refuses and logs every
outbound connection, and HF_HUB_OFFLINE=1 keeps the speech-to-text warm-up off
the network, so a pass also proves nothing left the machine. No paid call is
made and no model is downloaded: the sample voices are built from code
(make_sample_voice.py).

This proves the plumbing, not how a real voice sounds. Physical acceptance on
the pilot Mac, with a real voice whose license is recorded, is the owner's.

Run from the repo root after `npm run build` in homeschool-tutor:
  python scripts/qualification/local_voice/run_local_voice_check.py \
      --voice-python <python with voice-service/requirements.lock.txt + onnx> --out <dir>
The python running this script needs the API's own requirements.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
API_DIR, UI_DIR = REPO / "homeschool-api", REPO / "homeschool-tutor"
API, UI, STUB, VOICE, PROXY = 18502, 18500, 18501, 18503, 18504
NAME = "Sample Learner Wren"
LINE = "Here are four counters, sample line for the voice check."
CASES = ("works", "fails", "none", "disabled", "hang")
REPLY = "STUB-TUTOR Let us try some sounds together."


class HangingVoice(BaseHTTPRequestHandler):
    """A voice server that says it is healthy and then never answers a line."""
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"voices": ["en", "es"]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        time.sleep(90)


class Recorder(BaseHTTPRequestHandler):
    """An HTTP(S) proxy that lets nothing out and remembers who tried."""
    seen: list[str] = []

    def log_message(self, *a):
        pass

    def _refuse(self):
        Recorder.seen.append(f"{self.command} {self.path}")
        self.send_response(403)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_CONNECT = do_GET = do_POST = do_PUT = do_HEAD = _refuse


def wait_http(url: str, timeout: float = 90) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if httpx.get(url, timeout=2, trust_env=False).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise SystemExit(f"{url} did not come up")


def start(cmd, cwd, env, log: Path) -> subprocess.Popen:
    return subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log.open("ab"), stderr=subprocess.STDOUT,
                            start_new_session=True)


def stop(*procs) -> None:
    for p in procs:
        if p and p.poll() is None:
            try:
                os.killpg(p.pid, 15)
                p.wait(10)
            except Exception:  # noqa: BLE001
                os.killpg(p.pid, 9)


def strong_pin() -> str:
    sys.path.insert(0, str(API_DIR))
    from core.pin_policy import is_published_credential, pin_is_strong
    while True:
        pin = "".join(secrets.choice("0123456789") for _ in range(6))
        if pin_is_strong(pin) and not is_published_credential(pin):
            return pin


def run_case(case: str, a, out: Path, voices: Path) -> dict:
    d = out / case
    d.mkdir(parents=True, exist_ok=True)
    voice = hanging = None
    if case == "hang":
        hanging = ThreadingHTTPServer(("127.0.0.1", VOICE), HangingVoice)
        threading.Thread(target=hanging.serve_forever, daemon=True).start()
    elif case not in ("none",):
        model = voices / ("sample-en.onnx" if case == "works" else "failing-en.onnx")
        venv = {k: v for k, v in os.environ.items() if not k.endswith("_PROXY") and not k.endswith("_proxy")}
        venv.update(BEDE_VOICE_EN=str(model), BEDE_VOICE_HOST="127.0.0.1", BEDE_VOICE_PORT=str(VOICE))
        voice = start([a.voice_python, "-I", str(REPO / "voice-service" / "server.py")], REPO, venv, d / "voice.log")
        wait_http(f"http://127.0.0.1:{VOICE}/health", 60)

    parent_password = "sample-" + secrets.token_hex(12)
    pin = strong_pin()
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    env.update(
        PRODUCTION="false", DISABLE_API_DOCS="true", EDUCATOR_PILOT_ENABLED="false",
        DATABASE_URL="sqlite+aiosqlite:///" + (d / "bede.db").as_posix(),
        SECRET_KEY=secrets.token_hex(32), MASTER_SECRET=secrets.token_hex(32),
        PARENT_PASSWORD=parent_password, CHILD_PIN="739184",
        LOCAL_LLM_BASE_URL=f"http://127.0.0.1:{STUB}/v1", LOCAL_LLM_MODEL="sample-stub",
        BEDE_FORCE_ADAPTER="local", TRANSCRIPTION_PROVIDER="local",
        MCP_EXTERNAL_ENABLED="false", LOCUTO_IPC_ENABLED="false",
        CORS_ORIGINS=f"http://127.0.0.1:{UI}", PYTHONUTF8="1",
        # Installed Bede, as docker-compose.yml pins it: Piper or nothing.
        TTS_PROVIDER="none" if case == "disabled" else "local",
        LOCAL_TTS_URL="" if case == "none" else f"http://127.0.0.1:{VOICE}",
        # Present, so that "never OpenAI" is tested with a key in reach. It is
        # a sample value, and the proxy below would refuse it anyway.
        OPENAI_API_KEY="sk-sample-never-used",
        HTTP_PROXY=f"http://127.0.0.1:{PROXY}", HTTPS_PROXY=f"http://127.0.0.1:{PROXY}",
        http_proxy=f"http://127.0.0.1:{PROXY}", https_proxy=f"http://127.0.0.1:{PROXY}",
        NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost",
        HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
    )
    api = start([sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(API),
                 "--workers", "1", "--no-access-log"], API_DIR, env, d / "api.log")
    preview = None
    try:
        wait_http(f"http://127.0.0.1:{API}/health")
        c = httpx.Client(base_url=f"http://127.0.0.1:{API}", timeout=30, trust_env=False)
        tok = c.post("/auth/login", json={"role": "parent", "credential": parent_password}).json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}
        c.post("/auth/elevate", json={"password": parent_password}, headers=h).raise_for_status()
        notice = hashlib.sha256((API_DIR / "data" / "consent_notice.txt").read_bytes()).hexdigest()
        cfg = {"student_name": NAME, "grade": "1", "grade_stage": "K-2", "subjects": ["language_arts"],
               "voice_required": False, "voice_narration_enabled": True}
        c.post("/pod/configs", json={"configs": [cfg], "consent_notice_hash": notice}, headers=h).raise_for_status()
        assert c.put(f"/pod/child-pins/{NAME}", json={"pin": pin}, headers=h).status_code == 204

        # The API's own answers, as a tablet would get them.
        child = c.post("/auth/login", json={"role": "child", "credential": pin, "student_name": NAME}).json()["access_token"]
        ch = {"Authorization": f"Bearer {child}"}
        status = c.get("/tutor/voice", headers=ch).json()
        r = c.post("/tutor/speak", json={"text": LINE}, headers=ch, timeout=120)
        speak = {"status": r.status_code, "type": r.headers.get("content-type"),
                 "configured": r.headers.get("x-tts-configured"), "bytes": len(r.content)}
        if r.status_code == 200:
            with wave.open(io.BytesIO(r.content)) as w:
                speak["seconds"] = round(w.getnframes() / w.getframerate(), 2)

        conf = d / "vite.preview.mjs"
        conf.write_text("export default {root: %s, preview: {host: '127.0.0.1', port: %d, strictPort: true, "
                        "proxy: {'/api': {target: %s, changeOrigin: true, rewrite: (p) => p.replace(/^\\/api/, '')}}}}\n"
                        % (json.dumps(UI_DIR.as_posix()), UI, json.dumps(f"http://127.0.0.1:{API}")))
        preview = start(["npx", "vite", "preview", "--config", str(conf)], UI_DIR, dict(os.environ), d / "preview.log")
        wait_http(f"http://127.0.0.1:{UI}/", 90)
        fixture = json.dumps({"ui": f"http://127.0.0.1:{UI}", "name": NAME, "pin": pin})
        res = subprocess.run(["node", str(HERE / "check_round.cjs")], env={**os.environ, "ROUND_FIXTURE": fixture},
                             capture_output=True, text=True, timeout=240)
        browser = json.loads(res.stdout.strip().splitlines()[-1]) if res.stdout.strip() else {"error": res.stderr[-500:]}
    finally:
        stop(preview, api, voice)
        if hanging:
            hanging.shutdown()
            hanging.server_close()
    logs = "".join((d / f).read_text(errors="replace") for f in ("api.log", "voice.log") if (d / f).exists())
    return {"case": case, "voice_status": status, "speak": speak, "browser": browser,
            "line_in_logs": LINE in logs or "sample line for the voice check" in logs}


def judge(r: dict) -> list[str]:
    """Every failed expectation for one case, in words. Empty means PASS."""
    bad, b, s, v = [], r["browser"], r["speak"], r["voice_status"]
    if b.get("error"):
        bad.append(f"browser: {b['error']} | {b.get('screen', '')[:200]}")
    if "round_open" not in b.get("steps", []):
        bad.append("the Sound Time round did not open")
    if "together" not in b.get("steps", []):
        bad.append("the round did not continue past Watch")
    if "chat_reply" not in b.get("steps", []):
        bad.append("the lesson did not go on in the chat after the round")
    if not any(b.get("lines", [])):
        bad.append("no prompt was shown on screen")
    if not b.get("feedback"):
        bad.append("no feedback was shown on screen after an answer")
    if b.get("browserVoice"):
        bad.append(f"the browser's own voice spoke: {b['browserVoice'][:3]}")
    outside = [q for q in b.get("requests", []) if not q.startswith(("127.0.0.1", "localhost"))]
    if outside:
        bad.append(f"the page reached outside the machine: {outside[:3]}")
    if r["line_in_logs"]:
        bad.append("a spoken line appeared in the API or voice logs")
    texts = b.get("speakTexts", [])
    tapped = {t for t in b.get("tapped", []) if t}
    for text in texts:
        if text in tapped:
            bad.append(f"what the child chose was sent to Bede's voice: {text!r}")
    if r["case"] in ("none", "disabled"):
        if texts:
            bad.append(f"the page asked for speech {len(texts)} time(s) where Bede's voice cannot speak")
    elif r["case"] == "works" and REPLY not in texts:
        bad.append("Bede's chat reply was not sent to Bede's voice")
    if r["case"] == "works":
        if v != {"configured": True, "where": "local", "available": True}:
            bad.append(f"/tutor/voice said {v}")
        if not (s["status"] == 200 and s["type"] == "audio/wav" and s.get("seconds", 0) > 0):
            bad.append(f"/tutor/speak did not return Piper's WAV: {s}")
        if not any(x["status"] == 200 and x["type"] == "audio/wav" and x["bytes"] > 44 for x in b.get("speak", [])):
            bad.append("the round's lines never came back as Piper audio")
        if not any(p.get("ok") and p["src"].startswith("blob:") for p in b.get("plays", [])):
            bad.append("no Piper audio played in the page")
    else:
        want = {"configured": True, "where": "local", "available": True} if r["case"] in ("fails", "hang") \
            else {"configured": False, "where": None, "available": False}
        if v != want:
            bad.append(f"/tutor/voice said {v}, expected {want}")
        if s["status"] != 204:
            bad.append(f"/tutor/speak returned {s['status']}, expected 204 (silence)")
        if any(x["status"] == 200 for x in b.get("speak", [])):
            bad.append("some line came back as audio")
        if any(p.get("ok") and not p["src"].startswith("data:") for p in b.get("plays", [])):
            bad.append("audio other than the silent unlock clip played")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice-python", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cases", default=",".join(CASES))
    a = ap.parse_args()
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if not (UI_DIR / "dist" / "index.html").exists():
        raise SystemExit("Build the app first: cd homeschool-tutor && npm run build")
    voices = out / "voices"
    for extra in ([], ["--failing"]):
        subprocess.run([a.voice_python, "-I", str(HERE / "make_sample_voice.py"), str(voices), "en", *extra], check=True)

    proxy = ThreadingHTTPServer(("127.0.0.1", PROXY), Recorder)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    stub = start([sys.executable, str(HERE / "model_stub.py"), str(STUB)], REPO, dict(os.environ), out / "stub.log")
    wait_http(f"http://127.0.0.1:{STUB}/v1/models", 30)
    results = []
    try:
        for case in a.cases.split(","):
            seen_before = len(Recorder.seen)
            r = run_case(case, a, out, voices)
            r["outbound"] = Recorder.seen[seen_before:]
            r["problems"] = judge(r) + (
                [f"tried to reach outside the machine: {sorted(set(r['outbound']))}"] if r["outbound"] else [])
            r["verdict"] = "PASS" if not r["problems"] else "FAIL"
            results.append(r)
            print(f"{case}: {r['verdict']} {r['problems']}", flush=True)
    finally:
        stop(stub)
        proxy.shutdown()
    outbound = list(Recorder.seen)
    summary = {"cases": {r["case"]: r["verdict"] for r in results}, "outbound_attempts": outbound,
               "verdict": "PASS" if all(r["verdict"] == "PASS" for r in results) and not outbound else "FAIL"}
    (out / "report.json").write_text(json.dumps({"summary": summary, "results": results}, indent=2))
    print(json.dumps(summary))
    return 0 if summary["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
