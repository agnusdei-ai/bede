#!/usr/bin/env python3
"""Cross-platform browser journeys against one local Bede service.

Runs on a real Windows or macOS runner (see
.github/workflows/cross-platform-browser-journeys.yml). Starts the real
`uvicorn main:app` with its real lifespan on a file-backed SQLite database,
the real homeschool-tutor build under `vite preview`, and a loopback model
stub. Seeds one synthetic household through the real API, then runs
journeys.cjs, which drives every requested browser at the same time against
this one service. Restarts the API mid-run when journeys.cjs asks.

Synthetic data only. No commercial model, no mail, no real learner.
Exits non-zero if any journey check fails.

    python run_journeys.py --sha <40-hex> --browsers chrome,msedge --out <dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
API_DIR = REPO / "homeschool-api"
UI_DIR = REPO / "homeschool-tutor"
API_PORT, UI_PORT, STUB_PORT = 18402, 18400, 18401
BROWSERS = {"chrome", "msedge", "webkit", "chromium", "firefox"}
EVENTS: list[dict] = []


def ev(**k):
    k["t"] = round(time.time(), 3)
    EVENTS.append(k)
    print("EVENT", json.dumps(k), flush=True)


def print_log_tails(out: Path) -> None:
    """Artifacts are not always reachable by whoever reads the run, so a
    failing run also prints the end of the service logs it depended on.
    Synthetic data only; these logs carry no credentials."""
    for name in ("api.log", "stub.log", "preview.log"):
        f = out / name
        if f.exists():
            tail = f.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
            sys.stdout.write(f"\n===== last {len(tail)} lines of {name} =====\n" + "\n".join(tail) + "\n")
    sys.stdout.flush()


def wait_http(url: str, proc: subprocess.Popen | None, what: str, timeout: float = 240) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            raise SystemExit(f"{what} exited during startup ({proc.returncode})")
        try:
            if httpx.get(url, timeout=3).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise SystemExit(f"{what} not ready within {timeout}s")


def make_fixtures(out: Path) -> Path:
    """A synthetic graded quiz page as PNG and as an image PDF (Pillow only)."""
    from PIL import Image, ImageDraw
    fx = out / "fixtures"
    fx.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(img)
    lines = ["Synthetic quiz - Ancient Egypt", "1. Which river flooded every year?  Nile   (correct)",
             "2. What was the ruler called?  king   (x)  pharoh", "3. What did they make paper from?  reeds  (x)",
             "4. On which continent is Egypt?  Africa  (correct)"]
    for i, line in enumerate(lines):
        d.text((80, 120 + i * 90), line, fill="black")
    img.save(fx / "quiz.png")
    img.save(fx / "quiz.pdf", "PDF", resolution=150)
    img.convert("RGB").save(fx / "quiz.jpg", "JPEG", quality=85)
    return fx


def npx() -> str:
    exe = shutil.which("npx") or shutil.which("npx.cmd")
    if not exe:
        raise SystemExit("npx not found")
    return exe


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", required=True)
    ap.add_argument("--browsers", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", a.sha):
        raise SystemExit("--sha must be a 40-character lowercase commit SHA")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    if head != a.sha:
        raise SystemExit(f"checked-out HEAD {head} is not the candidate {a.sha}")
    browsers = [b.strip() for b in a.browsers.split(",") if b.strip()]
    if not browsers or set(browsers) - BROWSERS:
        raise SystemExit(f"unknown browser in {browsers}")
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "ctl").mkdir(exist_ok=True)
    fixtures = make_fixtures(out)

    # One learner per browser; the household parent and every child sign in at once.
    learners = {f"Synthetic Learner {chr(65 + i)}": pin for i, pin in
                enumerate(["582916", "694217", "815372", "927481", "361948"][:len(browsers)])}
    parent_password = "synthetic-" + secrets.token_hex(12)
    env = {k: v for k, v in os.environ.items()
           if not k.endswith("_API_KEY") and not k.startswith(("STRIPE_", "AZURE_"))}
    env.update(
        PRODUCTION="false", DISABLE_API_DOCS="true", EDUCATOR_PILOT_ENABLED="false",
        DATABASE_URL="sqlite+aiosqlite:///" + (out / "journeys.db").as_posix(),
        SECRET_KEY=secrets.token_hex(32), MASTER_SECRET=secrets.token_hex(32),
        PARENT_PASSWORD=parent_password, CHILD_PIN="739184",
        LOCAL_LLM_BASE_URL=f"http://127.0.0.1:{STUB_PORT}/v1", LOCAL_LLM_MODEL="synthetic-stub",
        BEDE_FORCE_ADAPTER="local", TRANSCRIPTION_PROVIDER="local",
        MCP_EXTERNAL_ENABLED="false", LOCUTO_IPC_ENABLED="false",
        # Every browser here shares the runner's loopback address; a real LAN gives each device its own.
        RATE_LIMIT_AUTH_PER_MINUTE="600", RATE_LIMIT_API_PER_MINUTE="6000",
        CORS_ORIGINS=f"http://127.0.0.1:{UI_PORT}", PYTHONUTF8="1",
    )
    procs: list[subprocess.Popen] = []
    stub = subprocess.Popen([sys.executable, str(HERE / "model_stub.py"), str(STUB_PORT), str(out)],
                            stdout=(out / "stub.log").open("ab"), stderr=subprocess.STDOUT)
    procs.append(stub)
    api_state = {"proc": None, "starts": 0}

    def start_api():
        api_state["starts"] += 1
        api_state["proc"] = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(API_PORT),
             "--workers", "1", "--no-access-log"], cwd=API_DIR, env=env,
            stdout=(out / "api.log").open("ab"), stderr=subprocess.STDOUT)
        wait_http(f"http://127.0.0.1:{API_PORT}/health", api_state["proc"], "uvicorn main:app")

    t0 = time.time()
    start_api()
    ev(e="api_started", boot_s=round(time.time() - t0, 2), sha=a.sha)

    api = httpx.Client(base_url=f"http://127.0.0.1:{API_PORT}", headers={"User-Agent": "journeys-seed"}, timeout=30)
    tok = api.post("/auth/login", json={"role": "parent", "credential": parent_password}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    api.post("/auth/elevate", json={"password": parent_password}, headers=h).raise_for_status()
    notice = hashlib.sha256((API_DIR / "data" / "consent_notice.txt").read_bytes()).hexdigest()
    cfgs = [{"student_name": n, "grade": "4", "grade_stage": "3-5", "subjects": ["history", "mathematics"],
             "voice_required": False} for n in learners]
    r = api.post("/pod/configs", json={"configs": cfgs, "consent_notice_hash": notice}, headers=h)
    if r.status_code not in (200, 201, 204):
        raise SystemExit(f"seed pod configs -> {r.status_code}")
    for n, pin in learners.items():
        r = api.put(f"/pod/child-pins/{n}", json={"pin": pin}, headers=h)
        if r.status_code != 204:
            raise SystemExit(f"seed child pin -> {r.status_code}")
    ev(e="household_seeded", learners=len(learners))

    conf = out / "vite.preview.mjs"
    conf.write_text("export default {root: %s, preview: {host: '127.0.0.1', port: %d, strictPort: true, "
                    "proxy: {'/api': {target: %s, changeOrigin: true, "
                    "rewrite: (p) => p.replace(/^\\/api/, '')}}}}\n"
                    % (json.dumps(UI_DIR.as_posix()), UI_PORT, json.dumps(f"http://127.0.0.1:{API_PORT}")))
    preview = subprocess.Popen([npx(), "vite", "preview", "--config", str(conf)], cwd=UI_DIR,
                               stdout=(out / "preview.log").open("ab"), stderr=subprocess.STDOUT)
    procs.append(preview)
    wait_http(f"http://127.0.0.1:{UI_PORT}/", preview, "vite preview", timeout=90)

    fixture = {"ui": f"http://127.0.0.1:{UI_PORT}", "api": f"http://127.0.0.1:{API_PORT}",
               "parent_password": parent_password, "learners": learners, "browsers": browsers,
               "fixtures": str(fixtures), "out": str(out), "ctl": str(out / "ctl"),
               "os": sys.platform, "sha": a.sha}
    (out / "fixture.json").write_text(json.dumps(fixture))
    load_env = dict(env, FIX=str(out / "fixture.json"))
    load = subprocess.Popen(["node", str(HERE / "journeys.cjs")], env=load_env,
                            stdout=(out / "journeys.log").open("ab"), stderr=subprocess.STDOUT)
    rc = None
    try:
        while rc is None:
            rc = load.poll()
            req = out / "ctl" / "restart"
            if req.exists():
                req.unlink()
                api_state["proc"].kill()
                api_state["proc"].wait()
                ev(e="api_killed")
                (out / "ctl" / "killed").write_text(str(time.time()))
                time.sleep(5)
                t0 = time.time()
                start_api()
                ev(e="api_restarted", boot_s=round(time.time() - t0, 2))
                (out / "ctl" / "restarted").write_text(str(time.time()))
            time.sleep(0.2)
    finally:
        ev(e="journeys_exit", rc=rc)
        (out / "events.json").write_text(json.dumps(EVENTS, indent=1))
        live = [p for p in [api_state["proc"], *procs] if p and p.poll() is None]
        for p in live:
            p.send_signal(signal.SIGTERM) if os.name != "nt" else p.terminate()
        # Windows cannot delete a file another process still has open, so
        # wait for the processes to exit before removing the database.
        for p in live:
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                p.kill()
        try:
            (out / "journeys.db").unlink(missing_ok=True)
        except PermissionError as exc:
            print(f"could not remove journeys.db: {exc}", flush=True)
    sys.stdout.write((out / "journeys.log").read_text(encoding="utf-8", errors="replace"))
    if rc:
        print_log_tails(out)
    return rc or 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit as exc:
        if exc.code not in (0, None) and not isinstance(exc.code, int):
            print(exc.code, flush=True)
            for i, arg in enumerate(sys.argv):
                if arg == "--out" and i + 1 < len(sys.argv):
                    print_log_tails(Path(sys.argv[i + 1]))
            raise SystemExit(1)
        raise
