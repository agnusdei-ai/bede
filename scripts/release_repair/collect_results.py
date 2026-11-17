"""Turn the artifacts of finished, trusted CI runs into one `results` event.

Only runs of the named workflows on the exact candidate SHA are read. Each
artifact goes through qualification_adapter, so absence stays NOT_RUN.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release_repair import artifacts  # noqa: E402
from release_repair import qualification_adapter as qa  # noqa: E402

TRUSTED_WORKFLOWS = {
    ".github/workflows/qualification.yml": "qualification",
    ".github/workflows/cross-platform-browser-journeys.yml": "journeys",
    ".github/workflows/test.yml": "qa",
    ".github/workflows/frontend-tests.yml": "qa",
    ".github/workflows/build-bede-operator.yml": "package",
}


def adapt(kind: str, name: str, root: Path, sha: str) -> list[dict]:
    if kind == "qualification":
        return qa.qualification_matrix(root, sha)
    if kind == "journeys":
        return qa.browser_journeys(root, sha)
    if kind == "qa":
        scope = "backend" if "backend" in name else "homeschool-tutor"
        reports = list(root.rglob("*.json"))
        return qa.qa_runner(reports[0] if reports else root / "missing.json", sha, scope)
    if kind == "package":
        # One row per packaged file (qualification_adapter.package_artifacts).
        # An artifact with no package in it (the browser walkthrough) adds none.
        return qa.package_artifacts(root, sha, name)
    return []


def collect(repo: str, token: str, run_ids: list[str], sha: str) -> dict:
    rows: list[dict] = []
    for rid in run_ids:
        run = artifacts._get(f"https://api.github.com/repos/{repo}/actions/runs/{rid}", token)
        kind = TRUSTED_WORKFLOWS.get(run.get("path"))
        if kind is None:
            rows.append(qa._r("collector", f"run/{rid}", "INFRA_ERROR", sha, "not a trusted workflow"))
            continue
        if run.get("head_sha") != sha:
            rows.append(qa._r("collector", f"run/{rid}", "INFRA_ERROR", sha, "run is for another SHA"))
            continue
        if run.get("status") != "completed":
            rows.append(qa._r("collector", f"run/{rid}", "NOT_RUN", sha, "run not finished"))
            continue
        arts = artifacts._get(f"https://api.github.com/repos/{repo}/actions/runs/{rid}/artifacts?per_page=100", token)
        for a in arts.get("artifacts", []):
            if a.get("expired"):
                continue
            with tempfile.TemporaryDirectory() as d:
                zipfile.ZipFile(io.BytesIO(artifacts._get(a["archive_download_url"], token, raw=True))).extractall(d)
                try:
                    rows += adapt(kind, a["name"], Path(d), sha)
                except qa.ShaMismatch as exc:
                    rows.append(qa._r("collector", a["name"], "INFRA_ERROR", sha, str(exc)))
    return {"kind": "results", "sha": sha, "results": rows}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", required=True)
    p.add_argument("--sha", required=True)
    p.add_argument("--event-id", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    ev = collect(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"],
                 [r for r in a.runs.split(",") if r.strip()], a.sha)
    ev["event_id"] = a.event_id
    Path(a.out).write_text(json.dumps(ev, indent=2) + "\n")
    print(json.dumps({"results": len(ev["results"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
