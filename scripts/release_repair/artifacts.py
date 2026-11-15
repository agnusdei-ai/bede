"""Find, verify and fetch a cycle's snapshot artifact from the trusted workflow.

`latest` chooses the snapshot to load (state_store.choose_latest refuses
missing, expired and ambiguous ones) and downloads it. `check-unchanged`
runs just before publishing: if a newer snapshot has appeared since this run
loaded its own, publishing is refused (exit 3) and the coordinator retries.
That detects a race; it cannot prevent one.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release_repair import state_store  # noqa: E402

_SEQ = re.compile(r"^release-repair-state-(?P<cycle>[0-9a-z-]+)-(?P<seq>\d+)$")


def _get(url: str, token: str, raw: bool = False):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read() if raw else json.load(r)


def from_record_job(created_at, record_started_at) -> bool:
    """An artifact uploaded before the trusted `record` job started cannot have
    come from it. The `candidate` job runs candidate code and finishes, with its
    processes cleaned up, before `record` starts, so a snapshot it forged would
    be dated earlier and is refused. ISO-8601 UTC strings compare in order."""
    return bool(created_at and record_started_at and created_at >= record_started_at)


def listing(repo: str, token: str, cycle: str) -> list[dict]:
    out, page, runs = [], 1, {}
    while True:
        data = _get(f"https://api.github.com/repos/{repo}/actions/artifacts?per_page=100&page={page}", token)
        for a in data.get("artifacts", []):
            m = _SEQ.match(a["name"])
            if not m or m["cycle"] != cycle:
                continue
            run_id = a.get("workflow_run", {}).get("id")
            if run_id not in runs:
                run = _get(f"https://api.github.com/repos/{repo}/actions/runs/{run_id}", token)
                jobs = _get(f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs?per_page=100", token)
                run["record_started_at"] = next((j.get("started_at") for j in jobs.get("jobs", [])
                                                 if j.get("name") == "record"), None)
                runs[run_id] = run
            run = runs[run_id]
            out.append({"id": a["id"], "name": a["name"], "state_sequence": int(m["seq"]),
                        "expired": a.get("expired", False), "head_branch": run.get("head_branch"),
                        "workflow_path": run.get("path"), "archive_download_url": a["archive_download_url"],
                        "from_record_job": from_record_job(a.get("created_at"), run.get("record_started_at"))})
        if len(data.get("artifacts", [])) < 100:
            return out
        page += 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["latest", "check-unchanged"])
    p.add_argument("--cycle", required=True)
    p.add_argument("--out")
    p.add_argument("--loaded-sequence", type=int)
    a = p.parse_args()
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"]
    try:
        chosen = state_store.choose_latest(listing(repo, token, a.cycle), cycle_id=a.cycle)
    except state_store.SnapshotError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}))
        return 2
    if a.command == "check-unchanged":
        if chosen["state_sequence"] != a.loaded_sequence:
            print(json.dumps({"status": "INFRA_ERROR", "reason": "a newer snapshot was published meanwhile",
                              "latest": chosen["state_sequence"], "loaded": a.loaded_sequence}))
            return 3
        print(json.dumps({"status": "unchanged", "sequence": chosen["state_sequence"]}))
        return 0
    blob = _get(chosen["archive_download_url"], token, raw=True)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    zipfile.ZipFile(io.BytesIO(blob)).extractall(a.out)
    print(json.dumps({"status": "loaded", "name": chosen["name"], "sequence": chosen["state_sequence"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
