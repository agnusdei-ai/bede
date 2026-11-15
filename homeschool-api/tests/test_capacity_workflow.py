"""The capacity workflow is report-only, read-only and pinned, and the pieces it
runs are wired to each other and to the real app.

`.github/workflows/capacity.yml` boots the real stack and drives real browsers
against it, so its shape is pinned here as for the other qualification
workflows: dispatch only, read-only token, a pinned runner, no secrets, every
free-text input reaching a script only through env:, and actions pinned to
reviewed SHAs. The rest proves the invocations rather than the functions
alone: the instrumented API really serves the app with the Dockerfile's flags
and really records client addresses and the pool, the relay really changes the
source address, the browser part really reuses the journeys' child steps
rather than a copy, and the change filter really covers these files. Each
guard was verified by breaking it (see the PR).
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "homeschool-api"
WF = ROOT / ".github" / "workflows" / "capacity.yml"
CAP = ROOT / "scripts" / "qualification" / "capacity"
JOURNEYS = ROOT / "scripts" / "qualification" / "browser_journeys"


def _wf() -> dict:
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def _on(data: dict) -> dict:
    # PyYAML reads the bare key `on` as the boolean True.
    return data.get("on", data.get(True))


# ── the workflow's shape ────────────────────────────────────────────────────
def test_dispatch_only():
    assert set(_on(_wf())) == {"workflow_dispatch"}


def test_read_only_token_and_no_job_widens_it():
    data = _wf()
    assert data["permissions"] == {"contents": "read"}
    assert all("permissions" not in job for job in data["jobs"].values())


def test_runner_is_pinned():
    for job in _wf()["jobs"].values():
        assert job["runs-on"] == "ubuntu-24.04"


def test_no_secrets_are_used():
    assert "secrets." not in WF.read_text(encoding="utf-8")


def test_free_text_reaches_scripts_only_through_env():
    for job in _wf()["jobs"].values():
        for st in job["steps"]:
            assert "${{" not in st.get("run", ""), st.get("name")


def test_inputs_cover_the_brief_and_candidate_sha_is_required():
    inputs = _on(_wf())["workflow_dispatch"]["inputs"]
    assert inputs["candidate_sha"]["required"] is True
    for name in ("browser_steps", "api_steps", "window_seconds", "model", "db_pool_size", "db_max_overflow",
                 "rate_limit_api_per_minute"):
        assert name in inputs
    assert inputs["model"]["options"] == ["stub", "ollama"]


def test_inputs_are_validated_before_anything_runs():
    steps = _wf()["jobs"]["capacity"]["steps"]
    first = steps[0]
    assert first["name"] == "Validate inputs"
    for needle in ("^[0-9a-f]{40}$", "DB_POOL_SIZE_INPUT", "DB_MAX_OVERFLOW_INPUT", "RATE_LIMIT_API_INPUT", "WINDOW_SECONDS"):
        assert needle in first["run"]


def test_actions_are_pinned_to_shas_already_reviewed_elsewhere():
    used = {st["uses"] for job in _wf()["jobs"].values() for st in job["steps"] if "uses" in st}
    others = "".join(p.read_text(encoding="utf-8") for p in (ROOT / ".github" / "workflows").glob("*.yml") if p != WF)
    for u in used:
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", u), u
        assert u in others, f"{u} is not used by any other workflow"


def test_the_workflow_runs_the_capacity_steps_and_uploads_the_evidence():
    text = WF.read_text(encoding="utf-8")
    assert "scripts/qualification/capacity/run_capacity.py" in text
    assert "scripts/qualification/capacity/docker-compose.capacity.yml" in text
    assert "${{ runner.temp }}/bede-capacity/" in text


def test_the_change_filter_covers_the_capacity_files():
    """scripts/qualification/ is in test.yml's grep filter; prove it with the
    filter's own regex against each file, not by searching for a substring."""
    test_yml = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    line = next(l for l in test_yml.splitlines() if "grep -qE" in l and "^(" in l)
    pattern = re.compile(re.search(r"grep -qE '([^']+)'", line).group(1))
    files = [p.relative_to(ROOT).as_posix() for p in CAP.iterdir() if p.is_file()]
    files += [".github/workflows/capacity.yml", "scripts/qualification/browser_journeys/child_steps.cjs"]
    assert files
    for f in files:
        assert pattern.match(f), f
    push = yaml.safe_load(test_yml)
    assert "scripts/qualification/**" in _on(push)["push"]["paths"]


