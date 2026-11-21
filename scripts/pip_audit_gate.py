#!/usr/bin/env python3
"""`pip-audit` as a gate that retries a transient PyPI failure and never
mistakes an audit that did not complete for a clean one.

Called by `.github/workflows/test.yml`'s `dependency-audit` job. Standard
library only.

## Why this exists

pip-audit looks every pinned version up on PyPI. On 2026-11-18 the
`dependency-audit` job failed on two unrelated pull requests because PyPI did
not answer within 15 seconds (`requests.exceptions.ReadTimeout`). The job
never read a single advisory. It was red for the same reason it would be red
for a real vulnerability, and nothing in the job said which.

pip-audit makes that easy to get wrong in both directions: it exits **1** for
"found a vulnerability" AND for "could not reach PyPI". The exit code cannot
tell them apart. The JSON report can: an audit that completed writes one, and
one that crashed on the network writes nothing.

## The three outcomes, kept separate

1. **Clean**: pip-audit exited 0 and wrote a report with no vulnerabilities.
2. **Advisory**: the report lists a vulnerability not recorded in
   `.github/audit-allowlist.json`. This fails at once, as it always did, and
   is never retried: an advisory is an answer, and asking again cannot
   change it.
3. **Audit unavailable**: no usable report. If pip-audit's error output shows
   a transient network failure (a timeout, a refused or reset connection, a
   failed name lookup, a 5xx or 429 from PyPI), it is retried up to
   ATTEMPTS times with BACKOFF_SECONDS between. If it still cannot complete,
   or the error is not one of those, the gate fails with "audit unavailable".
   **A timeout is neither an advisory nor evidence that the dependencies are
   clean**, so it is reported as neither.

The gate fails closed throughout: a missing pip-audit, an unreadable
allowlist, or a report it cannot parse is "audit unavailable", never clean.

Exit codes: 0 clean, 1 at least one advisory, 3 audit unavailable (and no
advisory), 2 bad usage.

Usage:
  python3 scripts/pip_audit_gate.py --allowlist ../.github/audit-allowlist.json \\
      requirements.lock.txt requirements-dev.lock.txt

Environment:
  PIP_AUDIT_CMD         the pip-audit command (default: pip-audit)
  PIP_AUDIT_ATTEMPTS    attempts per requirements file (default 3)
  PIP_AUDIT_BACKOFF     comma-separated waits in seconds (default 20,60)
  GITHUB_STEP_SUMMARY   where the Markdown summary is appended, when set
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ATTEMPTS = 3
BACKOFF_SECONDS = (20, 60)
# One pip-audit run over a lockfile takes about a minute; this only stops a
# wedged process holding the job.
RUN_TIMEOUT_SECONDS = 900

CLEAN, ADVISORY, UNAVAILABLE = "clean", "advisory", "unavailable"

# What a transient network failure looks like in pip-audit's error output.
# These are requests/urllib3 exception names and PyPI's own status answers.
# Anything else (a malformed requirement, a resolver error, a crash) is not
# retried: asking again would give the same answer.
TRANSIENT = re.compile(
    r"ReadTimeout|ConnectTimeout|ConnectionError|ConnectionResetError|"
    r"RemoteDisconnected|ProtocolError|ChunkedEncodingError|IncompleteRead|"
    r"NameResolutionError|Temporary failure in name resolution|"
    r"Max retries exceeded|timed out|"
    r"\b(?:429|500|502|503|504)\b (?:Server Error|Too Many Requests)|"
    r"HTTPError: (?:429|50[0-4])"
)


def allowlisted_ids(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    ids = [entry["id"] for entry in data.get("python", [])]
    if not all(isinstance(i, str) and i for i in ids):
        raise ValueError("every python allowlist entry needs an id")
    return ids


def findings(report: dict, ignored: set[str]) -> list[str]:
    """Every vulnerability in a pip-audit JSON report that is not
    allowlisted, by its id or any alias."""
    found = []
    for dep in report.get("dependencies", []):
        for vuln in dep.get("vulns") or []:
            names = {vuln.get("id"), *(vuln.get("aliases") or [])}
            if names & ignored:
                continue
            fixes = ", ".join(vuln.get("fix_versions") or []) or "no fix published"
            found.append(f"{dep.get('name')} {dep.get('version')}: {vuln.get('id')} (fixed in {fixes})")
    # pip-audit can list one advisory more than once; report each once.
    return list(dict.fromkeys(found))


def audit_once(cmd: list[str], requirements: str, ignored: list[str]) -> tuple[str, list[str], str]:
    """One pip-audit run. Returns (outcome, findings, error text)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "report.json"
        argv = [*cmd, "-r", requirements, "-f", "json", "-o", str(out)]
        for vid in ignored:
            argv += ["--ignore-vuln", vid]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=RUN_TIMEOUT_SECONDS)
        except FileNotFoundError as exc:
            return UNAVAILABLE, [], f"pip-audit could not be started: {exc}"
        except subprocess.TimeoutExpired:
            return UNAVAILABLE, [], f"pip-audit did not finish within {RUN_TIMEOUT_SECONDS}s (timed out)"
        error = (proc.stderr or "") + (proc.stdout or "")
        try:
            report = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # No report: the audit did not complete, whatever the exit code.
            return UNAVAILABLE, [], error
    found = findings(report, set(ignored))
    if found:
        return ADVISORY, found, error
    if proc.returncode == 0:
        return CLEAN, [], error
    # A report with nothing in it, yet a failing exit: something went wrong
    # that the report does not explain. Not clean.
    return UNAVAILABLE, [], error


