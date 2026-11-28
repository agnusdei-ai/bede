#!/usr/bin/env python3
"""How many children can ONE Bede backend serve at once?

    # The docker stack (the workflow boots it first; see capacity.yml):
    python run_capacity.py --sha <40-hex> --target stack --parts browser,api --out <dir>
    # A local uvicorn + vite preview (no docker), for a quick look:
    python run_capacity.py --sha <40-hex> --target local --parts browser,api --out <dir>

Steps the number of concurrent sessions up (capacity.json), holding a steady
lesson load at each step for a fixed window, and records per step: first-token
and full-turn latency, every status, dropped and duplicated turns and practice
answers, the API process's RSS, CPU, threads, file descriptors and disk I/O,
the DB pool's checkouts and wait, 429s by rate-limit bucket, the container's
OOM/restart state and its storage, and the runner's own CPU and memory, so a
saturated runner is never mistaken for a Bede limit. Writes report.json,
report.md and SHA256SUMS to --out, after a fail-closed credential scan.

Two parts:
  browser  real Chromium sessions (browser_sessions.cjs), the primary result,
           with a PASS/FAIL/NOT_RUN verdict at capacity.json's required count;
  api      httpx clients (loadgen.py), cheaper per session, to find headroom.

Every sample device arrives from its own address (relay.py and httpx
`local_address`), because the per-IP rate limit keys on the client address and
a household's tablets each have their own. The address the API actually saw
per device is recorded, and so is what happens without that (every device on
one address), as a finding.

Report only. Exits non-zero only when the run could not produce trustworthy
evidence (bad inputs, the service never came up, a credential in the output),
never because a step failed its thresholds.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
API_DIR = REPO / "homeschool-api"
UI_DIR = REPO / "homeschool-tutor"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(API_DIR))
import loadgen  # noqa: E402
from instrumented_api import WAIT_EDGES  # noqa: E402
import report as rpt  # noqa: E402

API_PORT, UI_PORT, STUB_PORT = 18412, 18410, 18411
BROWSER_RELAY_BASE, API_RELAY_BASE, PARENT_RELAY = 19000, 19100, 19099
MAX_LEARNERS = 10  # PodConfigsRequest's cap, and the throwaway licence's seats
HISTORY_TURN = {"number": 1, "prompt": "Which river flooded every year in Egypt?", "student_response": "Nile",
                "teacher_mark": "correct"}


def log(msg: str) -> None:
    print(f"[capacity {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def own_group() -> dict:
    return {"start_new_session": True}


def stop(procs) -> None:
    for p in procs:
        if p and p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    for p in procs:
        if p:
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)


def wait_http(url: str, proc, what: str, timeout: float = 240, verify: bool = True) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            raise SystemExit(f"{what} exited during startup ({proc.returncode})")
        try:
            if httpx.get(url, timeout=3, verify=verify).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise SystemExit(f"{what} not ready within {timeout}s")


def sh(*cmd: str, check: bool = False, timeout: float = 60) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise SystemExit(f"{' '.join(cmd[:3])} failed: {r.stderr[-400:]}")
    return r.stdout


# ── host sampling: the runner itself, so a saturated runner is visible ─────
def _cpu_times() -> tuple[float, float]:
    f = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
    vals = [float(x) for x in f]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    return sum(vals), idle


def host_sample(prev: tuple | None) -> tuple[dict, tuple]:
    total, idle = _cpu_times()
    mem = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        k, _, v = line.partition(":")
        mem[k] = int(v.split()[0])
    chrome_kb = 0
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            if "chrom" in (d / "comm").read_text():
                for line in (d / "status").read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        chrome_kb += int(line.split()[1])
        except OSError:
            continue
    cpu = None
    if prev:
        dt, di = total - prev[0], idle - prev[1]
        cpu = (dt - di) / dt if dt > 0 else None
    out = {"cpu_fraction": cpu, "mem_fraction": 1 - mem.get("MemAvailable", 0) / mem["MemTotal"],
           "mem_total_mb": mem["MemTotal"] / 1024, "chrome_rss_mb": chrome_kb / 1024}
    return out, (total, idle)


class Sampler(threading.Thread):
    """Samples the host and the backend every second into timestamped lists."""

    def __init__(self, backend):
        super().__init__(daemon=True)
        self.backend, self.host, self.api, self.container = backend, [], [], []
        self.halt = threading.Event()

    def run(self):
        prev = None
        n = 0
        while not self.halt.is_set():
            t = time.time()
            h, prev = host_sample(prev)
            self.host.append(dict(h, t=t))
            snap = self.backend.read_metrics()
            if snap:
                self.api.append(dict(snap, t=t))
            if n % 2 == 0:
                c = self.backend.container_sample()
                if c:
                    self.container.append(dict(c, t=t))
            n += 1
            self.halt.wait(1.0)


# ── backends ─────────────────────────────────────────────────────────────────
class Backend:
    target = "?"
    layout = "?"
    procs: list

    def child_endpoint(self, i: int) -> tuple[str, str | None, bool]:
        raise NotImplementedError

    def ui_url(self, i: int) -> str:
        raise NotImplementedError

    def read_metrics(self) -> dict | None:
        raise NotImplementedError

    def container_sample(self) -> dict | None:
        return None

    def container_state(self) -> dict:
        return {}

    def storage(self) -> dict:
        return {}

    def log_text(self, since: float, until: float) -> str:
        return ""


def start_stub(out: Path, stub_cfg: dict, bind: str) -> subprocess.Popen:
    env = dict(os.environ, STUB_NONSTREAM_DELAY_S=stub_cfg["nonstream_delay_s"],
               STUB_FIRST_TOKEN_DELAY_S=stub_cfg["first_token_delay_s"],
               STUB_CHUNK_DELAY_S=stub_cfg["chunk_delay_s"], STUB_BIND=bind)
    (out / "stub").mkdir(exist_ok=True)
    p = subprocess.Popen([sys.executable, str(REPO / "scripts/qualification/browser_journeys/model_stub.py"),
                          str(STUB_PORT), str(out / "stub")], env=env,
                         stdout=(out / "stub.log").open("ab"), stderr=subprocess.STDOUT, **own_group())
    wait_http(f"http://{bind}:{STUB_PORT}/v1/models", p, "model stub", 30)
    return p


def start_relays(out: Path, specs: list[str], name: str) -> subprocess.Popen:
    args = [sys.executable, str(HERE / "relay.py")]
    for s in specs:
        args += ["--spec", s]
    p = subprocess.Popen(args, stdout=(out / f"{name}.log").open("ab"), stderr=subprocess.STDOUT, **own_group())
    time.sleep(1.0)
    if p.poll() is not None:
        raise SystemExit(f"{name} exited at startup; see {name}.log")
    return p


class LocalBackend(Backend):
    """uvicorn (through instrumented_api.py) + vite preview on this machine.
    SQLite unless CAPACITY_DATABASE_URL names a Postgres."""
    target = "local"

    def __init__(self, out: Path, cfg: dict, parts: set, overrides: dict, browsers: int, api_children: int):
        self.out, self.procs = out, []
        self.metrics_path = out / "ctl" / "api-metrics.json"
        self.parent_password = "cap-" + secrets.token_hex(12)
        db = os.environ.get("CAPACITY_DATABASE_URL") or "sqlite+aiosqlite:///" + (out / "ctl" / "capacity.db").as_posix()
        self.db_kind = "postgres" if db.startswith("postgres") else "sqlite"
        self.layout = (f"one machine: uvicorn + {self.db_kind} + vite preview + loopback stub; each device its own "
                       "127.0.0.x address")
        env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY") and not k.startswith(("STRIPE_", "AZURE_"))}
        env.update(PRODUCTION="false", DISABLE_API_DOCS="true", EDUCATOR_PILOT_ENABLED="false", DATABASE_URL=db,
                   SECRET_KEY=secrets.token_hex(32), MASTER_SECRET=secrets.token_hex(32),
                   PARENT_PASSWORD=self.parent_password, CHILD_PIN="739184",
                   LOCAL_LLM_BASE_URL=f"http://127.0.0.1:{STUB_PORT}/v1", LOCAL_LLM_MODEL="sample-stub",
                   BEDE_FORCE_ADAPTER="local", TRANSCRIPTION_PROVIDER="local", MCP_EXTERNAL_ENABLED="false",
                   LOCUTO_IPC_ENABLED="false", CORS_ORIGINS=f"http://127.0.0.1:{UI_PORT}", PYTHONUTF8="1",
                   CAPACITY_METRICS_PATH=str(self.metrics_path))
        for k, v in overrides.items():
            if v is not None:
                env[k] = str(v)
        self.env = env
        self.procs.append(start_stub(out, cfg["stub"], "127.0.0.1"))
        self.api = subprocess.Popen([sys.executable, str(HERE / "instrumented_api.py"), "--host", "127.0.0.1",
                                     "--port", str(API_PORT), "--forwarded-allow-ips", "127.0.0.1"], cwd=API_DIR,
                                    env=env, stdout=(out / "api.log").open("ab"), stderr=subprocess.STDOUT, **own_group())
        self.procs.append(self.api)
        wait_http(f"http://127.0.0.1:{API_PORT}/health", self.api, "instrumented API")
        self.api_base = f"http://127.0.0.1:{API_PORT}"
        if "browser" in parts:
            # xfwd: the preview server passes each browser's address on as
            # X-Forwarded-For, as nginx does in the real stack; uvicorn trusts
            # it only from 127.0.0.1, where the preview server runs.
            conf = out / "ctl" / "vite.preview.mjs"
            conf.write_text("export default {root: %s, preview: {host: '127.0.0.1', port: %d, strictPort: true, "
                            "proxy: {'/api': {target: %s, changeOrigin: true, xfwd: true, "
                            "rewrite: (p) => p.replace(/^\\/api/, '')}}}}\n"
                            % (json.dumps(UI_DIR.as_posix()), UI_PORT, json.dumps(self.api_base)))
            npx = shutil.which("npx") or "npx"
            self.procs.append(subprocess.Popen([npx, "vite", "preview", "--config", str(conf)], cwd=UI_DIR,
                                               stdout=(out / "preview.log").open("ab"), stderr=subprocess.STDOUT,
                                               **own_group()))
            wait_http(f"http://127.0.0.1:{UI_PORT}/", self.procs[-1], "vite preview", 90)
            specs = [f"127.0.0.1:{BROWSER_RELAY_BASE + i}=127.0.0.{20 + i}>127.0.0.1:{UI_PORT}" for i in range(browsers)]
            self.procs.append(start_relays(out, specs, "browser-relays"))
        self.browser_relays = browsers if "browser" in parts else 0

    def parent_client(self) -> httpx.Client:
        transport = httpx.HTTPTransport(local_address="127.0.0.250")
        return httpx.Client(base_url=self.api_base, transport=transport, headers={"User-Agent": "capacity-seed"}, timeout=60)

    def child_endpoint(self, i):
        return self.api_base, f"127.0.0.{100 + i}", True

    def ui_url(self, i):
        return f"http://127.0.0.1:{BROWSER_RELAY_BASE + i}"

    def read_metrics(self):
        try:
            return json.loads(self.metrics_path.read_text())
        except (OSError, ValueError):
            return None

    def container_state(self):
        return {"oom_killed": None, "restarts": 0 if self.api.poll() is None else 1,
                "note": "no container: RSS is compared with the compose default limit, not an enforced one"}

    def storage(self):
        db = self.out / "ctl" / "capacity.db"
        du = shutil.disk_usage(self.out)
        return {"db_bytes": db.stat().st_size if db.exists() else None, "free_bytes": du.free}

    _log_pos = 0

    def log_text(self, since, until):
        """The API log written since the previous call (one call per step)."""
        with (self.out / "api.log").open("rb") as f:
            f.seek(self._log_pos)
            data = f.read()
            self._log_pos = f.tell()
        return data.decode("utf-8", errors="replace")


class StackBackend(Backend):
    """The real docker compose stack (Caddy -> nginx -> api + Postgres), booted
    by the workflow with docker-compose.capacity.yml layered on. Each device
    gets its own address on the stack's docker network (secondary addresses
    on the bridge, sudo), reached through relay.py, so Caddy sees a distinct
    client per device as it would on a LAN."""
    target = "stack"

    def __init__(self, out: Path, cfg: dict, parts: set, browsers: int, api_children: int):
        self.out, self.procs = out, []
        env = dict(line.split("=", 1) for line in (REPO / ".env").read_text().splitlines() if "=" in line)
        self.parent_password = env["PARENT_PASSWORD"]
        self.secrets = {k: env.get(k, "") for k in ("SECRET_KEY", "MASTER_SECRET", "PARENT_PASSWORD", "CHILD_PIN", "POSTGRES_PASSWORD")}
        self.ids = {s: sh("docker", "compose", "ps", "-q", s).strip() for s in ("api", "db", "caddy", "ui")}
        if not self.ids["api"] or not self.ids["caddy"]:
            raise SystemExit("the compose stack is not running")
        net = json.loads(sh("docker", "inspect", self.ids["caddy"], check=True))[0]["NetworkSettings"]["Networks"]
        name, info = next(iter(net.items()))
        self.caddy_ip = info["IPAddress"]
        nw = json.loads(sh("docker", "network", "inspect", name, check=True))[0]
        bridge = "br-" + nw["Id"][:12]
        subnet = nw["IPAM"]["Config"][0]["Subnet"]
        network = ipaddress.ip_network(subnet)
        n = browsers + api_children + 1
        if n > network.num_addresses // 4:
            raise SystemExit("too many devices for the stack network")
        # The top of the subnet: Docker hands container addresses out from
        # the bottom, so these never collide with a container.
        self.alias = [str(network.broadcast_address - (2 + k)) for k in range(n)]
        prefix = network.prefixlen
        for a in self.alias:
            subprocess.run(["sudo", "ip", "addr", "add", f"{a}/{prefix}", "dev", bridge], capture_output=True)
        self.layout = (f"docker stack on this runner; browsers and clients on the host, each device its own address "
                       f"on the stack network (the top {n} addresses of {subnet} on {bridge}), reaching Caddy directly")
        upstream = f"{self.caddy_ip}:443"
        specs = [f"127.0.0.1:{PARENT_RELAY}={self.alias[0]}>{upstream}"]
        specs += [f"127.0.0.1:{BROWSER_RELAY_BASE + i}={self.alias[1 + i]}>{upstream}" for i in range(browsers)]
        specs += [f"127.0.0.1:{API_RELAY_BASE + i}={self.alias[1 + browsers + i]}>{upstream}" for i in range(api_children)]
        self.procs.append(start_relays(out, specs, "relays"))
        self.browser_relays, self.api_relays = browsers, api_children
        docker0 = re.search(r"inet (\S+)/", sh("ip", "-4", "-o", "addr", "show", "docker0"))
        self.procs.insert(0, start_stub(out, cfg["stub"], docker0.group(1) if docker0 else "127.0.0.1"))
        wait_http(f"https://localhost:{PARENT_RELAY}/api/health", None, "the stack through a relay", 120, verify=False)
        mem = json.loads(sh("docker", "inspect", self.ids["api"], check=True))[0]["HostConfig"]["Memory"]
        self.mem_limit_mb = mem / 1048576 if mem else None

    def parent_client(self):
        return httpx.Client(base_url=f"https://localhost:{PARENT_RELAY}/api", verify=False,
                            headers={"User-Agent": "capacity-seed"}, timeout=60)

    def child_endpoint(self, i):
        return f"https://localhost:{API_RELAY_BASE + i}/api", None, False

    def ui_url(self, i):
        return f"https://localhost:{BROWSER_RELAY_BASE + i}"

    def read_metrics(self):
        r = subprocess.run(["docker", "exec", self.ids["api"], "cat", "/tmp/capacity-metrics.json"],
                           capture_output=True, text=True, timeout=20)
        try:
            return json.loads(r.stdout) if r.returncode == 0 else None
        except ValueError:
            return None

    def container_sample(self):
        r = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}", self.ids["api"]],
                           capture_output=True, text=True, timeout=30)
        try:
            s = json.loads(r.stdout.strip().splitlines()[0])
        except (ValueError, IndexError):
            return None
        return {"mem": s.get("MemUsage"), "mem_perc": float(str(s.get("MemPerc", "0")).rstrip("%") or 0),
                "cpu_perc": float(str(s.get("CPUPerc", "0")).rstrip("%") or 0), "pids": int(s.get("PIDs") or 0),
                "block_io": s.get("BlockIO")}

    def container_state(self):
        st = json.loads(sh("docker", "inspect", self.ids["api"]))[0]
        return {"oom_killed": st["State"].get("OOMKilled"), "restarts": st.get("RestartCount", 0),
                "started_at": st["State"].get("StartedAt"), "mem_limit_mb": self.mem_limit_mb}

    def storage(self):
        out = {}
        if self.ids.get("db"):
            du = sh("docker", "exec", self.ids["db"], "du", "-sk", "/var/lib/postgresql/data").split()
            df = sh("docker", "exec", self.ids["db"], "df", "-k", "/var/lib/postgresql/data").splitlines()
            out["pgdata_kb"] = int(du[0]) if du else None
            out["pg_free_kb"] = int(df[-1].split()[3]) if len(df) > 1 else None
        df = sh("docker", "exec", self.ids["api"], "df", "-k", "/tmp").splitlines()
        if len(df) > 1:
            out["api_tmp_used_kb"], out["api_tmp_free_kb"] = int(df[-1].split()[2]), int(df[-1].split()[3])
        out["uploads_volume"] = "none: docker-compose.yml has no uploads volume (practice photos are request-only)"
        out["host_free_bytes"] = shutil.disk_usage("/").free
        return out

    def log_text(self, since, until):
        r = subprocess.run(["docker", "logs", "--since", str(int(since)), "--until", str(int(until) + 1), self.ids["api"]],
                           capture_output=True, text=True, timeout=60)
        return r.stdout + r.stderr


# ── seeding: one household through the real parent API ─────────────────────
def seed(backend, n: int) -> dict[str, str]:
    from core.pin_policy import pin_is_strong, suggest_pin
    pins: list[str] = []
    while len(pins) < n:
        p = suggest_pin()
        if pin_is_strong(p) and p not in pins and p != "739184":
            pins.append(p)
    learners = {f"Sample Learner {chr(65 + i)}": pin for i, pin in enumerate(pins)}
    records: dict[str, int] = {}
    api = backend.parent_client()
    r = api.post("/auth/login", json={"role": "parent", "credential": backend.parent_password})
    r.raise_for_status()
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    api.post("/auth/elevate", json={"password": backend.parent_password}, headers=h).raise_for_status()
    notice = hashlib.sha256((API_DIR / "data" / "consent_notice.txt").read_bytes()).hexdigest()
    cfgs = [{"student_name": nm, "grade": "4", "grade_stage": "3-5", "subjects": ["history", "mathematics"],
             "voice_required": False} for nm in learners]
    r = api.post("/pod/configs", json={"configs": cfgs, "consent_notice_hash": notice}, headers=h)
    if r.status_code not in (200, 201, 204):
        raise SystemExit(f"seed pod configs -> {r.status_code}")
    for nm, pin in learners.items():
        if api.put(f"/pod/child-pins/{nm}", json={"pin": pin}, headers=h).status_code != 204:
            raise SystemExit("seed child pin failed")
        a = {"subject": "history", "sections": [{"label": "Ancient Egypt", "instructions": "Answer each question.",
             "required_format": "free", "items": [
                 HISTORY_TURN,
                 {"number": 2, "prompt": "What was the ruler of Egypt called?", "student_response": "king",
                  "teacher_mark": "incorrect", "teacher_correction": "pharaoh"},
                 {"number": 3, "prompt": "What did Egyptians make paper from?", "student_response": "reeds",
                  "teacher_mark": "incorrect", "teacher_correction": "papyrus"},
                 {"number": 4, "prompt": "On which continent is Egypt?", "student_response": "Africa",
                  "teacher_mark": "correct"}]}]}
        r = api.post(f"/practice/{nm}/assessments", json={"assessment": a}, headers=h)
        if r.status_code != 201:
            raise SystemExit(f"seed assessment -> {r.status_code} {r.text[:200]}")
        records[nm] = r.json()["id"]
    backend.parent_headers, backend.parent, backend.records = h, api, records
    approve_new_sets(backend, list(learners))
    return learners


def approve_new_sets(backend, names) -> None:
    """A fresh approved practice set per learner, planned from the learner's
    confirmed quiz, so every browser step has a question left to answer (a
    learner answers one per step, and a set holds only a few)."""
    for nm in names:
        r = backend.parent.post(f"/practice/{nm}/assessments/{backend.records[nm]}/plan", headers=backend.parent_headers)
        set_id = r.json().get("set_id") if r.status_code == 201 else None
        if not set_id:
            raise SystemExit(f"plan practice -> {r.status_code} {r.text[:200]}")
        r = backend.parent.post(f"/practice/{nm}/sets/{set_id}/approve", json={}, headers=backend.parent_headers)
        if r.status_code != 200:
            raise SystemExit(f"approve practice -> {r.status_code}")


def recorded_outcomes(backend, names) -> dict[str, set]:
    out: dict[str, set] = {}
    for nm in names:
        r = backend.parent.get(f"/practice/{nm}/sets", params={"status": "approved"}, headers=backend.parent_headers)
        for s in r.json() if r.status_code == 200 else []:
            out[f"{nm}/{s['id']}"] = {int(k) for k in (s.get("observed_outcomes") or {}) if str(k).isdigit()}
    return out


# ── per-step numbers from the samples ───────────────────────────────────────
def _hist_delta(a: dict, b: dict) -> dict:
    return {k: b.get(k, 0) - a.get(k, 0) for k in b if b.get(k, 0) - a.get(k, 0) > 0}


def api_numbers(samples: list[dict], t0: float, t1: float, mem_limit_mb: float | None, cont: list[dict]) -> dict:
    """One step's API-process numbers from the cumulative snapshots."""
    inside = [s for s in samples if t0 <= s["t"] <= t1]
    before = [s for s in samples if s["t"] < t0]
    if not inside:
        return {"missing": True}
    a, b = (before[-1] if before else inside[0]), inside[-1]
    restarted = any(x.get("pid") != a.get("pid") for x in inside)
    pa, pb = a["pool"], b["pool"]
    co = _hist_delta(pa.get("checkedout_hist", {}), pb.get("checkedout_hist", {}))
    wh = [y - x for x, y in zip(pa["wait_hist"], pb["wait_hist"])]
    edges = WAIT_EDGES
    total = sum(wh)
    p95 = wmax = None
    if total:
        acc = 0
        for i, n in enumerate(wh):
            acc += n
            if p95 is None and acc >= 0.95 * total:
                p95 = edges[i] if i < len(edges) else edges[-1]  # over the last edge: at least this long
            if n:
                wmax = edges[i] if i < len(edges) else edges[-1]
    cpu = []
    for x, y in zip(inside, inside[1:]):
        dt = y["t"] - x["t"]
        if dt > 0 and y.get("pid") == x.get("pid"):
            cpu.append((y["proc"]["cpu_s"] - x["proc"]["cpu_s"]) / dt)
    rss = max(x["proc"].get("vmrss_kb", 0) for x in inside) / 1024
    cont_in = [c for c in cont if t0 <= c["t"] <= t1]
    cmem = max((c["mem_perc"] for c in cont_in), default=None)
    clients = _hist_delta(a.get("clients", {}), b.get("clients", {}))
    minutes = max((t1 - t0) / 60, 1e-9)
    return {
        "rss_mb_max": rss,
        "rss_fraction_of_limit": (cmem / 100) if cmem is not None else (rss / mem_limit_mb if mem_limit_mb else None),
        "cpu_fraction_max": max(cpu) if cpu else None,
        # Sustained use: a one-second spike (a page load, a sign-in) is not saturation.
        "cpu_fraction_p75": rpt.percentile(cpu, 0.75),
        "cpu_fraction_avg": sum(cpu) / len(cpu) if cpu else None,
        "threads_max": max(x["proc"].get("threads", 0) for x in inside),
        "container_pids_max": max((c["pids"] for c in cont_in), default=None),
        "fds_max": max(x["proc"].get("fds", 0) for x in inside),
        "io_read_bytes": b["proc"].get("read_bytes", 0) - a["proc"].get("read_bytes", 0),
        "io_write_bytes": b["proc"].get("write_bytes", 0) - a["proc"].get("write_bytes", 0),
        "pool_size": pb.get("size"), "pool_max_overflow": pb.get("max_overflow"),
        "pool_capacity": (pb.get("size") or 0) + max(pb.get("max_overflow") or 0, 0),
        "pool_checkedout_max": max((int(k) for k in co), default=0),
        "pool_acquisitions": pb["acquisitions"] - pa["acquisitions"],
        "pool_contended": pb["contended"] - pa["contended"],
        "pool_wait_mean_s": (pb["wait_sum_s"] - pa["wait_sum_s"]) / total if total else None,
        "pool_wait_p95_s": p95, "pool_wait_max_s": wmax, "pool_waits_over_30s": wh[-1] if wh else 0,
        "statuses": _hist_delta(a.get("status", {}), b.get("status", {})),
        "rate_limited_by_bucket": _hist_delta(a.get("rate_limited", {}), b.get("rate_limited", {})),
        "clients_observed": len(clients), "busiest_client_per_min": max(clients.values(), default=0) / minutes,
        "transcription": b.get("transcription"),
        "restarted": restarted,
        "settings": b.get("settings"),
    }


