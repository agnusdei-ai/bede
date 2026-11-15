"""Shared helpers for the release-repair controller tests (not a test module)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from release_repair import controller, policy, state_store  # noqa: E402

A = "a" * 40
B = "b" * 40
C = "c" * 40
WEBKIT = "webkit-original-page-reload-crash"


def pol():
    return policy.load(REPO / "config" / "release-repair.json")


def acc(name="test-only.json"):
    return policy.load_acceptance(REPO / "config" / "acceptance" / name)


class Cycle:
    """A controller cycle in a temp dir, driven one event at a time."""

    def __init__(self, tmp: Path, acceptance="test-only.json", cycle="c1", sha=A, now=1000.0):
        self.pol, self.acc, self.now = pol(), acc(acceptance), now
        self.store = state_store.Store(tmp / "work")
        self.n = 0
        out = self.ev("start", cycle_id=cycle, candidate_sha=sha, controller_revision="trusted-rev")
        assert out["accepted"], out

    def ev(self, kind, **fields):
        self.n += 1
        event = {"kind": kind, "event_id": fields.pop("event_id", f"e{self.n}"), **fields}
        return controller.apply(self.store, event, self.pol, self.acc, now=self.now)

    @property
    def s(self):
        return self.store.get("state")

    def task_for(self, key, active=True):
        ids = self.s["failures"][key]["task_ids"]
        tasks = [self.s["tasks"][t] for t in ids]
        if active:
            tasks = [t for t in tasks if t["status"] not in controller.gates.TERMINAL_TASK]
        return tasks[-1]

    def lease(self, tid):
        t = self.s["tasks"][tid]
        return {"lease_id": t["lease_id"], "generation": t["lease_generation"]}

    def run_role(self, tid, role, **result):
        assert self.ev("assign", task_id=tid, role=role, session_id=f"session_{role}_{tid}",
                       replace_session=True)["accepted"]
        return self.ev("agent_result", task_id=tid, lease=self.lease(tid),
                       result={"kind": "AgentResult", "task_id": tid, "agent_role": role, "summary": "x", **result})

    def verify(self, tid, *, pre=True, post=True, adjacent=True, validation=None, **over):
        t = self.s["tasks"][tid]
        return self.ev("verification", task_id=tid, branch=over.get("branch", t["branch"]),
                       base_sha=over.get("base_sha", t["base_sha"]), resolved_sha=over.get("resolved_sha", C),
                       validation=validation or {"ok": True, "refused": False, "needs_authorization": False, "violations": []},
                       regression={"pre_fix_failed": pre, "post_fix_passed": post, "adjacent_passed": adjacent},
                       run={"run_id": "r1", "run_attempt": "1", "controller_revision": "trusted-rev",
                            "policy_revision": over.get("policy_revision", self.pol.revision)})

    def drive_to_review(self, tid, branch=None):
        assert self.run_role(tid, "triage", status="done")["accepted"]
        assert self.run_role(tid, "reproduce", status="reproduced")["accepted"]
        assert self.run_role(tid, "repair", status="patch_pushed",
                             branch=branch or f"release-repair/c1/{tid}")["accepted"]
        assert self.verify(tid)["accepted"]
        assert self.s["tasks"][tid]["status"] == "REVIEWING"


def fail_row(check, sha=A, source="browser_journeys", **extra):
    return {"source": source, "check": check, "status": "FAIL", "sha": sha, "detail": "Page crashed", **extra}


def pass_row(check, sha=A, source="browser_journeys", **extra):
    return {"source": source, "check": check, "status": "PASS", "sha": sha, "detail": "", **extra}
