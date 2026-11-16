"""Read the EXISTING qualification outputs into one result vocabulary.

PASS / FAIL / SKIP / NOT_RUN / INFRA_ERROR. Nothing missing, ABSENT, BLOCKED
or UNVERIFIED is ever a pass, and a result is refused outright when it was
produced against a different SHA than the one asked about.
"""
from __future__ import annotations

import hashlib
import json
import re
import tarfile
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
               digest=data.get("digest"), embedded_sha=data.get("source_sha"),
               architecture=data.get("architecture"))]


PACKAGE_SUFFIXES = (".tar.gz", ".dmg", ".exe", ".deb", ".rpm")
_PROVENANCE = "RELEASE_PROVENANCE.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _checksum(f: Path) -> dict:
    """The build's own .sha256 sidecar, recomputed. Never inferred from the
    Actions archive digest: a missing sidecar is NOT_RUN."""
    side = f.with_name(f.name + ".sha256")
    if not side.exists():
        return {"status": "NOT_RUN", "reason": "no .sha256 sidecar beside the artifact"}
    want = (side.read_text().split() or [""])[0].lower()
    got = _sha256(f)
    return {"status": "PASS" if want == got else "FAIL", "sha256": got, "sidecar": want}


def _provenance_for(f: Path) -> tuple[dict | None, str]:
    """RELEASE_PROVENANCE.json beside the file, or inside a .tar.gz (read, never
    extracted). A DMG's or EXE's embedded copy cannot be read here."""
    beside = f.parent / _PROVENANCE
    if beside.exists():
        return json.loads(beside.read_text()), "beside the artifact"
    if f.name.endswith(".tar.gz"):
        with tarfile.open(f, "r:gz") as tar:
            for m in tar:
                if m.isfile() and m.name.count("/") == 1 and m.name.endswith("/" + _PROVENANCE):
                    return json.loads(tar.extractfile(m).read()), "inside the tarball"
    return None, "no RELEASE_PROVENANCE.json beside the artifact or readable inside it"


def package_artifacts(root: Path, sha: str, artifact_name: str = "") -> list[dict]:
    """One row per packaged file, recording filename, embedded SHA,
    architecture, OS, checksum and signing status. Only facts the build wrote
    down are recorded: RELEASE_PROVENANCE.json has source_sha and architecture
    but no OS and no signing or notarization field, so those are NOT_RUN with
    the reason, never read off an artifact's name."""
    files = sorted(f for f in root.rglob("*") if f.is_file() and f.name.endswith(PACKAGE_SUFFIXES))
    rows = []
    for f in files:
        prov, where = _provenance_for(f)
        embedded = (prov or {}).get("source_sha")
        if embedded and embedded != sha:
            raise ShaMismatch(f"{f.name} embeds {embedded[:12]}, not {sha[:12]}")
        checksum = _checksum(f)
        info = {
            "artifact": artifact_name, "filename": f.name,
            "embedded_sha": embedded or {"status": "NOT_RUN", "reason": where},
            "architecture": (prov or {}).get("architecture") or {"status": "NOT_RUN", "reason": where},
            "os": (prov or {}).get("os") or {"status": "NOT_RUN", "reason": "RELEASE_PROVENANCE.json records no OS"},
            "checksum": checksum,
            "signing": ({"status": "RECORDED", "value": prov["signing"]} if (prov or {}).get("signing") else
                        {"status": "NOT_RUN", "reason": "RELEASE_PROVENANCE.json records no signing or notarization status"}),
            "not_for_distribution_notice": (f.parent / "NOT_FOR_DISTRIBUTION.txt").exists(),
        }
        if checksum["status"] == "FAIL":
            st, why = "FAIL", "checksum does not match its .sha256 sidecar"
        elif prov is not None and prov.get("prior_qualification_carries_to_this_sha") is not False:
            st, why = "FAIL", "provenance claims prior qualification carries over"
        elif checksum["status"] == "NOT_RUN":
            st, why = "NOT_RUN", checksum["reason"]
        elif not embedded:
            st, why = "NOT_RUN", f"embedded SHA: {where}"
        else:
            st, why = "PASS", "embedded SHA, architecture and checksum bound to this SHA"
        rows.append(_r("release_provenance", f"package/{f.name}", st, sha, why, package=info))
    return rows


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