# ── the instrumented API is the real API with the image's flags ────────────
def test_the_launcher_uses_the_dockerfile_cmd_flags():
    cmd = (API_DIR / "Dockerfile").read_text(encoding="utf-8")
    cmd = next(l for l in cmd.splitlines() if l.startswith("CMD"))
    for flag in ('"--workers", "1"', '"--proxy-headers"', '"--forwarded-allow-ips=*"', '"--timeout-graceful-shutdown", "120"'):
        assert flag in cmd, f"the Dockerfile CMD changed ({flag}); update instrumented_api.py to match"
    src = (CAP / "instrumented_api.py").read_text(encoding="utf-8")
    for kw in ("workers=1", "proxy_headers=True", "timeout_graceful_shutdown=120", "import main as bede"):
        assert kw in src
    override = yaml.safe_load((CAP / "docker-compose.capacity.yml").read_text(encoding="utf-8"))
    command = override["services"]["api"]["command"]
    assert command[-2:] == ["--forwarded-allow-ips", "*"]
    assert set(override["services"]) == {"api"}, "the override must change nothing but the api command"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_instrumented_api_serves_the_app_and_records_what_it_saw(tmp_path):
    """Boots instrumented_api.py with the real lifespan on SQLite, sends
    requests from two loopback addresses, and reads its snapshot: both
    addresses, the statuses, the pool (with the configured size) and the
    settings the process actually runs with."""
    port = _free_port()
    metrics = tmp_path / "m.json"
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    env.update(DATABASE_URL="sqlite+aiosqlite:///" + (tmp_path / "c.db").as_posix(), PRODUCTION="false",
               SECRET_KEY="x" * 40, MASTER_SECRET="y" * 40, PARENT_PASSWORD="sample-password-1", CHILD_PIN="739184",
               LOCAL_LLM_BASE_URL="http://127.0.0.1:9/v1", BEDE_FORCE_ADAPTER="local", CAPACITY_METRICS_PATH=str(metrics),
               DB_POOL_SIZE="7", DB_MAX_OVERFLOW="2", EDUCATOR_PILOT_ENABLED="false")
    proc = subprocess.Popen([sys.executable, str(CAP / "instrumented_api.py"), "--port", str(port)], cwd=API_DIR,
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.3)
        else:
            raise AssertionError(proc.stdout.read1().decode(errors="replace")[-3000:] if proc.stdout else "no output")
        for src in ("127.0.0.31", "127.0.0.32"):
            t = httpx.HTTPTransport(local_address=src)
            with httpx.Client(transport=t) as c:
                assert c.post(f"http://127.0.0.1:{port}/auth/login", json={"role": "parent", "credential": "sample-password-1"}).status_code == 200
        time.sleep(1.5)
        snap = json.loads(metrics.read_text())
        assert {"127.0.0.31", "127.0.0.32"} <= set(snap["clients"])
        assert snap["status"].get("200", 0) >= 2
        assert snap["pool"]["size"] == 7 and snap["pool"]["max_overflow"] == 2
        assert snap["pool"]["acquisitions"] >= 1
        assert snap["settings"]["db_pool_size"] == 7
        assert snap["proc"]["threads"] >= 1 and snap["proc"]["fds"] >= 1
    finally:
        proc.terminate()
        proc.wait(timeout=30)


