#!/usr/bin/env python3
"""Run the demo watchdog's sample journey on every device, retrying a device
once only when its failure is a transient load or connection failure.

Called by .github/workflows/demo-watchdog.yml. Standard library only.

Why a retry, and why such a narrow one. The watchdog runs every 30 minutes,
and on 2026-11-18 at 18:15 one device failed because the connection was reset
while its browser was loading the demo's main script
(`net::ERR_CONNECTION_RESET` on `/bede/assets/index-*.js`). The other two
devices passed seconds later, as did every run after it. One dropped
connection on the runner's side emailed the owner that the demo was broken.

The rule:

* A device is retried at most once, after RETRY_DELAY_SECONDS (30).
* It is retried only when its report shows a transient load or connection
  failure (`is_transient`): the page answered with a gateway error or not at
  all, or a request failed at the transport level (a reset, a timeout, a
  failed name lookup), and nothing in the report points at a deterministic
  cause. A failed assertion, a page error with no transport failure, a policy
  refusal, a server error from the API, or an unreadable report is never
  retried.
* A retry that passes is labelled "passed on retry", and both attempts are in
  the summary and the uploaded artifact. A retry that fails fails the run, in
  the same run, so a real outage is still reported within one tick.

Nothing here makes a failing demo pass. A device is green only if one full
journey succeeded; the retry can only turn a one-off network drop into a
second, real observation.

Usage:
  DEMO_URL=https://agnusdei.ai/bede/ python3 scripts/demo_watchdog_run.py

Environment:
  DEMO_URL              the demo to check (required)
  JOURNEY_CMD           the journey command (default: node scripts/sample_journey.mjs)
  RETRY_DELAY_SECONDS   pause before a retry (default 30)
  WATCHDOG_DEVICES      space-separated profiles (default: desktop galaxy-a10 android-tablet)
  GITHUB_STEP_SUMMARY   where the Markdown summary is appended, when set
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

DEVICES = ("desktop", "galaxy-a10", "android-tablet")
RETRY_DELAY_SECONDS = 30
# A journey takes a few seconds; its own waits are bounded. This only stops a
# wedged process holding the job until its 15-minute cap.
JOURNEY_TIMEOUT_SECONDS = 300

# Chromium network error codes that mean the connection itself failed, not
# that a server or the page decided anything. Deliberately excludes
# ERR_FAILED (what a CORS refusal looks like), ERR_ABORTED (a navigation or
# fetch the page itself cancelled), ERR_BLOCKED_BY_* and anything a policy
# produces: those are deterministic and retrying them only delays the alert.
TRANSPORT_ERRORS = frozenset({
    "net::ERR_CONNECTION_RESET",
    "net::ERR_CONNECTION_CLOSED",
    "net::ERR_CONNECTION_ABORTED",
    "net::ERR_CONNECTION_REFUSED",
    "net::ERR_CONNECTION_TIMED_OUT",
    "net::ERR_CONNECTION_FAILED",
    "net::ERR_TIMED_OUT",
    "net::ERR_EMPTY_RESPONSE",
    "net::ERR_NETWORK_CHANGED",
    "net::ERR_INTERNET_DISCONNECTED",
    "net::ERR_ADDRESS_UNREACHABLE",
    "net::ERR_NAME_NOT_RESOLVED",
    "net::ERR_NAME_RESOLUTION_FAILED",
    "net::ERR_HTTP2_PROTOCOL_ERROR",
    "net::ERR_HTTP2_PING_FAILED",
    "net::ERR_QUIC_PROTOCOL_ERROR",
    "net::ERR_SSL_PROTOCOL_ERROR",
    "net::ERR_SOCKET_NOT_CONNECTED",
})
_TRANSPORT_RE = re.compile("|".join(re.escape(code) for code in sorted(TRANSPORT_ERRORS)))

# Gateway and timeout answers for the page itself: the edge or the origin did
# not produce the page this time. 520-524 are Cloudflare's own origin errors.
TRANSIENT_LOAD_STATUSES = frozenset({408, 502, 503, 504, 520, 521, 522, 523, 524})

# Steps whose failure is a decision about the page, never the network.
DETERMINISTIC_STEPS = frozenset({"picture-study-csp"})


def is_transient(report: dict | None) -> bool:
    """True when a failed report shows a transient load or connection failure
    and nothing deterministic. False for anything else, including a passing
    or unreadable report."""
    if not isinstance(report, dict) or report.get("ok") is not False:
        return False
    step = report.get("failedStep")
    if step in DETERMINISTIC_STEPS:
        return False
    # The API answered with a server error: an application error, reported
    # as such, not retried.
    if any(isinstance(r, dict) and isinstance(r.get("status"), int) and r["status"] >= 500
           for r in report.get("requests") or []):
        return False
    # The policy refused the backend call: a deployment header problem.
    if any(re.search(r"connect-src", str(v), re.I) for v in report.get("cspViolations") or []):
        return False
    if step == "load":
        status = report.get("loadStatus", "missing")
        # null means the navigation produced no response at all.
        return status is None or status in TRANSIENT_LOAD_STATUSES
    if step == "exception":
        return bool(_TRANSPORT_RE.search(str(report.get("exception") or "")))
    return any(
        isinstance(f, dict) and str(f.get("failure")) in TRANSPORT_ERRORS
        for f in report.get("networkFailures") or []
    )


def read_report(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def run_journey(cmd: list[str], url: str, device: str, out: Path) -> int:
    env = {**os.environ, "DEVICE_PROFILE": device}
    with out.open("w", encoding="utf-8") as fh:
        try:
            return subprocess.run([*cmd, url], stdout=fh, env=env,
                                  timeout=JOURNEY_TIMEOUT_SECONDS).returncode
        except subprocess.TimeoutExpired:
            return 124


def _summary_of(report: dict | None) -> str:
    if report is None:
        return "the check produced no readable report"
    return str(report.get("summary") or "no summary")


def check_device(cmd: list[str], url: str, device: str, workdir: Path,
                 delay: float, sleep=time.sleep) -> dict:
    """Run one device, retrying once on a transient failure. Returns what
    happened, including both attempts when there was a retry."""
    final = workdir / f"journey-report-{device}.json"
    code = run_journey(cmd, url, device, final)
    first = read_report(final)
    if code == 0:
        return {"device": device, "outcome": "passed", "attempts": [(code, first, final)]}
    if not is_transient(first):
        return {"device": device, "outcome": "failed", "attempts": [(code, first, final)]}

    # Keep the first attempt under its own name; the final report keeps the
    # established name the repair prompt and the artifact already use.
    kept = workdir / f"journey-report-{device}.attempt-1.json"
    final.replace(kept)
    sleep(delay)
    code2 = run_journey(cmd, url, device, final)
    second = read_report(final)
    outcome = "passed_on_retry" if code2 == 0 else "failed_after_retry"
    return {"device": device, "outcome": outcome,
            "attempts": [(code, first, kept), (code2, second, final)]}


RESULT_LINES = {
    "passed": "**Result:** ✅ the demo works",
    "passed_on_retry": "**Result:** ✅ passed on retry (the first attempt hit a transient load or connection failure)",
    "failed": "**Result:** ❌ the demo is broken",
    "failed_after_retry": "**Result:** ❌ the demo is broken (failed again on retry)",
}


def summary_markdown(result: dict) -> str:
    attempts = result["attempts"]
    name = next((r.get("device") for _, r, _ in reversed(attempts) if r and r.get("device")),
                result["device"])
    lines = [f"### Demo watchdog — {name}", "", RESULT_LINES[result["outcome"]], ""]
    if len(attempts) == 1:
        lines += [_summary_of(attempts[0][1]), ""]
    else:
        for i, (code, report, path) in enumerate(attempts, 1):
            verdict = "passed" if code == 0 else "failed"
            lines += [f"Attempt {i} ({verdict}, `{path.name}`): {_summary_of(report)}", ""]
    return "\n".join(lines) + "\n"


def main() -> int:
    url = os.environ.get("DEMO_URL", "").strip()
    if not url:
        print("DEMO_URL is not set", file=sys.stderr)
        return 2
    cmd = shlex.split(os.environ.get("JOURNEY_CMD") or "node scripts/sample_journey.mjs")
    delay = float(os.environ.get("RETRY_DELAY_SECONDS") or RETRY_DELAY_SECONDS)
    devices = (os.environ.get("WATCHDOG_DEVICES") or " ".join(DEVICES)).split()
    workdir = Path.cwd()
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")

    overall = 0
    # Every device is checked and reported even when an earlier one failed.
    for device in devices:
        result = check_device(cmd, url, device, workdir, delay)
        if result["outcome"] not in ("passed", "passed_on_retry"):
            overall = 1
        # Always print every attempt's report: a green run that printed
        # nothing teaches nobody anything.
        for _, _, path in result["attempts"]:
            print(f"--- {path.name}")
            try:
                print(path.read_text(encoding="utf-8"), end="")
            except OSError:
                print("(no report)")
        print(f"=== {device}: {result['outcome']}", flush=True)
        if summary_path:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write(summary_markdown(result))
    # The job's own result is what the repair gate reads.
    return overall


if __name__ == "__main__":
    sys.exit(main())
