"""The API must run as exactly one process.

Voice stream sessions, the demo diagnostic store, Practice Coach progress,
the rate limiter and the anomaly window all live in in-memory dicts. uvicorn
reads its worker count from WEB_CONCURRENCY when --workers is not given, so
a host that sets that variable splits them across processes. On 2026-11-10 a
phone on the public demo saw voice sessions answer "unknown or expired
session" on their own next request, under one instance id. The Dockerfile's
CMD pins one worker; this fails if that pin goes.
"""
import json
import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def _cmd() -> list[str]:
    lines = [l for l in DOCKERFILE.read_text().splitlines() if l.startswith("CMD ")]
    assert len(lines) == 1, lines
    return json.loads(lines[0][4:])


def test_the_api_runs_exactly_one_worker_process():
    cmd = _cmd()
    assert cmd[0] == "uvicorn"
    assert "--workers" in cmd, cmd
    assert cmd[cmd.index("--workers") + 1] == "1", cmd


def test_no_other_worker_setting_overrides_it():
    text = DOCKERFILE.read_text()
    assert not re.search(r"^\s*ENV\s+WEB_CONCURRENCY", text, re.M)
    assert "gunicorn" not in " ".join(_cmd())
