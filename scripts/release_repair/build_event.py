"""Assemble the trusted `verification` event from facts this run produced.

Inputs are the trusted validator's report, the regression report from the
isolated candidate job, and the run's own identifiers. Nothing an agent
wrote is read here.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release_repair import policy as policy_mod  # noqa: E402


def verification(task_id, branch, base, resolved, validation, regression, run) -> dict:
    return {"kind": "verification", "event_id": f"verify-{task_id}-{resolved[:12]}-{run['run_id']}-{run['run_attempt']}",
            "task_id": task_id, "branch": branch, "base_sha": base, "resolved_sha": resolved,
            "validation": {k: validation.get(k) for k in ("ok", "refused", "needs_authorization", "violations")},
            "regression": {k: bool(regression.get(k)) for k in ("pre_fix_failed", "post_fix_passed", "adjacent_passed")},
            "run": run}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    for a in ("task-id", "branch", "base", "resolved", "validation", "regression", "run-id", "run-attempt",
              "controller-revision", "out"):
        p.add_argument("--" + a, required=True)
    p.add_argument("--policy", default=str(policy_mod.DEFAULT_POLICY))
    a = p.parse_args()
    pol = policy_mod.load(a.policy)
    reg_path = Path(a.regression)
    regression = json.loads(reg_path.read_text()) if reg_path.exists() else {}
    ev = verification(a.task_id, a.branch, a.base, a.resolved, json.loads(Path(a.validation).read_text()), regression,
                      {"run_id": a.run_id, "run_attempt": a.run_attempt,
                       "controller_revision": a.controller_revision, "policy_revision": pol.revision})
    Path(a.out).write_text(json.dumps(ev, indent=2) + "\n")
    print(json.dumps({"event_id": ev["event_id"], "regression": ev["regression"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