# ── the relay really changes the source address ────────────────────────────
def test_the_relay_gives_each_device_its_own_source_address():
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.client_address[0])
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    up = srv.server_address[1]
    p1, p2 = _free_port(), _free_port()
    relay = subprocess.Popen([sys.executable, str(CAP / "relay.py"),
                              "--spec", f"127.0.0.1:{p1}=127.0.0.41>127.0.0.1:{up}",
                              "--spec", f"127.0.0.1:{p2}=127.0.0.42>127.0.0.1:{up}"],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        assert b"relay ready" in relay.stdout.readline()
        assert httpx.get(f"http://127.0.0.1:{p1}/").status_code == 200
        assert httpx.get(f"http://127.0.0.1:{p2}/").status_code == 200
        assert seen == ["127.0.0.41", "127.0.0.42"]
    finally:
        relay.terminate()
        relay.wait(timeout=10)
        srv.shutdown()


# ── the browser part reuses the journeys' child steps ───────────────────────
def test_the_child_steps_live_in_one_place():
    shared = JOURNEYS / "child_steps.cjs"
    assert "async function childLogin" in shared.read_text(encoding="utf-8")
    assert "require('../browser_journeys/child_steps.cjs')" in (CAP / "browser_sessions.cjs").read_text(encoding="utf-8")
    assert "require('./child_steps.cjs')(F)" in (JOURNEYS / "journeys.cjs").read_text(encoding="utf-8")
    copies = [p for p in (ROOT / "scripts" / "qualification").rglob("*.cjs")
              if p != shared and re.search(r"async function (childLogin|sendChat)\b", p.read_text(encoding="utf-8"))]
    assert not copies, copies


@pytest.mark.skipif(not __import__("shutil").which("node"), reason="node not installed")
def test_the_shared_child_steps_load_and_export_what_both_callers_use():
    out = subprocess.run(["node", "-e", "const s=require(process.argv[1])({ui:'x',learners:{}});"
                          "console.log(Object.keys(s).sort().join(','))", str(JOURNEYS / "child_steps.cjs")],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "childLogin,inputReady,passIntro,replies,sendChat,stillInLesson"


def test_the_stack_env_boots_licensed_and_passes_production_validation(tmp_path, monkeypatch):
    """stack_env.py's licence verifies under the checkout it rewrites, and the
    .env it writes, plus the two values compose hard-codes, is a valid
    production configuration, so the stack boots licensed rather than gated
    or refusing to start. Run against a COPY of core/licensing.py."""
    import importlib.util
    sys.path.insert(0, str(CAP))
    import stack_env
    lic = tmp_path / "licensing.py"
    lic.write_text((API_DIR / "core" / "licensing.py").read_text(encoding="utf-8"), encoding="utf-8")
    key = stack_env.mint_license(lic)
    spec = importlib.util.spec_from_file_location("capacity_licensing_copy", lic)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    info = mod.verify_license(key)
    assert info.tier == "trial" and info.seats == 10 and not info.is_expired
    lines = stack_env.env_lines("http://host.docker.internal:18411/v1", key,
                                {"DB_POOL_SIZE": 20, "DB_MAX_OVERFLOW": None, "RATE_LIMIT_API_PER_MINUTE": None})
    env = dict(line.split("=", 1) for line in lines)
    assert env["DB_POOL_SIZE"] == "20" and "DB_MAX_OVERFLOW" not in env, "an unset override must stay the default"
    from core.config import Settings
    for k in list(os.environ):
        if k.endswith("_API_KEY"):
            monkeypatch.delenv(k, raising=False)
    fields = {k.lower(): v for k, v in env.items() if k.lower() in Settings.model_fields}
    s = Settings(_env_file=None, production="true", disable_api_docs="true", **fields)
    assert s.db_pool_size == 20 and s.local_llm_base_url.endswith("/v1")


def test_the_stub_delays_are_settable_and_default_to_the_journeys_values(tmp_path):
    """The capacity run fixes the stub's delays; the journeys keep theirs."""
    src = (JOURNEYS / "model_stub.py").read_text(encoding="utf-8")
    for name, default in (("STUB_NONSTREAM_DELAY_S", "0.5-3.0"), ("STUB_FIRST_TOKEN_DELAY_S", "0.4-1.2"),
                          ("STUB_CHUNK_DELAY_S", "0.05-0.2")):
        assert f'_range("{name}", "{default}")' in src
    port = _free_port()
    env = dict(os.environ, STUB_NONSTREAM_DELAY_S="0.0-0.0")
    proc = subprocess.Popen([sys.executable, str(JOURNEYS / "model_stub.py"), str(port), str(tmp_path)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        t0 = time.monotonic()
        r = httpx.post(f"http://127.0.0.1:{port}/v1/chat/completions", timeout=10,
                       json={"messages": [{"role": "system", "content": '"flagged"'}, {"role": "user", "content": "hi"}]})
        assert r.status_code == 200 and time.monotonic() - t0 < 0.4  # the default would wait at least 0.5 s
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_the_ten_session_point_is_stated_in_the_config():
    cfg = json.loads((CAP / "capacity.json").read_text(encoding="utf-8"))
    assert cfg["browser"]["required_sessions"] == 10
    assert cfg["browser"]["steps"][-1] == 10
    th = cfg["thresholds"]
    assert th["max_5xx"] == 0 and th["max_dropped_turns"] == 0 and th["max_duplicated_turns"] == 0
    assert th["allow_oom_or_restart"] is False
    # The reference line is a copy of the Family Membership's seat count;
    # checked against the licence server's own entitlement, not retyped.
    ent = (ROOT / "license-server" / "src" / "license" / "entitlements.ts").read_text(encoding="utf-8")
    block = ent[ent.index("export const ANNUAL_FAMILY_ENTITLEMENT"):]
    assert cfg["reference"]["family_membership_seats"] == int(re.search(r"seats: (\d+)", block).group(1))