def host_numbers(samples, t0, t1) -> dict:
    inside = [s for s in samples if t0 <= s["t"] <= t1]
    cpu = [s["cpu_fraction"] for s in inside if s["cpu_fraction"] is not None]
    return {"cpu_fraction_max": max(cpu, default=None), "cpu_fraction_p75": rpt.percentile(cpu, 0.75),
            "cpu_fraction_avg": sum(cpu) / len(cpu) if cpu else None,
            "mem_fraction_max": max((s["mem_fraction"] for s in inside), default=None),
            "chrome_rss_mb_max": max((s["chrome_rss_mb"] for s in inside), default=None),
            "mem_total_mb": inside[-1]["mem_total_mb"] if inside else None}


def log_errors(text: str, patterns: dict) -> dict:
    return {cls: sum(text.count(p) for p in pats) for cls, pats in patterns.items()}


def stub_numbers(out: Path, t0: float, t1: float, stub_cfg: dict) -> dict:
    """The stub's own call times in this step, against its configured delay."""
    calls = []
    f = out / "stub" / "stub.jsonl"
    if f.exists():
        for line in f.read_text().splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if t0 <= e["t0"] <= t1 and e["kind"] in ("moderation", "other", "safety"):
                calls.append(e["t1"] - e["t0"])
    configured = float(stub_cfg["nonstream_delay_s"].split("-")[-1])
    return {"calls": len(calls), "p95_s": rpt.percentile(calls, 0.95), "configured_s": configured}


