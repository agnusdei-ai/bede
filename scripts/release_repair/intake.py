"""The record job's intake: what the coordinator may submit, and the facts only
this trusted job adds.

`screen` runs over event_json, the coordinator's input. A kind only the trusted
job builds (`diagnosis`, `verification`, `results`) or a field only it fills
(`ancestry`) is never accepted from there: the event is replaced by a
`coordinator_refused` event the controller refuses and records, so the
refusal is visible in the event log rather than silently dropped.

`enrich` runs after the saved state is loaded. For an owner's
`resolved_outside_loop` event it checks, with git, whether the fixing merge
SHA is an ancestor of the CURRENT candidate, and records that fact. The
controller refuses the event without it.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release_repair import state_store  # noqa: E402

TRUSTED_ONLY_KINDS = frozenset({"diagnosis", "verification", "results"})
TRUSTED_FIELDS = frozenset({"ancestry"})
_SHA = re.compile(r"^[0-9a-f]{40}$")


def screen(events: list[dict]) -> list[dict]:
    out = []
    for e in events:
        kind = e.get("kind")
        reason = None
        if kind in TRUSTED_ONLY_KINDS:
            reason = f"{kind}_is_built_only_by_the_record_job"
        elif TRUSTED_FIELDS & set(e):
            reason = "field_" + ",".join(sorted(TRUSTED_FIELDS & set(e))) + "_is_filled_only_by_the_record_job"
        out.append({"kind": "coordinator_refused", "event_id": e.get("event_id"), "refused_kind": kind,
                    "reason": reason} if reason else e)
    return out


def git_is_ancestor(repo_url: str, token: str | None, ancestor: str, descendant: str, workdir: Path):
    """True/False from `git merge-base --is-ancestor`; None when git could not answer."""
    if not (_SHA.match(ancestor) and _SHA.match(descendant)):
        return None
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    if token:
        cred = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                   GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {cred}")
    bare = workdir / "ancestry.git"
    try:
        if not bare.exists():
            subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, env=env, capture_output=True)
        subprocess.run(["git", "-C", str(bare), "fetch", "-q", "--no-tags", "--filter=blob:none", repo_url,
                        ancestor, descendant], check=True, env=env, capture_output=True, timeout=600)
        code = subprocess.run(["git", "-C", str(bare), "merge-base", "--is-ancestor", ancestor, descendant],
                              env=env, capture_output=True).returncode
    except (OSError, subprocess.SubprocessError):
        return None
    return {0: True, 1: False}.get(code)


def enrich(events: list[dict], candidate_sha: str, is_ancestor) -> list[dict]:
    out = []
    for e in events:
        if e.get("kind") == "resolved_outside_loop":
            merge = str(e.get("merge_sha", ""))
            e = {**e, "ancestry": {"merge_sha": merge, "candidate_sha": candidate_sha,
                                   "is_ancestor": is_ancestor(merge, candidate_sha), "checked_by": "record"}}
        out.append(e)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["screen", "enrich"])
    p.add_argument("--events", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--snapshot-in")
    p.add_argument("--work")
    p.add_argument("--cycle")
    a = p.parse_args()
    loaded = json.loads(Path(a.events).read_text())
    events = loaded if isinstance(loaded, list) else [loaded]
    if a.command == "screen":
        events = screen(events)
    elif any(e.get("kind") == "resolved_outside_loop" for e in events):
        work = Path(a.work)
        store = state_store.load(Path(a.snapshot_in), work / "state", cycle_id=a.cycle)
        candidate = (store.get("state") or {}).get("candidate_sha", "")
        repo_url = os.environ.get("REPO_URL", "")
        events = enrich(events, candidate, lambda anc, desc: git_is_ancestor(
            repo_url, os.environ.get("GH_TOKEN"), anc, desc, work))
    Path(a.out).write_text(json.dumps(events) + "\n")
    print(json.dumps({"command": a.command, "events": len(events),
                      "refused": [e["event_id"] for e in events if e.get("kind") == "coordinator_refused"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