def audit(cmd: list[str], requirements: str, ignored: list[str], attempts: int,
          backoff: list[float], sleep=time.sleep, log=print) -> dict:
    tries = []
    for n in range(1, attempts + 1):
        outcome, found, error = audit_once(cmd, requirements, ignored)
        transient = outcome == UNAVAILABLE and bool(TRANSIENT.search(error))
        tries.append({"attempt": n, "outcome": outcome, "transient": transient})
        if outcome != UNAVAILABLE:
            return {"file": requirements, "outcome": outcome, "findings": found, "tries": tries}
        last = error.strip().splitlines()[-1] if error.strip() else "no output"
        log(f"{requirements}: attempt {n} did not complete: {last}")
        if not transient:
            log(f"{requirements}: the error is not a transient network failure; not retrying")
            break
        if n < attempts:
            wait = backoff[min(n - 1, len(backoff) - 1)] if backoff else 0
            log(f"{requirements}: retrying in {wait:g}s")
            sleep(wait)
    return {"file": requirements, "outcome": UNAVAILABLE, "findings": [], "tries": tries}


def summarize(results: list[dict]) -> tuple[int, str]:
    lines = ["### Dependency audit (pip-audit)", ""]
    for r in results:
        n = len(r["tries"])
        retried = f" after {n} attempts" if n > 1 else ""
        if r["outcome"] == CLEAN:
            lines.append(f"- `{r['file']}`: ✅ clean{retried} (no known vulnerabilities)")
        elif r["outcome"] == ADVISORY:
            lines.append(f"- `{r['file']}`: ❌ advisory found")
            lines += [f"  - {f}" for f in r["findings"]]
        else:
            lines.append(
                f"- `{r['file']}`: ⚠️ **audit unavailable**{retried}. The audit did not complete, "
                "so this is neither an advisory nor evidence that the dependencies are clean."
            )
    outcomes = {r["outcome"] for r in results}
    code = 1 if ADVISORY in outcomes else 3 if UNAVAILABLE in outcomes else 0
    return code, "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--allowlist", required=True, type=Path)
    parser.add_argument("requirements", nargs="+")
    args = parser.parse_args(argv)

    cmd = shlex.split(os.environ.get("PIP_AUDIT_CMD") or "pip-audit")
    attempts = max(1, int(os.environ.get("PIP_AUDIT_ATTEMPTS") or ATTEMPTS))
    backoff_env = os.environ.get("PIP_AUDIT_BACKOFF")
    backoff = [float(x) for x in backoff_env.split(",")] if backoff_env else list(BACKOFF_SECONDS)

    try:
        ignored = allowlisted_ids(args.allowlist)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"audit unavailable: cannot read the allowlist {args.allowlist}: {exc}")
        return 3

    results = [audit(cmd, req, ignored, attempts, backoff) for req in args.requirements]
    code, text = summarize(results)
    print(text, end="")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(text)
    if code == 3:
        print("audit unavailable: at least one requirements file could not be audited. "
              "This is not a clean result.")
    return code


if __name__ == "__main__":
    sys.exit(main())