def build_step(kind: str, n: int, results: list[dict], learners_used: list[str], backend, sampler, t0, t1,
               cfg: dict, out: Path, mem_limit_mb) -> dict:
    turns = [dict(t, session=r["name"]) for r in results for t in r.get("turns", [])]
    answers = [dict(a, learner=r["name"].split("#")[0]) for r in results for a in r.get("answers", [])]
    per_session = {f"{r['name']}#{i}": sum(1 for t in r.get("turns", []) if t["outcome"] == "ok")
                   for i, r in enumerate(results)}
    rec = recorded_outcomes(backend, sorted(set(learners_used)))
    for a in answers:
        if a.get("set_id") is None and a.get("status") == 200:
            a["status"] = None  # an answer we cannot attribute is not counted as accepted
    step = {
        "kind": kind, "sessions": n, "status": "ran", "t0": t0, "t1": t1,
        "summary": rpt.summarize_turns(turns), "turns_per_session": per_session,
        "duplicated_turns": sum(1 for t in turns if t.get("duplicated")),
        "practice": loadgen.practice_check(answers, rec),
        "session_errors": sorted({e for r in results for e in r.get("errors", [])})[:20],
        "api": api_numbers(sampler.api, t0, t1, mem_limit_mb, sampler.container),
        "host": host_numbers(sampler.host, t0, t1),
        "container": backend.container_state(),
        "storage": backend.storage(),
        "log_errors": log_errors(backend.log_text(t0, t1), cfg["error_patterns"]),
        "stub": stub_numbers(out, t0, t1, cfg["stub"]),
    }
    if not results or all(not r.get("turns") for r in results):
        step["status"] = "error"
        step["error"] = "no session completed sign-in: " + "; ".join(step["session_errors"][:3])
    api = step["api"]
    step["api_restarted"] = api.get("restarted", False)
    if kind == "browser":
        # Every browser session answers one approved practice question.
        step["practice_required"] = n
    step["rate"] = {"busiest_client_per_min": {"api": api.get("busiest_client_per_min", 0)},
                    "limits": {"api": (api.get("settings") or {}).get("rate_limit_api_per_minute")},
                    "refused_by_bucket": api.get("rate_limited_by_bucket", {})}
    return step


