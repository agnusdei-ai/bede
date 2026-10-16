"""Process, browser and HTTP plumbing shared by the qualification steps.

  * ``Stack``   — the AI stub and the REAL ``uvicorn main:app`` process (real
                  lifespan), started and stopped with SIGTERM like a service
                  manager would.
  * ``Driver``  — the Chromium virtual-authenticator process
                  (webauthn_driver.cjs), one browser context per principal.
  * ``Api``     — an httpx client that presents the SAME User-Agent as the
                  browser, so a token issued to the browser's ceremony is the
                  token the API client carries (JWTs are IP+UA fingerprinted).

Nothing here talks to the database. The one exception anywhere in the
harness is the documented ``minted_token`` fallback in seed.py.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qualconfig as cfg  # noqa: E402

HERE = Path(__file__).resolve().parent


class HarnessError(RuntimeError):
    pass


# ── Processes ────────────────────────────────────────────────────────────────

def make_tls(tmp: Path) -> dict:
    """A self-signed certificate for this run only (localhost + 127.0.0.1),
    plus the base64 SHA-256 of its public key, which Chromium is told to
    trust by --ignore-certificate-errors-spki-list. Lives in the run's temp
    directory; never in the evidence directory."""
    tmp.mkdir(parents=True, exist_ok=True)
    key, cert = tmp / "tls-key.pem", tmp / "tls-cert.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                    "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "1",
                    "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"],
                   check=True, capture_output=True)
    pub = subprocess.run(["openssl", "x509", "-pubkey", "-noout", "-in", str(cert)],
                         check=True, capture_output=True).stdout
    der = subprocess.run(["openssl", "pkey", "-pubin", "-outform", "der"], input=pub,
                         check=True, capture_output=True).stdout
    import base64
    import hashlib
    return {"key": str(key), "cert": str(cert),
            "spki": base64.b64encode(hashlib.sha256(der).digest()).decode()}


@dataclass
class Stack:
    env: dict
    out: Path
    server: subprocess.Popen | None = None
    stub: subprocess.Popen | None = None
    sink: subprocess.Popen | None = None
    tls: dict = field(default_factory=dict)
    starts: int = 0
    events: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if cfg.TLS and not self.tls:
            self.tls = make_tls(cfg.RUN_TMP / "tls")

    @property
    def base(self) -> str:
        return f"{'https' if cfg.TLS else 'http'}://{cfg.API_HOST}:{cfg.API_PORT}"

    @property
    def verify(self):
        return self.tls.get("cert", True) if cfg.TLS else True

    def start_stub(self) -> None:
        log = (self.out / "ai-stub.log").open("ab")
        self.stub = subprocess.Popen(
            [sys.executable, str(HERE / "ai_stub.py"), "--host", cfg.STUB_HOST,
             "--port", str(cfg.STUB_PORT), "--log", str(self.out / "ai-stub-requests.jsonl")],
            stdout=log, stderr=subprocess.STDOUT)
        self._wait(f"http://{cfg.STUB_HOST}:{cfg.STUB_PORT}/v1/models", "ai stub")

    def start_sink(self) -> None:
        """Start the loopback mail sink only when the application is pointed
        at it (RESEND_API_BASE_URL)."""
        if not self.env.get("RESEND_API_BASE_URL"):
            return
        log = (self.out / "mail-sink.log").open("ab")
        env = dict(os.environ, QUAL_MAIL_SINK_KEY=self.env.get("RESEND_API_KEY", ""))
        self.sink = subprocess.Popen(
            [sys.executable, str(HERE / "mail_sink.py"), "--host", cfg.MAIL_SINK_HOST,
             "--port", str(cfg.MAIL_SINK_PORT), "--store", str(cfg.MAIL_SINK_DIR),
             "--log", str(self.out / "mail-sink-messages.jsonl"),
             "--domain", cfg.INSTITUTION_EMAIL_DOMAIN],
            stdout=log, stderr=subprocess.STDOUT, env=env)
        self._wait(f"http://{cfg.MAIL_SINK_HOST}:{cfg.MAIL_SINK_PORT}/health", "mail sink", proc=self.sink)

    def start_server(self) -> None:
        self.starts += 1
        log = (self.out / "server.log").open("ab")
        log.write(f"\n=== server start #{self.starts} at {time.time():.3f} ===\n".encode())
        log.flush()
        tls = ["--ssl-keyfile", self.tls["key"], "--ssl-certfile", self.tls["cert"]] if cfg.TLS else []
        self.server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", cfg.API_HOST,
             "--port", str(cfg.API_PORT), "--workers", "1", "--no-access-log", *tls],
            cwd=cfg.API_DIR, env=self.env, stdout=log, stderr=subprocess.STDOUT)
        self._wait(self.base + "/health", "uvicorn main:app", proc=self.server)
        self.events.append({"event": "server_started", "n": self.starts, "pid": self.server.pid,
                            "tls": cfg.TLS})

    def stop_server(self, sig: int = signal.SIGTERM) -> int | None:
        """Stop with SIGTERM (graceful lifespan shutdown) and wait."""
        if not self.server:
            return None
        self.server.send_signal(sig)
        try:
            code = self.server.wait(timeout=cfg.SHUTDOWN_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            self.server.kill()
            code = self.server.wait()
            self.events.append({"event": "server_kill_after_timeout"})
        self.events.append({"event": "server_stopped", "signal": int(sig), "exit": code})
        self.server = None
        return code

    def restart_server(self) -> dict:
        exit_code = self.stop_server(signal.SIGTERM)
        self.start_server()
        return {"sigterm_exit": exit_code, "relaunch": self.starts}

    def stop_all(self) -> None:
        self.stop_server()
        for proc in (self.stub, self.sink):
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self.stub = self.sink = None

    def _wait(self, url: str, what: str, proc: subprocess.Popen | None = None) -> None:
        deadline = time.time() + cfg.STARTUP_TIMEOUT_S
        while time.time() < deadline:
            if proc is not None and proc.poll() is not None:
                raise HarnessError(f"{what} exited during startup (code {proc.returncode}); see logs")
            try:
                if httpx.get(url, timeout=2, verify=self.verify).status_code < 500:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise HarnessError(f"{what} did not become ready within {cfg.STARTUP_TIMEOUT_S}s")


# ── Browser ──────────────────────────────────────────────────────────────────

class Driver:
    """JSON-lines client for webauthn_driver.cjs."""

    def __init__(self, origin: str, out: Path, spki: str = "") -> None:
        self.log = (out / "browser-driver.log").open("ab")
        self.proc = subprocess.Popen(
            ["node", str(HERE / "webauthn_driver.cjs"), origin],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
            text=True, bufsize=1, env=dict(os.environ, QUAL_TLS_SPKI=spki))
        self._n = 0

    def call(self, **msg) -> dict:
        self._n += 1
        msg["id"] = self._n
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise HarnessError("browser driver exited; see browser-driver.log")
        reply = json.loads(line)
        if not reply.get("ok"):
            raise HarnessError(f"browser {msg.get('op')} failed: {reply.get('error')}")
        return reply

    def user_agent(self, ctx: str) -> str:
        return self.call(op="context", ctx=ctx)["userAgent"]

    def create(self, ctx: str, public_key: dict) -> dict:
        return self.call(op="create", ctx=ctx, publicKey=public_key)["credential"]

    def get(self, ctx: str, public_key: dict) -> dict:
        return self.call(op="get", ctx=ctx, publicKey=public_key)["credential"]

    def fetch(self, ctx: str, method: str, path: str, token: str | None = None,
              body: dict | None = None) -> tuple[int, str]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        r = self.call(op="fetch", ctx=ctx, method=method, path=path, headers=headers,
                      body=json.dumps(body) if body is not None else None)
        return r["status"], r["text"]

    def close(self) -> None:
        try:
            self.call(op="close")
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


# ── HTTP ─────────────────────────────────────────────────────────────────────

class Api:
    def __init__(self, base: str, user_agent: str, verify=True) -> None:
        self.base = base
        self.ua = user_agent
        self.verify = verify
        self.client = httpx.Client(base_url=base, timeout=cfg.REQUEST_TIMEOUT_S, verify=verify,
                                   headers={"User-Agent": user_agent})

    def call(self, method: str, path: str, token: str | None = None,
             body: dict | None = None, files: dict | None = None) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.request(method, path, headers=headers,
                                   json=body if files is None else None, files=files)

    def close(self) -> None:
        self.client.close()


def load_route_table(out: Path) -> set[tuple[str, str]]:
    """The candidate's real route table, written by preflight from
    ``main.app.routes`` at the same SHA. Read from the app object rather
    than /openapi.json so the run can keep DISABLE_API_DOCS=true like
    production."""
    path = out / "routes.json"
    if not path.exists():
        raise HarnessError("routes.json missing: run preflight first")
    return {(m, p) for m, p in json.loads(path.read_text())}


def route_present(routes: set[tuple[str, str]], method: str, template: str) -> bool:
    return (method.upper(), template) in routes
