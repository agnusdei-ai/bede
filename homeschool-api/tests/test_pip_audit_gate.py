"""scripts/pip_audit_gate.py keeps clean, advisory and "audit unavailable"
apart, and retries only a transient PyPI failure.

The cases run the REAL gate as the workflow does, with a stand-in pip-audit
that behaves the way the real one was observed to: a completed audit writes
its JSON report and exits 0 (clean) or 1 (vulnerabilities); a network failure
writes NO report and also exits 1, with a requests traceback on stderr. The
error text below is the line from the 2026-11-18 CI failure.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts" / "pip_audit_gate.py"
ALLOWLIST = ROOT / ".github" / "audit-allowlist.json"

sys.path.insert(0, str(GATE.parent))
import pip_audit_gate as gate  # noqa: E402

READ_TIMEOUT = ("requests.exceptions.ReadTimeout: HTTPSConnectionPool(host='pypi.org', port=443): "
                "Read timed out. (read timeout=15)")
NAME_LOOKUP = ("requests.exceptions.ConnectionError: HTTPSConnectionPool(host='pypi.org', port=443): "
               "Max retries exceeded (Caused by NameResolutionError(\"Failed to resolve 'pypi.org'\"))")
BAD_REQUIREMENT = "pip_audit._dependency_source.interface.DependencySourceError: invalid requirement"

CLEAN = {"dependencies": [{"name": "idna", "version": "3.15", "vulns": []}], "fixes": []}
VULN = {"dependencies": [{"name": "pyyaml", "version": "5.3", "vulns": [
    {"id": "PYSEC-2020-96", "fix_versions": ["5.3.1"], "aliases": ["GHSA-8q59-q68h-6hv4"]},
    {"id": "PYSEC-2020-96", "fix_versions": ["5.3.1"], "aliases": ["GHSA-8q59-q68h-6hv4"]},
]}], "fixes": []}

# Each step: ("report", data, exit code) writes the report, or
# ("error", text, exit code) writes none and prints a traceback.
OK = ("report", CLEAN, 0)
FOUND = ("report", VULN, 1)
TIMEOUT = ("error", READ_TIMEOUT, 1)


def _stand_in(tmp_path: Path, plan: list) -> str:
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    script = tmp_path / "fake_pip_audit.py"
    script.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        f"base = Path({str(tmp_path)!r})\n"
        "calls = base / 'calls'\n"
        "n = int(calls.read_text()) if calls.exists() else 0\n"
        "calls.write_text(str(n + 1))\n"
        "(base / f'argv-{n}').write_text(json.dumps(sys.argv[1:]))\n"
        "kind, data, code = json.loads((base / 'plan.json').read_text())[n]\n"
        "if kind == 'report':\n"
        "    Path(sys.argv[sys.argv.index('-o') + 1]).write_text(json.dumps(data))\n"
        "else:\n"
        "    print('Traceback (most recent call last):', file=sys.stderr)\n"
        "    print(data, file=sys.stderr)\n"
        "sys.exit(code)\n"
    )
    return f"{sys.executable} {script}"


def _run(tmp_path: Path, plan: list, files=("requirements.lock.txt",), allowlist=ALLOWLIST):
    summary = tmp_path / "summary.md"
    env = {**os.environ, "PIP_AUDIT_CMD": _stand_in(tmp_path, plan),
           "PIP_AUDIT_BACKOFF": "0", "GITHUB_STEP_SUMMARY": str(summary)}
    proc = subprocess.run([sys.executable, str(GATE), "--allowlist", str(allowlist), *files],
                          env=env, capture_output=True, text=True, timeout=60)
    calls = int((tmp_path / "calls").read_text()) if (tmp_path / "calls").exists() else 0
    return proc, calls, summary.read_text() if summary.exists() else ""


def test_a_clean_audit_passes(tmp_path):
    proc, calls, summary = _run(tmp_path, [OK])
    assert (proc.returncode, calls) == (0, 1)
    assert "✅ clean (no known vulnerabilities)" in summary


def test_recovery_after_a_read_timeout(tmp_path):
    proc, calls, summary = _run(tmp_path, [TIMEOUT, OK])
    assert (proc.returncode, calls) == (0, 2), proc.stdout
    assert "clean after 2 attempts" in summary
    assert "attempt 1 did not complete" in proc.stdout and "Read timed out" in proc.stdout


def test_exhausted_retries_fail_as_audit_unavailable_never_clean(tmp_path):
    proc, calls, summary = _run(tmp_path, [TIMEOUT, TIMEOUT, TIMEOUT, OK])
    assert proc.returncode == 3
    assert calls == gate.ATTEMPTS == 3
    assert "audit unavailable" in summary and "after 3 attempts" in summary
    assert "neither an advisory nor evidence that the dependencies are clean" in summary
    assert "clean (" not in summary and "advisory found" not in summary


def test_an_advisory_fails_at_once_and_is_not_retried(tmp_path):
    proc, calls, summary = _run(tmp_path, [FOUND, OK])
    assert (proc.returncode, calls) == (1, 1)
    assert "advisory found" in summary
    # Listed once, though pip-audit listed it twice.
    assert summary.count("pyyaml 5.3: PYSEC-2020-96 (fixed in 5.3.1)") == 1


def test_an_advisory_after_a_timeout_still_fails_as_an_advisory(tmp_path):
    proc, calls, summary = _run(tmp_path, [TIMEOUT, FOUND])
    assert (proc.returncode, calls) == (1, 2)
    assert "advisory found" in summary


def test_an_allowlisted_advisory_passes_by_id_or_alias(tmp_path):
    allow = tmp_path / "allow.json"
    allow.write_text(json.dumps({"python": [{"id": "GHSA-8q59-q68h-6hv4"}]}))
    proc, _, summary = _run(tmp_path, [("report", VULN, 0)], allowlist=allow)
    assert proc.returncode == 0, summary
    argv = json.loads((tmp_path / "argv-0").read_text())
    assert argv[argv.index("--ignore-vuln") + 1] == "GHSA-8q59-q68h-6hv4"


def test_a_non_transient_error_is_not_retried_and_is_not_clean(tmp_path):
    proc, calls, summary = _run(tmp_path, [("error", BAD_REQUIREMENT, 1), OK])
    assert (proc.returncode, calls) == (3, 1)
    assert "audit unavailable" in summary


def test_a_failing_exit_with_an_empty_report_is_not_clean(tmp_path):
    proc, _, summary = _run(tmp_path, [("report", CLEAN, 1)])
    assert proc.returncode == 3
    assert "audit unavailable" in summary


def test_an_unreadable_allowlist_is_unavailable_not_clean(tmp_path):
    bad = tmp_path / "allow.json"
    bad.write_text("{not json")
    proc, calls, _ = _run(tmp_path, [OK], allowlist=bad)
    assert (proc.returncode, calls) == (3, 0)


def test_a_missing_pip_audit_is_unavailable_not_clean(tmp_path):
    env = {**os.environ, "PIP_AUDIT_CMD": str(tmp_path / "no-such-pip-audit"), "PIP_AUDIT_BACKOFF": "0"}
    proc = subprocess.run([sys.executable, str(GATE), "--allowlist", str(ALLOWLIST), "r.txt"],
                          env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 3


def test_both_files_are_audited_and_the_worst_outcome_wins(tmp_path):
    proc, calls, summary = _run(tmp_path, [OK, TIMEOUT, TIMEOUT, TIMEOUT],
                                files=("requirements.lock.txt", "requirements-dev.lock.txt"))
    assert (proc.returncode, calls) == (3, 4)
    assert "`requirements.lock.txt`: ✅ clean" in summary
    assert "`requirements-dev.lock.txt`: ⚠️ **audit unavailable**" in summary


def test_the_backoff_waits_between_attempts():
    waits = []
    gate.audit(["false"], "r.txt", [], 3, [20, 60], sleep=waits.append, log=lambda *_: None)
    # `false` exits 1 with no report and no transient text: not retried.
    assert waits == []
    real = gate.audit_once

    def timing_out(*_a, **_k):
        return gate.UNAVAILABLE, [], READ_TIMEOUT

    gate.audit_once = timing_out
    try:
        result = gate.audit(["x"], "r.txt", [], 3, [20, 60], sleep=waits.append, log=lambda *_: None)
    finally:
        gate.audit_once = real
    assert waits == [20, 60]
    assert result["outcome"] == gate.UNAVAILABLE


@pytest.mark.parametrize("text", [READ_TIMEOUT, NAME_LOOKUP,
                                  "requests.exceptions.ConnectTimeout: timed out",
                                  "urllib3.exceptions.ProtocolError: ('Connection aborted.', "
                                  "RemoteDisconnected('Remote end closed connection'))",
                                  "requests.exceptions.HTTPError: 503 Server Error: Service Unavailable"])
def test_transient_network_failures_are_recognised(text):
    assert gate.TRANSIENT.search(text)


@pytest.mark.parametrize("text", [BAD_REQUIREMENT, "",
                                  "requests.exceptions.HTTPError: 404 Client Error: Not Found",
                                  "Found 2 known vulnerabilities in 1 package"])
def test_other_errors_are_not_retried(text):
    assert not gate.TRANSIENT.search(text)
