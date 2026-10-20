#!/usr/bin/env python3
"""Campus-scoped native process supervisor. No shell, Docker, or remote listener."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request

IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
ROOT = Path.home() / "Library" / "Application Support" / "Bede" / "Native" / "Campus"

def campus_path(identifier):
    if not IDENTIFIER.fullmatch(identifier):
        raise ValueError("invalid campus identifier")
    path = ROOT / identifier
    if path.is_symlink():
        raise ValueError("campus symlink refused")
    return path

def record(path, identifier):
    if (path / "campus.json").is_symlink():
        raise ValueError("campus metadata symlink refused")
    value = json.loads((path / "campus.json").read_text())
    if value.get("campusID") != identifier or value.get("architecture") != "native-macos":
        raise ValueError("invalid campus record")
    return value

def live(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False

def start(path, identifier, payload, port):
    record(path, identifier)
    if not (1024 <= port <= 65535):
        raise ValueError("invalid port")
    pidfile = path / "native-service.json"
    if pidfile.is_symlink():
        raise ValueError("process-state symlink refused")
    if pidfile.exists():
        old = json.loads(pidfile.read_text())
        if live(old["pid"]):
            raise ValueError("service already running")
        pidfile.unlink()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError("native service port unavailable") from exc
    executable = payload.resolve() / "bin" / "bede-native-smoke"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("native executable missing")
    logs = path / "logs"
    if logs.is_symlink() or (logs / "native-service.log").is_symlink():
        raise ValueError("service log symlink refused")
    logs.mkdir(mode=0o700, exist_ok=True)
    with (logs / "native-service.log").open("ab") as output:
        proc = subprocess.Popen([str(executable)], stdin=subprocess.DEVNULL,
                                stdout=output, stderr=output, start_new_session=True,
                                env={**os.environ, "BEDE_SYNTHETIC_ONLY": "1",
                                     "BEDE_NATIVE_PORT": str(port)})
    started_at = subprocess.run(["/bin/ps", "-p", str(proc.pid), "-o", "lstart="],
                                capture_output=True, text=True, check=False).stdout.strip()
    if not started_at:
        proc.terminate()
        proc.wait(timeout=3)
        raise RuntimeError("cannot verify process start identity")
    state = {"pid": proc.pid, "port": port, "executable": str(executable),
             "started_at": started_at}
    pidfile.write_text(json.dumps(state))
    pidfile.chmod(0o600)
    try:
        for _ in range(30):
            if proc.poll() is not None:
                raise RuntimeError("native service exited during startup")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as response:
                    health = json.load(response)
                if health.get("status") == "synthetic-only":
                    return {"running": True, "pid": proc.pid, "health": health}
            except (OSError, ValueError):
                time.sleep(0.2)
        raise RuntimeError("native health check timed out")
    except Exception:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
        pidfile.unlink(missing_ok=True)
        raise

def stop(path, identifier):
    record(path, identifier)
    pidfile = path / "native-service.json"
    if pidfile.is_symlink():
        raise ValueError("process-state symlink refused")
    if not pidfile.exists():
        return {"running": False}
    state = json.loads(pidfile.read_text())
    pid = state["pid"]
    # Verify process identity before signaling to avoid PID-reuse termination.
    command = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "command="],
                             capture_output=True, text=True, check=False).stdout.strip()
    if not command:
        pidfile.unlink()
        return {"running": False}
    started_at = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "lstart="],
                                capture_output=True, text=True, check=False).stdout.strip()
    if command.split()[0] != state["executable"] or not started_at or started_at != state.get("started_at"):
        raise RuntimeError("process identity changed; refusing to signal")
    os.kill(pid, signal.SIGTERM)
    for _ in range(30):
        if not live(pid):
            pidfile.unlink()
            return {"running": False}
        time.sleep(0.1)
    raise RuntimeError("process did not exit; manual intervention required")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "stop", "status", "recover"))
    parser.add_argument("campus")
    parser.add_argument("--payload", type=Path)
    parser.add_argument("--port", type=int, default=18743)
    args = parser.parse_args()
    path = campus_path(args.campus)
    if not path.is_dir():
        raise ValueError("campus not provisioned")
    if args.action in ("start", "recover") and not args.payload:
        parser.error("--payload required")
    if args.action == "start":
        result = start(path, args.campus, args.payload, args.port)
    elif args.action == "stop":
        result = stop(path, args.campus)
    elif args.action == "recover":
        stop(path, args.campus)
        result = start(path, args.campus, args.payload, args.port)
    else:
        record(path, args.campus)
        pidfile = path / "native-service.json"
        state = json.loads(pidfile.read_text()) if pidfile.exists() else {}
        result = {"running": bool(state and live(state["pid"])), "pid": state.get("pid")}
    print(json.dumps(result))

if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"BEDE_NATIVE_ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