# ── the two parts ───────────────────────────────────────────────────────────
def run_browser_step(backend, learners: dict, n: int, cfg: dict, out: Path) -> list[dict]:
    names = list(learners)[:n]
    fix = out / "ctl" / f"browser-fix-{n}.json"
    fix.write_text(json.dumps({"sessions": [{"name": nm, "pin": learners[nm], "ui": backend.ui_url(i)} for i, nm in enumerate(names)],
                               "window_s": cfg["browser"]["window_s"], "think_s": cfg["browser"]["think_s"],
                               "out": str(out / "ctl"), "step": n}))
    env = dict(os.environ, FIX=str(fix))
    r = subprocess.run(["node", str(HERE / "browser_sessions.cjs")], env=env, capture_output=True, text=True,
                       timeout=cfg["browser"]["window_s"] + 600)
    (out / f"browser-step-{n}.log").write_text((r.stdout + r.stderr)[-20000:])
    fix.unlink(missing_ok=True)
    res = out / "ctl" / f"browser-step-{n}.json"
    if r.returncode != 0 or not res.exists():
        raise RuntimeError(f"browser driver exited {r.returncode}")
    data = json.loads(res.read_text())
    res.unlink()
    backend.browser_versions = {"chromium": data.get("chromium"), "playwright": data.get("playwright")}
    return data["sessions"]


