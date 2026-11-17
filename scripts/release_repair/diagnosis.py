"""Build the trusted `diagnosis` event from one named run of a diagnosis workflow.

Only the trusted `record` job runs this, from its checkout of main. The
coordinator never types a diagnosis: intake.py refuses a `diagnosis` event
submitted as event_json. This module records facts read from the run and its
artifacts; the controller decides what they are worth (h_diagnosis), so a
run of the wrong workflow, for the wrong SHA, or on an environment that does
not match the pins is refused there with a named reason.

Artifact format (webkit-reload-diagnosis.yml's minimal job, one artifact per
Playwright version, named <artifact_prefix><playwright>-<sha>):
- results.json: {"env", "versions", "repeats", "tally": {"<engine>/<variant>":
  {"crashed", "runs", "not_run"}}, "runs": [{"engine", "variant", "outcome"}]}
- runner.txt: sw_vers output plus "candidate: <sha>" and a
  "verified: playwright=... webkit=... (expected ...) node=... macos=... arch=..." line.
Nothing else in the artifact (traces, sanitized crash summaries, the log) is
read here.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release_repair import artifacts  # noqa: E402
from release_repair import policy as policy_mod  # noqa: E402

_PAIR = re.compile(r"(\w+)=(\S+)")
_VERSION_SHA = re.compile(r"^(?P<pw>\d+\.\d+\.\d+)-(?P<sha>[0-9a-f]{40})$")


def parse_runner(text: str) -> dict:
    """The candidate line and the LAST verified line (the step that checks the pins)."""
    candidate, verified = None, None
    for line in text.splitlines():
        if line.startswith("candidate:"):
            candidate = line.split(":", 1)[1].strip()
        elif line.startswith("verified:"):
            verified = {k: v for k, v in _PAIR.findall(line.split(":", 1)[1])}
    return {"candidate": candidate, "verified": verified}


def parse_results(data: dict) -> dict:
    """Per-variant tallies, and the variants an engine could not run, with reasons."""
    tallies = {}
    for key, t in sorted((data.get("tally") or {}).items()):
        tallies[str(key)] = {k: int(t.get(k, 0) or 0) for k in ("crashed", "runs", "not_run")}
    reasons: dict[str, str] = {}
    for r in data.get("runs") or []:
        outcome = str(r.get("outcome", ""))
        if outcome.startswith("not_run"):
            reasons.setdefault(f"{r.get('engine')}/{r.get('variant')}", outcome.split(":", 1)[-1].strip()[:120])
    not_run = [{"variant": k, "reason": reasons.get(k, "the engine could not run this variant")}
               for k, t in tallies.items() if t["not_run"]]
    return {"tallies": tallies, "not_run": not_run}


def read_artifact(root: Path) -> dict:
    out: dict = {"results_present": False, "runner_present": False}
    runner = next(iter(sorted(root.rglob("runner.txt"))), None)
    if runner is not None:
        out["runner_present"] = True
        out.update(parse_runner(runner.read_text(errors="replace")))
    results = next(iter(sorted(root.rglob("results.json"))), None)
    if results is not None:
        try:
            out.update(parse_results(json.loads(results.read_text())))
            out["results_present"] = True
        except (ValueError, AttributeError, TypeError):
            out["results_error"] = "results.json did not parse"
    return out


def build(run: dict, found: dict[str, list[Path]], task_id: str, prefix: str | None) -> dict:
    """`found` maps an artifact name to the directories it was extracted into
    (more than one means an ambiguous run, which the controller refuses)."""
    versions, ambiguous = {}, []
    for name, dirs in sorted(found.items()):
        if prefix is None or not name.startswith(prefix):
            continue
        m = _VERSION_SHA.match(name[len(prefix):])
        if not m:
            continue
        if len(dirs) != 1 or m["pw"] in versions:
            ambiguous.append(name)
            continue
        versions[m["pw"]] = {"artifact": name, "artifact_sha": m["sha"], **read_artifact(dirs[0])}
    return {"kind": "diagnosis", "event_id": f"diagnosis-{task_id}-{run.get('id')}-{run.get('run_attempt')}",
            "task_id": task_id,
            "run": {"run_id": str(run.get("id")), "run_attempt": str(run.get("run_attempt")),
                    "workflow_path": run.get("path"), "head_sha": run.get("head_sha"),
                    "head_branch": run.get("head_branch"), "event": run.get("event"),
                    "status": run.get("status"), "conclusion": run.get("conclusion")},
            "versions": versions, "ambiguous": ambiguous}


def collect(repo: str, token: str, run_id: str, task_id: str, pol) -> dict:
    run = artifacts._get(f"https://api.github.com/repos/{repo}/actions/runs/{run_id}", token)
    prefix = next((d["artifact_prefix"] for d in pol.trusted_diagnoses() if d["workflow"] == run.get("path")), None)
    found: dict[str, list[Path]] = {}
    keep = tempfile.mkdtemp(prefix="rr-diagnosis-")
    if prefix is not None and run.get("status") == "completed":
        arts = artifacts._get(f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100", token)
        for i, a in enumerate(arts.get("artifacts", [])):
            if a.get("expired") or not str(a.get("name", "")).startswith(prefix):
                continue
            d = Path(keep) / str(i)
            d.mkdir()
            zipfile.ZipFile(io.BytesIO(artifacts._get(a["archive_download_url"], token, raw=True))).extractall(d)
            found.setdefault(a["name"], []).append(d)
    return build(run, found, task_id, prefix)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--policy", default=str(policy_mod.DEFAULT_POLICY))
    a = p.parse_args()
    if not re.fullmatch(r"\d{1,20}", a.run):
        sys.exit("diagnosis run id must be digits")
    ev = collect(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"], a.run, a.task_id, policy_mod.load(a.policy))
    Path(a.out).write_text(json.dumps(ev, indent=2) + "\n")
    print(json.dumps({"event_id": ev["event_id"], "versions": sorted(ev["versions"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
