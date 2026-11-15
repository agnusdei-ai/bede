"""Read the EXISTING qualification outputs into one result vocabulary.

PASS / FAIL / SKIP / NOT_RUN / INFRA_ERROR. Nothing missing, ABSENT, BLOCKED
or UNVERIFIED is ever a pass, and a result is refused outright when it was
produced against a different SHA than the one asked about.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

STATUSES = ("PASS", "FAIL", "SKIP", "NOT_RUN", "INFRA_ERROR")
_MATRIX = {"PASS": "PASS", "FAIL": "FAIL", "ABSENT": "FAIL", "BLOCKED": "FAIL", "UNVERIFIED": "FAIL"}
_FRAME = re.compile(r"^\s+(?:WebCore|WebKit|JavaScriptCore)\s+(\S+?)\(", re.M)


class ShaMismatch(ValueError):
    pass


def _r(source, check, status, sha, detail="", **extra):
    assert status in STATUSES
    return {"source": source, "check": check, "status": status, "sha": sha, "detail": str(detail)[:400], **extra}


def _bind(found: str | None, sha: str, where: str):
    if found and found != sha:
        raise ShaMismatch(f"{where} was produced for {found[:12]}, not {sha[:12]}")


def qualification_matrix(out_dir: Path, sha: str) -> list[dict]:
    manifest, matrix = out_dir / "manifest.json", out_dir / "matrix.json"
    if not matrix.exists():
        return [_r("qualification_matrix", "matrix", "NOT_RUN", sha, "matrix.json absent")]
    if manifest.exists():
        _bind(json.loads(manifest.read_text()).get("candidate_sha"), sha, "manifest.json")
    data = json.loads(matrix.read_text())
    rows = [_r("qualification_matrix", f"{c['group']}/{c['cell']}", _MATRIX.get(c["status"], "FAIL"), sha,
               c.get("detail", ""), original_status=c["status"]) for c in data.get("cells", [])]
    return rows or [_r("qualification_matrix", "matrix", "NOT_RUN", sha, "no cells")]


def browser_journeys(out_dir: Path, sha: str, expected: list[str] | None = None) -> list[dict]:
    results = out_dir / "results.json"
    if not results.exists():
        return [_r("browser_journeys", "results", "NOT_RUN", sha, "results.json absent")]
    data = json.loads(results.read_text())
    summary = data.get("summary", {})
    _bind(summary.get("sha"), sha, "results.json")
    os_name = summary.get("os")
    frames = crash_frames(out_dir / "crash-reports")
    rows = []
    for c in data.get("checks", []):
        rows.append(_r("browser_journeys", f"{c['user']}/{c['check']}", "PASS" if c.get("ok") else "FAIL",
                       sha, c.get("note", ""), os=os_name))
    for s in data.get("steps", []):
        if not s.get("ok"):
            rows.append(_r("browser_journeys", f"{s['user']}/{s['step']}", "FAIL", sha, s.get("note", ""),
                           os=os_name, crash_frames=frames if "crash" in str(s.get("note", "")).lower() else []))
    for m in summary.get("missing_checks", []) + [e for e in (expected or [])
                                                    if e not in {f"{c['user']}/{c['check']}" for c in data.get("checks", [])}]:
        rows.append(_r("browser_journeys", m, "NOT_RUN", sha, "expected check did not report", os=os_name))
    return rows or [_r("browser_journeys", "results", "NOT_RUN", sha, "no checks", os=os_name)]


def crash_frames(summary_dir: Path) -> list[str]:
    """Function names from the SANITIZED crash summaries only, never a raw report."""
    if not summary_dir.is_dir():
        return []
    frames: list[str] = []
    for f in sorted(summary_dir.glob("*")):
        if f.is_file() and f.suffix != ".ips":
            frames += _FRAME.findall(f.read_text(errors="replace"))
    return frames[:40]


def qa_runner(report: Path, sha: str, scope: str) -> list[dict]:
    if not report.exists():
        return [_r("qa_runner", scope, "NOT_RUN", sha, "runner report absent", scope=scope)]
    data = json.loads(report.read_text())
    _bind(data.get("head"), sha, report.name)
    if data.get("merge_status", "").startswith("unaffected"):
        return [_r("qa_runner", scope, "SKIP", sha, "no affected tests", scope=scope)]
    terminal = {tuple(x["command"]): x for x in data.get("results", [])}
    if not terminal:
        return [_r("qa_runner", scope, "NOT_RUN", sha, "no commands ran", scope=scope)]
    rows = []
    for cmd, x in terminal.items():
        status = "PASS" if x["exit_code"] == 0 else ("INFRA_ERROR" if x.get("category") == "environment" else "FAIL")
        rows.append(_r("qa_runner", " ".join(cmd), status, sha, x.get("category", ""), scope=scope))
    return rows


def release_provenance(path: Path, sha: str) -> list[dict]:
    if not path.exists():
        return [_r("release_provenance", "package", "NOT_RUN", sha, "RELEASE_PROVENANCE.json absent")]
    data = json.loads(path.read_text())
    _bind(data.get("source_sha"), sha, "RELEASE_PROVENANCE.json")
    ok = data.get("prior_qualification_carries_to_this_sha") is False
    return [_r("release_provenance", "package", "PASS" if ok else "FAIL", sha,
               "bound to this SHA" if ok else "provenance claims prior qualification carries over",
               digest=data.get("digest"))]


def mac_check(path: Path, sha: str) -> list[dict]:
    """A person's physical check. Absent is NOT_RUN; it is never inferred."""
    if not path.exists():
        return [_r("mac_check", "physical_mac", "NOT_RUN", sha, "no physical Mac record supplied")]
    data = json.loads(path.read_text())
    _bind(data.get("candidate_sha"), sha, "mac-check-result.json")
    rows = []
    for item, v in sorted(data.get("items", {}).items()):
        if v.get("you_said") == "(skipped)":
            st = "NOT_RUN"
        else:
            st = "PASS" if v.get("server_says") == "PASS" and v.get("you_said") == "yes" else "FAIL"
        rows.append(_r("mac_check", item, st, sha, v.get("why", ""), browser=data.get("browser_requested")))
    if not data.get("finished"):
        rows.append(_r("mac_check", "finished", "NOT_RUN", sha, "check did not finish"))
    return rows or [_r("mac_check", "physical_mac", "NOT_RUN", sha, "no items")]