def run_api_step(backend, learners: dict, n: int, cfg: dict) -> list[dict]:
    names = list(learners)
    children = []
    for i in range(n):
        nm = names[i % len(names)]
        base, local, verify = backend.child_endpoint(i)
        children.append(loadgen.Child(name=nm, pin=learners[nm], base=base, local_address=local, verify=verify))
    a = cfg["api"]
    res = asyncio.run(loadgen.run_step(children, a["window_s"], a["think_s"], a["practice_every_turns"],
                                       cfg["sse_stall_s"], cfg["turn_timeout_s"]))
    for i, r in enumerate(res):
        r["name"] = f"{r['name']}#{i}"
    return res


def run_part(kind: str, steps: list[int], backend, sampler, learners, cfg, out, mem_limit_mb) -> list[dict]:
    done: list[dict] = []
    fails = 0
    for n in steps:
        if kind == "api" and fails >= cfg.get("stop_after_failing_api_steps", 2):
            done.append({"kind": kind, "sessions": n, "status": "not_run",
                         "error": f"stopped after {fails} failing steps"})
            continue
        log(f"{kind} step: {n} sessions")
        if kind == "browser":
            approve_new_sets(backend, list(learners)[:n])
        time.sleep(cfg.get("settle_s", 5))
        t0 = time.time()
        try:
            results = run_browser_step(backend, learners, n, cfg, out) if kind == "browser" else run_api_step(backend, learners, n, cfg)
        except Exception as exc:  # the step did not run; it is recorded, never passed
            done.append({"kind": kind, "sessions": n, "status": "error", "error": f"{type(exc).__name__}: {exc}"[:300]})
            fails += 1
            continue
        t1 = time.time()
        time.sleep(2)  # one more sample after the window
        used = [r["name"].split("#")[0] for r in results]
        step = build_step(kind, n, results, used, backend, sampler, t0, t1, cfg, out, mem_limit_mb)
        th = cfg["thresholds"]
        prev_base = rpt.baseline_first_token(done + [step])
        v = rpt.step_verdict(step, th, prev_base)
        fails = fails + 1 if not v["passed"] else 0
        log(f"  {n}: {'PASS' if v['passed'] else 'FAIL'} {v['reasons'][:2]}")
        done.append(step)
    return done


