"""Reconcile a cycle's state against its pinned acceptance manifest.

Only results for the CURRENT candidate SHA count. Missing evidence is
NOT_RUN and blocks. Every blocker keeps its own reason code, so a cycle that
ran out of repair budget AND lacks physical Mac evidence reports both.
READY_FOR_RELEASE_DECISION is never release approval.
"""
from __future__ import annotations

ACTIVE_TASK = ("TRIAGING", "REPRODUCING", "REPAIRING", "VERIFYING", "REVIEWING", "READY_TO_INTEGRATE")
TERMINAL_TASK = ("FIXED", "INTEGRATED", "BLOCKED", "BUDGET_EXHAUSTED", "SUPERSEDED", "CANCELLED")
TERMINAL_CYCLE = ("READY_FOR_RELEASE_DECISION", "BUDGET_EXHAUSTED", "BLOCKED", "CANCELLED")
STAGE_FOR = {"TRIAGING": "TRIAGING", "REPRODUCING": "REPRODUCING", "REPAIRING": "REPAIRING",
             "VERIFYING": "VERIFYING", "REVIEWING": "REVIEWING", "READY_TO_INTEGRATE": "INTEGRATING"}
STAGE_ORDER = ["TRIAGING", "REPRODUCING", "REPAIRING", "VERIFYING", "REVIEWING", "INTEGRATING"]


def _gate_status(gate: dict, state: dict) -> str:
    sha = state.get("candidate_sha")
    src = gate["source"]
    if src == "review":
        tasks = [t for t in state["tasks"].values() if t["status"] in ("INTEGRATED", "READY_TO_INTEGRATE", "FIXED")]
        if any(state.get("reviews", {}).get(t["task_id"]) != "approve" for t in tasks):
            return "NOT_RUN"
        return "PASS"
    rows = [r for r in state.get("results", []) if r["source"] == src and r["sha"] == sha]
    for key in ("scope", "os", "browser"):
        if key in gate:
            rows = [r for r in rows if r.get(key) == gate[key]]
    if not rows:
        return "NOT_RUN"
    statuses = {r["status"] for r in rows}
    if statuses <= {"PASS", "SKIP"} and "PASS" in statuses:
        return "PASS"
    if "FAIL" in statuses:
        return "FAIL"
    if "INFRA_ERROR" in statuses:
        return "INFRA_ERROR"
    return "NOT_RUN"


def evaluate(state: dict, acceptance: dict) -> dict:
    gates = {g["id"]: _gate_status(g, state) for g in acceptance["gates"] if g.get("required")}
    blockers: list[dict] = []
    for f in state["failures"].values():
        if f["release_blocking"] and f["status"] != "FIXED_VERIFIED":
            blockers.append({"code": "release_blocking_failure_open", "failure": f["key"]})
    tasks = list(state["tasks"].values())
    for code, st in (("repair_budget_exhausted", "BUDGET_EXHAUSTED"), ("task_blocked", "BLOCKED"),
                     ("awaiting_owner_authorization", "AWAITING_AUTHORIZATION")):
        for t in tasks:
            if t["status"] == st:
                blockers.append({"code": code, "task": t["task_id"], "detail": t.get("reason")})
    kinds = {g["id"]: g for g in acceptance["gates"]}
    for gid, st in gates.items():
        if st == "PASS":
            continue
        g = kinds[gid]
        if g["kind"] == "physical":
            blockers.append({"code": "real_safari_evidence_missing" if g.get("browser") == "safari"
                             else "physical_mac_evidence_missing", "gate": gid, "status": st})
        else:
            blockers.append({"code": "gate_not_passed", "gate": gid, "status": st})

    active = [t for t in tasks if t["status"] in ACTIVE_TASK]
    if state.get("cancelled"):
        status = "CANCELLED"
    elif not blockers and gates and all(v == "PASS" for v in gates.values()):
        status = "READY_FOR_RELEASE_DECISION"
    elif active:
        status = min((STAGE_FOR[t["status"]] for t in active), key=STAGE_ORDER.index)
    elif any(t["status"] == "AWAITING_AUTHORIZATION" for t in tasks):
        status = "AWAITING_AUTHORIZATION"
    elif any(b["code"] == "repair_budget_exhausted" for b in blockers):
        status = "BUDGET_EXHAUSTED"
    elif any(b["code"] == "task_blocked" for b in blockers):
        status = "BLOCKED"
    elif any(v == "NOT_RUN" and kinds[g]["kind"] != "physical" for g, v in gates.items()):
        status = "QUALIFYING"
    elif any(b["code"].endswith("_evidence_missing") for b in blockers):
        status = "AWAITING_PHYSICAL_VERIFICATION"
    else:
        status = "ASSEMBLING_EVIDENCE"
    return {"gates": gates, "blockers": blockers, "status": status,
            "release_status": "READY_FOR_RELEASE_DECISION" if status == "READY_FOR_RELEASE_DECISION" else "HOLD",
            "terminal": status in TERMINAL_CYCLE}
