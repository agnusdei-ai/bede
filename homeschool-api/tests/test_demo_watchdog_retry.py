"""The demo watchdog retries a device once, only for a transient load or
connection failure (scripts/demo_watchdog_run.py).

The end-to-end cases run the REAL script as the workflow does, with a stand-in
journey that writes the report each case needs, so the decision, the files,
the summary and the exit code are all observed rather than assumed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "demo_watchdog_run.py"
WORKFLOW = ROOT / ".github" / "workflows" / "demo-watchdog.yml"
JOURNEY = ROOT / "scripts" / "sample_journey.mjs"

sys.path.insert(0, str(SCRIPT.parent))
import demo_watchdog_run as wd  # noqa: E402

# The report the desktop device produced at 2026-11-18T18:15, reduced to the
# fields the decision reads. The demo was healthy; the connection was reset
# while the main script was loading.
OBSERVED_RESET = {
    "device": "desktop",
    "ok": False,
    "failedStep": "find-button",
    "summary": 'The "Start Bede demo" button never appeared — the app may not have mounted.',
    "cspViolations": [
        "Loading the script 'https://static.cloudflareinsights.com/beacon.min.js/v' violates the "
        "following Content Security Policy directive: \"script-src 'self'\"."
    ],
    "networkFailures": [
        {"url": "https://static.cloudflareinsights.com/beacon.min.js/v", "method": "GET", "failure": "csp"},
        {"url": "https://agnusdei.ai/bede/assets/index-BYHNSYVO.js", "method": "GET",
         "failure": "net::ERR_CONNECTION_RESET"},
    ],
    "requests": [],
}

PASS = {"device": "desktop", "ok": True, "failedStep": None,
        "summary": "A demo session started successfully.", "networkFailures": [], "requests": []}

DETERMINISTIC = {"device": "desktop", "ok": False, "failedStep": "find-button",
                 "summary": "The button never appeared.", "networkFailures": [], "requests": []}


# ── the decision ────────────────────────────────────────────────────────────

def test_the_observed_connection_reset_is_transient():
    assert wd.is_transient(OBSERVED_RESET)


@pytest.mark.parametrize("report", [
    PASS,
    DETERMINISTIC,
    None,
    "not a dict",
    # A failure the page decided, with a transport failure alongside it.
    {**OBSERVED_RESET, "failedStep": "picture-study-csp"},
    # The API answered with a server error: an application error.
    {**OBSERVED_RESET, "requests": [{"url": "https://x.onrender.com/auth/demo-code", "status": 503}]},
    # The policy refused the backend call.
    {**OBSERVED_RESET, "cspViolations": ["Refused to connect ... violates connect-src"]},
    # Only a CORS-shaped failure, which is deterministic.
    {**OBSERVED_RESET, "networkFailures": [{"url": "https://x/", "failure": "net::ERR_FAILED"}]},
    {**OBSERVED_RESET, "networkFailures": [{"url": "https://x/", "failure": "net::ERR_ABORTED"}]},
    # The page loaded with a real error status.
    {"ok": False, "failedStep": "load", "loadStatus": 404},
    {"ok": False, "failedStep": "load", "loadStatus": 500},
    # A load failure from an older journey that recorded no status.
    {"ok": False, "failedStep": "load"},
    # The check itself threw for a reason that is not the network.
    {"ok": False, "failedStep": "exception", "exception": "TypeError: x is undefined"},
], ids=["pass", "assertion", "none", "not-dict", "csp-step", "api-5xx", "connect-src",
        "err-failed", "err-aborted", "load-404", "load-500", "load-unknown", "exception-other"])
def test_nothing_deterministic_is_retried(report):
    assert not wd.is_transient(report)


@pytest.mark.parametrize("report", [
    {"ok": False, "failedStep": "load", "loadStatus": None},
    {"ok": False, "failedStep": "load", "loadStatus": 502},
    {"ok": False, "failedStep": "load", "loadStatus": 522},
    {"ok": False, "failedStep": "exception",
     "exception": "Error: page.goto: net::ERR_CONNECTION_RESET at https://agnusdei.ai/bede/"},
    {"ok": False, "failedStep": "timeout",
     "networkFailures": [{"url": "https://x.onrender.com/auth/login", "failure": "net::ERR_TIMED_OUT"}]},
], ids=["no-response", "502", "522", "goto-reset", "api-timeout"])
def test_transient_load_and_connection_failures_are_retried(report):
    assert wd.is_transient(report)


def test_the_retry_waits_thirty_seconds_by_default(tmp_path):
    waits = []
    fake = _fake_journey(tmp_path, {"desktop": [OBSERVED_RESET, PASS]})
    result = wd.check_device(fake, "https://example.invalid/", "desktop", tmp_path,
                             wd.RETRY_DELAY_SECONDS, sleep=waits.append)
    assert waits == [30]
    assert result["outcome"] == "passed_on_retry"


# ── end to end, through the real script ───────────────────────────────────

def _fake_journey(tmp_path: Path, plan: dict[str, list]) -> list[str]:
    """A journey that emits the next planned report for its device, exits 0
    for ok, and records each call. `None` in a plan prints nothing and exits
    1, as a crashed journey would."""
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    script = tmp_path / "fake_journey.py"
    script.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        f"base = Path({str(tmp_path)!r})\n"
        "dev = os.environ['DEVICE_PROFILE']\n"
        "calls = base / ('calls-' + dev)\n"
        "n = int(calls.read_text()) if calls.exists() else 0\n"
        "calls.write_text(str(n + 1))\n"
        "report = json.loads((base / 'plan.json').read_text())[dev][n]\n"
        "if report is None:\n"
        "    sys.exit(1)\n"
        "print(json.dumps(report))\n"
        "sys.exit(0 if report.get('ok') else 1)\n"
    )
    return [sys.executable, str(script)]


def _run(tmp_path: Path, plan: dict[str, list]) -> tuple[subprocess.CompletedProcess, str]:
    work = tmp_path / "work"
    work.mkdir()
    summary = tmp_path / "summary.md"
    cmd = _fake_journey(tmp_path, plan)
    env = {**os.environ, "DEMO_URL": "https://example.invalid/bede/",
           "JOURNEY_CMD": " ".join(cmd), "RETRY_DELAY_SECONDS": "0",
           "WATCHDOG_DEVICES": " ".join(plan), "GITHUB_STEP_SUMMARY": str(summary)}
    proc = subprocess.run([sys.executable, str(SCRIPT)], cwd=work, env=env,
                          capture_output=True, text=True, timeout=60)
    return proc, summary.read_text() if summary.exists() else ""


def _calls(tmp_path: Path, device: str) -> int:
    path = tmp_path / f"calls-{device}"
    return int(path.read_text()) if path.exists() else 0


def test_a_recovered_device_passes_on_retry_and_keeps_both_attempts(tmp_path):
    proc, summary = _run(tmp_path, {"desktop": [OBSERVED_RESET, PASS]})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _calls(tmp_path, "desktop") == 2
    assert "passed on retry" in summary
    assert "Attempt 1 (failed" in summary and "Attempt 2 (passed" in summary
    work = tmp_path / "work"
    assert json.loads((work / "journey-report-desktop.attempt-1.json").read_text())["ok"] is False
    assert json.loads((work / "journey-report-desktop.json").read_text())["ok"] is True


def test_a_retry_that_fails_fails_the_run_in_the_same_run(tmp_path):
    proc, summary = _run(tmp_path, {"desktop": [OBSERVED_RESET, OBSERVED_RESET]})
    assert proc.returncode == 1
    assert _calls(tmp_path, "desktop") == 2
    assert "the demo is broken (failed again on retry)" in summary


def test_a_deterministic_failure_is_reported_at_once_without_a_retry(tmp_path):
    proc, summary = _run(tmp_path, {"desktop": [DETERMINISTIC, PASS]})
    assert proc.returncode == 1
    assert _calls(tmp_path, "desktop") == 1
    assert "**Result:** ❌ the demo is broken\n" in summary
    assert not (tmp_path / "work" / "journey-report-desktop.attempt-1.json").exists()


def test_an_application_error_is_not_retried(tmp_path):
    api_error = {**OBSERVED_RESET,
                 "requests": [{"url": "https://x.onrender.com/auth/demo-code", "status": 503}]}
    proc, _ = _run(tmp_path, {"desktop": [api_error, PASS]})
    assert proc.returncode == 1
    assert _calls(tmp_path, "desktop") == 1


def test_a_journey_that_left_no_report_is_not_retried(tmp_path):
    proc, summary = _run(tmp_path, {"desktop": [None, PASS]})
    assert proc.returncode == 1
    assert _calls(tmp_path, "desktop") == 1
    assert "no readable report" in summary


def test_one_device_failing_never_stops_the_others(tmp_path):
    plan = {"desktop": [DETERMINISTIC], "galaxy-a10": [OBSERVED_RESET, PASS],
            "android-tablet": [PASS]}
    proc, summary = _run(tmp_path, plan)
    assert proc.returncode == 1
    assert [_calls(tmp_path, d) for d in plan] == [1, 2, 1]
    assert summary.count("### Demo watchdog") == 3
    assert "passed on retry" in summary


def test_a_clean_run_is_unchanged(tmp_path):
    proc, summary = _run(tmp_path, {"desktop": [PASS]})
    assert proc.returncode == 0
    assert _calls(tmp_path, "desktop") == 1
    assert "**Result:** ✅ the demo works" in summary


def test_the_script_refuses_to_run_without_a_target(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "DEMO_URL"}
    proc = subprocess.run([sys.executable, str(SCRIPT)], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 2


# ── the invocation ─────────────────────────────────────────────────────────

def _check_steps() -> list[dict]:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["check"]["steps"]


def test_the_workflow_runs_the_retrying_runner():
    step = next(s for s in _check_steps() if s.get("id") == "journey")
    assert step["run"].strip() == "python3 scripts/demo_watchdog_run.py"
    assert "DEMO_URL" in step["env"]


def test_the_artifact_still_collects_every_attempt():
    upload = next(s for s in _check_steps() if "upload-artifact" in str(s.get("uses")))
    assert upload["with"]["path"] == "journey-report-*.json"
    assert upload.get("if") == "always()"


def test_the_runner_defaults_to_the_real_journey():
    text = SCRIPT.read_text()
    assert '"node scripts/sample_journey.mjs"' in text
    assert set(wd.DEVICES) == {"desktop", "galaxy-a10", "android-tablet"}


def test_the_journey_records_the_fields_the_decision_reads():
    text = JOURNEY.read_text()
    assert "report.loadStatus = res ? res.status() : null;" in text
    assert "report.exception = `${err?.name}: ${err?.message}`;" in text