# ── the address finding ─────────────────────────────────────────────────────
def address_probe(backend, sampler, n: int = 4) -> dict:
    """What address does the API see for each device? Through each device's
    own relay or local address, and, on the stack, from the runner's own
    loopback through docker's published port (what every device would share
    without the relays). A probe that cannot connect records the error and
    never stops the run."""
    out: dict = {}
    time.sleep(1.2)  # let the seeding requests reach a snapshot first

    def probe(label: str, gets: list) -> None:
        snap = backend.read_metrics() or {}
        errors = []
        for url, local, sni in gets:
            try:
                t = httpx.HTTPTransport(local_address=local, verify=False)
                with httpx.Client(transport=t, timeout=20) as c:
                    c.get(url, extensions={"sni_hostname": sni} if sni else None)
            except httpx.HTTPError as exc:
                errors.append(type(exc).__name__)
        time.sleep(1.2)
        now = backend.read_metrics() or {}
        out[label] = {"devices": len(gets), "observed": sorted(_hist_delta(snap.get("clients", {}), now.get("clients", {}))),
                      "errors": errors}

    k = min(n, getattr(backend, "api_relays", n))
    if k:
        probe("per_device_api_clients", [(backend.child_endpoint(i)[0] + "/health", backend.child_endpoint(i)[1], None)
                                         for i in range(k)])
    b = min(n, getattr(backend, "browser_relays", 0))
    if b:
        probe("per_device_browser_path", [(backend.ui_url(i) + "/api/health", None, None) for i in range(b)])
    if backend.target == "stack":
        probe("published_port_from_loopback",
              [("https://127.0.0.1/api/health", f"127.0.0.{2 + i}", "localhost") for i in range(n)])
        out["published_port_from_loopback"]["note"] = "the runner's own loopback through docker's published port 443"
    return out


