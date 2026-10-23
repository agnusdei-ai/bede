#!/usr/bin/env python3
"""Bounded affected-code QA runner. No silent test skipping or blind reruns.

Runs an existing selector plan. Safe repair is limited to restoring locally
missing dependencies with reproducible installs; semantic test/code defects
are BLOCKED for a coding agent to patch with a regression test and new SHA.
Does not change source, lockfiles, policy, security gates or CI status.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PATTERNS = (
    ("security_audit", r"GHSA-|CVE-|vulnerabilit|pip.audit|audit gate"),
    ("outdated_test", r"(?m)^FAILED tests/|AssertionError|TestingLibraryElementError|AssertionFailed|toHaveTextContent"),
    ("type_or_build", r"TS\d{4}|TypeError|SyntaxError|Build failed|error TS\d+"),
    ("dependency_lock", r"npm (?:ERR!|error)|EUSAGE|lockfile.*(?:missing|mismatch|corrupt)|hash mismatch"),
    ("environment", r"ModuleNotFoundError|Cannot find module|ENOENT|Connection refused|DATABASE_URL"),
    ("authorization", r"forbidden|unauthorized|401|403|cross.campus|webauthn"),
    ("test_flakiness", r"timed out|TimeoutError|race condition|flaky"),
)
SENSITIVE = re.compile(r"(?i)(api[_-]?key|password|secret|token|authorization)([=: ]+)([^ ,\n]+)")


def sanitize(line: str) -> str:
    return SENSITIVE.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", line)


def categorize(log: str) -> str:
    for category, expression in PATTERNS:
        if re.search(expression, log, re.I):
            return category
    return "application_or_unclassified"


def run_command(argv: list[str], cwd: Path, timeout: int) -> dict:
    start = time.monotonic()
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                                errors="replace", timeout=timeout, check=False)
        output = sanitize((result.stdout or "")[-24000:] + "\n" + (result.stderr or "")[-9000:])
        code = result.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        output, code = sanitize(str(exc)), 124
    return {"command": argv, "cwd": str(cwd), "exit_code": code,
            "duration_seconds": round(time.monotonic() - start, 2),
            "category": "pass" if code == 0 else categorize(output),
            "diagnostic_excerpt": "\n".join(output.splitlines()[-90:])[-10000:] if code else ""}


def missing_local_install(result: dict) -> bool:
    msg = result["diagnostic_excerpt"]
    return bool(re.search(r"ModuleNotFoundError|Cannot find module|node_modules|npm ERR! ENOENT", msg))


def execute(root: Path, plan: dict, scope: str, timeout: int,
            repair: bool = False, max_attempts: int = 2) -> dict:
    if max_attempts < 1 or max_attempts > 2:
        raise ValueError("QA repair attempts are bounded to 1 or 2")
    selected = [cmd for cmd in plan["commands"] if cmd["scope"] == scope]
    detail = plan["scopes"][scope]
    report = {
        "schema": 1, "when_utc": datetime.now(timezone.utc).isoformat(),
        "head": plan.get("head"), "merge_base": plan.get("merge_base"),
        "input_sha256": plan.get("input_sha256"),
        "changed_modules": plan["changed_modules"],
        "scope": scope, "selected_tests": [cmd["argv"] for cmd in selected],
        "mapping": "full" if detail["full"] else "affected",
        "mapping_reasons": detail["reasons"], "results": [],
        "repairs": [], "security_checks": plan["mandatory_external_gates"],
        "runner_seconds": 0, "github_billed_minutes": None,
        "merge_status": "blocked",
    }
    if not selected:
        if detail["full"] or detail["tests"]:
            raise ValueError("Unmapped nonempty test scope: refusing success")
        report["merge_status"] = "unaffected (required external gates still apply)"
        return report
    for cmd in selected:
        working = (root / cmd["cwd"]).resolve()
        if not working.is_relative_to(root.resolve()) or not working.is_dir():
            raise ValueError("Invalid or missing working directory: " + cmd["cwd"])
        argv = cmd["argv"]
        if not argv or any(not isinstance(x, str) for x in argv):
            raise ValueError("Invalid test command")
        # Plan files are data, not arbitrary executable instructions.
        allowed = (argv[:3] == ["python", "-m", "pytest"] or
                   argv[:2] == ["npx", "tsc"] or
                   argv[:3] == ["npx", "vitest", "run"] or
                   argv == ["npm", "test"])
        if not allowed:
            raise ValueError("Untrusted command in QA plan: " + repr(argv))
        attempt = 0
        while attempt < max_attempts:
            attempt += 1
            result = run_command(argv, working, timeout)
            result["attempt"] = attempt
            report["results"].append(result)
            report["runner_seconds"] += result["duration_seconds"]
            if result["exit_code"] == 0:
                break
            if not repair or attempt >= max_attempts or not missing_local_install(result):
                break
            # A missing local install is an environment defect, not a source
            # repair. npm ci reads an immutable lockfile; pip uses hashes.
            install = (["python", "-m", "pip", "install", "--require-hashes",
                        "-r", "requirements-dev.lock.txt"]
                       if scope == "backend" else ["npm", "ci"])
            repaired = run_command(install, working, timeout)
            repaired["reason"] = "missing local dependencies only"
            report["repairs"].append(repaired)
            report["runner_seconds"] += repaired["duration_seconds"]
            if repaired["exit_code"] != 0:
                break
    failures = [x for x in report["results"] if x["exit_code"] != 0]
    # A later *passing* retry can supersede only its own failed attempt.
    terminal = {tuple(x["command"]): x for x in report["results"]}
    report["merge_status"] = ("ready for external CI and security gates"
                              if all(x["exit_code"] == 0 for x in terminal.values())
                              and all(x["exit_code"] == 0 for x in report["repairs"])
                              else "blocked")
    report["runner_seconds"] = round(report["runner_seconds"], 2)
    report["failed_attempts"] = len(failures)
    return report


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", required=True)
    p.add_argument("--scope", required=True,
                   choices=["backend", "homeschool-tutor", "demo", "license-server"])
    p.add_argument("--repo", default=".")
    p.add_argument("--report", required=True)
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--repair", action="store_true",
                   help="Only reinstall missing local dependencies; no source edits")
    args = p.parse_args()
    root = Path(args.repo).resolve()
    with open(args.plan, encoding="utf-8") as fp:
        plan = json.load(fp)
    if plan.get("version") != 1 or args.scope not in plan.get("scopes", {}):
        print("Unsupported/unmapped QA plan; blocking", file=sys.stderr)
        return 2
    if args.timeout < 1 or args.timeout > 3600:
        print("QA timeout must be 1..3600 seconds", file=sys.stderr)
        return 2
    result = execute(root, plan, args.scope, args.timeout, args.repair)
    output = Path(args.report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    summary = (f"QA {args.scope}: {result['merge_status']}; "
               f"{len(result['results'])} test command attempts; "
               f"{result['runner_seconds']}s")
    print(summary)
    for attempt in result["results"]:
        if attempt["exit_code"]:
            message = attempt["diagnostic_excerpt"]
            print(
                f"QA FAIL [{attempt['category']}] "
                f"{' '.join(attempt['command'])} (exit {attempt['exit_code']})",
                file=sys.stderr,
            )
            # Emit the actual failure summary in CI even when this runner
            # captured stdout. The JSON evidence remains the full audit trail.
            print(message[-10000:], file=sys.stderr)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fp:
            fp.write("### " + summary + "\n\n")
            for x in result["results"]:
                fp.write("- " + ("PASS" if x["exit_code"] == 0 else "FAIL") +
                         ": " + " ".join(x["command"]) +
                         f" ({x['duration_seconds']}s, {x['category']})\n")
            fp.write("\nBilled runner minutes: consult GitHub job usage metrics; "
                     "local elapsed seconds are not billing evidence.\n\n")
    return 0 if result["merge_status"] != "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