def credential_scan(out: Path, secrets_env: dict, pins: list[str]) -> list[dict]:
    import package  # scripts/qualification/package.py's scan
    findings = package.scan(out, secrets_env)
    for f in sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS" and "ctl" not in p.parts):
        text = f.read_text(errors="replace")
        for pin in pins:
            if re.search(rf"(?<!\d){pin}(?!\d)", text):
                findings.append({"file": str(f.relative_to(out)), "kind": "learner-pin"})
    return findings


def parse_steps(s: str | None, default: list[int]) -> list[int]:
    if not s:
        return default
    vals = sorted({int(x) for x in s.split(",") if x.strip()})
    if not vals or any(v < 1 or v > 200 for v in vals):
        raise SystemExit("steps must be integers from 1 to 200")
    return vals


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", required=True)
    ap.add_argument("--target", choices=["local", "stack"], required=True)
    ap.add_argument("--parts", default="browser,api")
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", default=str(HERE / "capacity.json"))
    ap.add_argument("--browser-steps")
    ap.add_argument("--api-steps")
    ap.add_argument("--window-s", type=int, help="overrides both parts' window")
    ap.add_argument("--model", choices=["stub", "ollama"], default="stub")
    ap.add_argument("--db-pool-size", type=int)
    ap.add_argument("--db-max-overflow", type=int)
    ap.add_argument("--rate-limit-api-per-minute", type=int)
    ap.add_argument("--skip-head-check", action="store_true", help="local look at uncommitted work only")
    a = ap.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", a.sha):
        raise SystemExit("--sha must be a 40-character lowercase commit SHA")
    head = sh("git", "-C", str(REPO), "rev-parse", "HEAD").strip()
    if head != a.sha and not a.skip_head_check:
        raise SystemExit(f"checked-out HEAD {head} is not the candidate {a.sha}")
    cfg = json.loads(Path(a.config).read_text())
    parts = {p.strip() for p in a.parts.split(",") if p.strip()}
    if not parts or parts - {"browser", "api"}:
        raise SystemExit("--parts takes browser and/or api")
    bsteps = parse_steps(a.browser_steps, cfg["browser"]["steps"]) if "browser" in parts else []
    asteps = parse_steps(a.api_steps, cfg["api"]["steps"]) if "api" in parts else []
    if bsteps and max(bsteps) > MAX_LEARNERS:
        raise SystemExit(f"browser steps go to {MAX_LEARNERS} at most: one learner per browser, {MAX_LEARNERS} per pod")
    if a.window_s:
        if not 10 <= a.window_s <= 900:
            raise SystemExit("--window-s must be 10..900")
        cfg["browser"]["window_s"] = cfg["api"]["window_s"] = a.window_s
    overrides = {"DB_POOL_SIZE": a.db_pool_size, "DB_MAX_OVERFLOW": a.db_max_overflow,
                 "RATE_LIMIT_API_PER_MINUTE": a.rate_limit_api_per_minute}
    for k, v in overrides.items():
        if v is not None and not 0 <= v <= 10000:
            raise SystemExit(f"{k} out of range")
    out = Path(a.out).resolve()
    (out / "ctl").mkdir(parents=True, exist_ok=True)
    meta = {"sha": a.sha, "target": a.target, "model": a.model, "stub": cfg["stub"], "parts": sorted(parts),
            "reference_seats": cfg["reference"]["family_membership_seats"], "config": cfg,
            "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    report: dict = {"meta": meta}
    if a.model == "ollama":
        # Phase 2 is not built: phase 1 has not yet had a green CI run, and a
        # local model on a shared runner is a separate decision.
        meta.update(layout="not started", non_default=False, client_addresses="not measured")
        report["browser_not_run"] = report["api_not_run"] = "NOT_RUN: the Ollama model run is not built yet (phase 2)"
        rpt.write_evidence(out, report)
        return 0
    browsers, api_children = (max(bsteps) if bsteps else 0), (max(asteps) if asteps else 0)
    backend = (LocalBackend(out, cfg, parts, overrides, browsers, api_children) if a.target == "local"
               else StackBackend(out, cfg, parts, browsers, api_children))
    mem_limit = getattr(backend, "mem_limit_mb", None) or cfg["api_mem_limit_mb"]
    sampler = Sampler(backend)
    sampler.start()
    learners: dict = {}
    try:
        meta["layout"] = backend.layout
        learners = seed(backend, MAX_LEARNERS)
        log(f"seeded {len(learners)} learners")
        meta["client_addresses"] = address_probe(backend, sampler)
        snap = backend.read_metrics() or {}
        settings = snap.get("settings") or {}
        meta["settings"] = settings
        defaults = {"db_pool_size": 20, "db_max_overflow": 20, "rate_limit_api_per_minute": 120}
        meta["non_default"] = sorted(k for k, v in defaults.items() if settings.get(k) not in (None, v))
        time.sleep(61)  # let the probe's requests leave every rate-limit window
        if bsteps:
            steps = run_part("browser", bsteps, backend, sampler, learners, cfg, out, mem_limit)
            report["browser"] = {"steps": steps, "judgement": rpt.judge(steps, cfg["thresholds"], cfg["browser"]["required_sessions"]),
                                 "versions": getattr(backend, "browser_versions", None)}
        else:
            report["browser_not_run"] = "NOT_RUN: browser part not requested"
        if asteps:
            steps = run_part("api", asteps, backend, sampler, learners, cfg, out, mem_limit)
            report["api"] = {"steps": steps, "judgement": rpt.judge(steps, cfg["thresholds"])}
        else:
            report["api_not_run"] = "NOT_RUN: API part not requested"
    finally:
        sampler.halt.set()
        stop(backend.procs)
    pins = list(learners.values())
    secret_env = getattr(backend, "secrets", None) or {"PARENT_PASSWORD": backend.parent_password,
                                                       "SECRET_KEY": backend.env.get("SECRET_KEY", ""),
                                                       "MASTER_SECRET": backend.env.get("MASTER_SECRET", "")}
    shutil.rmtree(out / "ctl", ignore_errors=True)
    for f in out.glob("*.log"):  # service logs can name learners; keep only the tail, scanned below
        f.write_text(f.read_text(errors="replace")[-200000:])
    rpt.write_evidence(out, report)
    findings = credential_scan(out, secret_env, pins)
    if findings:
        for p in out.iterdir():
            if p.is_file():
                p.unlink()
        (out / "CREDENTIAL_SCAN_FAILED.json").write_text(json.dumps(findings, indent=1))
        log(f"FAIL credential scan found {len(findings)} item(s); evidence withheld")
        return 3
    log((out / "report.md").read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
