"""The release-repair controller: a deterministic state machine.

Actions: start, record, status, reconcile, cancel, envelope.

A model's claim is never evidence. AgentResults are stored as claims; the
transitions that matter (verified, refused, budget spent) are driven only by
facts the trusted CI job produced, bound to the candidate SHA, the controller
revision, the policy revision and the producing run.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release_repair import gates, leases, sanitize  # noqa: E402
from release_repair import policy as policy_mod  # noqa: E402
from release_repair import state_store  # noqa: E402

ROLES = ("triage", "reproduce", "repair", "review")
ROLE_FOR_STATUS = {"TRIAGING": "triage", "REPRODUCING": "reproduce", "REPAIRING": "repair", "REVIEWING": "review"}
MAX_EVIDENCE = 25
EXIT_OK, EXIT_BLOCKED, EXIT_INFRA = 0, 2, 3


class Refused(Exception):
    pass


# ── failure matching ─────────────────────────────────────────────────────────
def _failure_key(result: dict, pol) -> tuple[str, dict | None]:
    check = f"{result['check']}"
    for rule in pol.failure_rules():
        sig = rule.get("signature", {})
        if not fnmatch.fnmatchcase(check, sig.get("check", "\0")):
            continue
        frames = result.get("crash_frames") or []
        frame = sig.get("crash_frame")
        if frame and frames and frame not in frames:
            continue
        return rule["key"], rule
    return f"{result['source']}:{check}", None


def _new_failure(key: str, rule: dict | None) -> dict:
    rule = rule or {}
    return {"key": key, "disposition": rule.get("disposition", "investigate"),
            "release_blocking": bool(rule.get("release_blocking", True)),
            "suppress_repair": bool(rule.get("suppress_repair", False)) and bool(rule.get("owner_approval_ref")),
            "root_cause": rule.get("root_cause", "unconfirmed"), "status": "OPEN",
            "evidence": list(rule.get("known_evidence", []))[:MAX_EVIDENCE], "occurrences": 0, "task_ids": []}


def _open_task(state: dict, failure: dict, base_sha: str, carry_attempt: int = 0) -> dict:
    n = len(state["tasks"]) + 1
    task = {"task_id": f"t{n:03d}-{failure['key'][:40]}".replace(":", "-").replace("/", "-").lower(),
            "failure_key": failure["key"], "status": "TRIAGING", "attempt": carry_attempt,
            "base_sha": base_sha, "branch": None, "resolved_sha": None, "session_ids": {},
            "lease_id": None, "lease_generation": 0, "lease_expires_at": 0, "claims": [], "reason": None}
    state["tasks"][task["task_id"]] = task
    failure["task_ids"].append(task["task_id"])
    return task


def _has_active_task(state, failure) -> bool:
    return any(state["tasks"][t]["status"] not in gates.TERMINAL_TASK for t in failure["task_ids"])


def _spend(task: dict, pol, reason: str):
    task["attempt"] += 1
    task["reason"] = reason
    task["status"] = "BUDGET_EXHAUSTED" if task["attempt"] >= pol.repair_budget else "REPAIRING"
    task["lease_id"] = None


# ── handlers ─────────────────────────────────────────────────────────────────
def h_start(state, ev, pol, acc, now):
    if state is not None:
        raise Refused("cycle_already_started")
    sha = ev["candidate_sha"]
    if len(sha) != 40:
        raise Refused("candidate_sha_must_be_40_hex")
    state = {"cycle_id": ev["cycle_id"], "candidate_sha": sha, "base_sha": sha,
             "policy_revision": pol.revision, "controller_revision": ev.get("controller_revision"),
             "acceptance_label": acc["label"], "acceptance_revision": acc["_revision"], "test_only": acc["test_only"],
             "failures": {}, "tasks": {}, "results": [], "reviews": {}, "authorizations": [],
             "infra_retries": {}, "notifications": [{"kind": "started", "at": now}], "cancelled": False,
             "submitted": {}}
    for rule in pol.failure_rules():
        if rule.get("disposition") == "investigate" and not rule.get("suppress_repair"):
            f = state["failures"][rule["key"]] = _new_failure(rule["key"], rule)
            _open_task(state, f, sha)
    return state


def h_results(state, ev, pol, acc, now):
    if ev["sha"] != state["candidate_sha"]:
        raise Refused("results_for_a_superseded_candidate")
    rows = sanitize.obj(ev["results"])
    keyset = {(r["source"], r["check"], r.get("os"), r.get("scope")) for r in rows}
    state["results"] = [r for r in state["results"] if not (r["sha"] == ev["sha"] and
                        (r["source"], r["check"], r.get("os"), r.get("scope")) in keyset)] + rows
    for r in rows:
        if r["status"] == "INFRA_ERROR":
            k = f"{r['source']}:{r['check']}"
            state["infra_retries"][k] = state["infra_retries"].get(k, 0) + 1
            continue
        if r["status"] != "FAIL":
            continue
        key, rule = _failure_key(r, pol)
        f = state["failures"].get(key)
        if f is None:
            f = state["failures"][key] = _new_failure(key, rule)
        f["occurrences"] += 1
        if f["status"] in ("FIXED_VERIFIED", "REPAIRED_PENDING_QUALIFICATION"):
            f["status"] = "OPEN"          # it came back: a regression is a new investigation
        f["evidence"] = (f["evidence"] + [f"{r['source']} {r['check']} @{r['sha'][:12]}: {r.get('detail','')}"])[-MAX_EVIDENCE:]
        if not f["suppress_repair"] and not _has_active_task(state, f):
            _open_task(state, f, state["candidate_sha"],
                       carry_attempt=max([state["tasks"][t]["attempt"] for t in f["task_ids"]
                                          if state["tasks"][t]["status"] == "SUPERSEDED"] or [0]))
    # a repaired failure whose checks now pass on this candidate is verified fixed
    for f in state["failures"].values():
        if f["status"] == "REPAIRED_PENDING_QUALIFICATION":
            mine = [r for r in rows if _failure_key(r, pol)[0] == f["key"]]
            if mine and all(r["status"] == "PASS" for r in mine):
                f["status"] = "FIXED_VERIFIED"
    return state


def h_assign(state, ev, pol, acc, now):
    t = _task(state, ev["task_id"])
    role = ROLE_FOR_STATUS.get(t["status"])
    if role is None or ev["role"] != role:
        raise Refused(f"task_in_{t['status']}_cannot_take_role_{ev['role']}")
    if role in t["session_ids"] and not ev.get("replace_session"):
        raise Refused("session_already_assigned")   # resume, do not duplicate
    lease = leases.issue(t, now, pol.lease_ttl)
    t.update(lease_id=lease["lease_id"], lease_generation=lease["generation"], lease_expires_at=lease["expires_at"])
    t["session_ids"][role] = ev["session_id"]
    return state


def h_agent_result(state, ev, pol, acc, now):
    t = _task(state, ev["task_id"])
    why = leases.check(t, ev.get("lease"), now)
    if why:
        raise Refused(why)
    res = sanitize.obj(ev["result"])
    role = ROLE_FOR_STATUS.get(t["status"])
    if res.get("agent_role") != role:
        raise Refused("result_role_does_not_match_task")
    t["claims"] = (t["claims"] + [{"role": role, "status": res.get("status"), "summary": res.get("summary")}])[-10:]
    st = res.get("status")
    if role == "triage":
        t["status"] = "REPRODUCING" if st == "done" else "BLOCKED"
    elif role == "reproduce":
        t["status"] = {"reproduced": "REPAIRING", "blocked": "BLOCKED"}.get(st, "BLOCKED")
    elif role == "repair":
        if st != "patch_pushed" or not res.get("branch"):
            _spend(t, pol, "repair_produced_no_branch")
        else:
            t["branch"], t["status"] = res["branch"], "VERIFYING"
    elif role == "review":
        verdict = res.get("verdict")
        if verdict == "approve":
            state["reviews"][t["task_id"]] = "approve"
            t["status"] = "READY_TO_INTEGRATE"
        elif verdict == "changes_requested":
            state["reviews"][t["task_id"]] = "changes_requested"
            _spend(t, pol, "review_requested_changes")
        else:
            t["status"], t["reason"] = "AWAITING_AUTHORIZATION", "reviewer_escalated"
    if st == "blocked" or t["status"] == "BLOCKED":
        t["reason"] = res.get("blocked_reason") or t["reason"] or "agent_reported_blocked"
    t["lease_id"] = None
    return state


def h_verification(state, ev, pol, acc, now):
    """Facts from the trusted CI job. The only route to REVIEWING."""
    t = _task(state, ev["task_id"])
    if t["status"] != "VERIFYING":
        raise Refused("task_not_awaiting_verification")
    run = ev.get("run", {})
    if run.get("policy_revision") != state["policy_revision"]:
        raise Refused("verified_under_a_different_policy_revision")
    if ev.get("branch") != t["branch"]:
        raise Refused("verification_for_another_branch")
    if ev.get("base_sha") != t["base_sha"]:
        raise Refused("verification_against_a_stale_base")
    if len(ev.get("resolved_sha", "")) != 40:
        raise Refused("branch_not_resolved_to_a_sha")
    t["resolved_sha"] = ev["resolved_sha"]
    t["verification_run"] = {k: run.get(k) for k in ("run_id", "run_attempt", "controller_revision", "policy_revision")}
    v, reg = ev.get("validation", {}), ev.get("regression", {})
    if v.get("refused"):
        _spend(t, pol, "validator_refused:" + ",".join(x["code"] for x in v.get("violations", [])))
    elif v.get("needs_authorization"):
        t["status"] = "AWAITING_AUTHORIZATION"
        t["reason"] = "needs_owner:" + ",".join(sorted({x["code"] for x in v["violations"]}))
        t["pending_regression"] = reg
    elif reg.get("pre_fix_failed") and reg.get("post_fix_passed") and reg.get("adjacent_passed"):
        t["status"] = "REVIEWING"
    else:
        _spend(t, pol, "regression_not_demonstrated:" + json.dumps(reg, sort_keys=True))
    return state


def h_authorization(state, ev, pol, acc, now):
    """Only the owner. The coordinator submits this only on the owner's word,
    and owner_ref must point at where they said it."""
    if ev.get("actor") != "owner" or not ev.get("owner_ref"):
        raise Refused("authorization_requires_owner_ref")
    t = _task(state, ev["task_id"])
    if t["status"] != "AWAITING_AUTHORIZATION":
        raise Refused("task_not_awaiting_authorization")
    state["authorizations"].append({k: ev.get(k) for k in ("task_id", "decision", "owner_ref", "codes")})
    if ev["decision"] != "allow":
        t["status"], t["reason"] = "BLOCKED", "owner_denied"
    elif state["reviews"].get(t["task_id"]) == "approve":
        t["status"] = "READY_TO_INTEGRATE"
    else:
        reg = t.pop("pending_regression", {}) or {}
        if reg.get("pre_fix_failed") and reg.get("post_fix_passed") and reg.get("adjacent_passed"):
            t["status"] = "REVIEWING"
        else:
            _spend(t, pol, "regression_not_demonstrated")
    return state


def h_integrated(state, ev, pol, acc, now):
    new = ev["new_candidate_sha"]
    if len(new) != 40:
        raise Refused("candidate_sha_must_be_40_hex")
    for tid in ev["merged_task_ids"]:
        t = _task(state, tid)
        if t["status"] != "READY_TO_INTEGRATE":
            raise Refused(f"{tid}_was_not_reviewed_and_approved")
    for tid in ev["merged_task_ids"]:
        t = state["tasks"][tid]
        t["status"] = "INTEGRATED"
        state["failures"][t["failure_key"]]["status"] = "REPAIRED_PENDING_QUALIFICATION"
    state["candidate_sha"] = new
    for t in list(state["tasks"].values()):
        if t["status"] not in gates.TERMINAL_TASK and t["base_sha"] != new and t["status"] != "AWAITING_AUTHORIZATION":
            t["status"], t["reason"] = "SUPERSEDED", f"candidate moved to {new[:12]}"
            f = state["failures"][t["failure_key"]]
            _open_task(state, f, new, carry_attempt=t["attempt"])
    return state


def h_physical(state, ev, pol, acc, now):
    """A person's physical Mac / Safari record. Owner-attributed, never inferred."""
    if ev.get("actor") != "owner" or not ev.get("owner_ref"):
        raise Refused("physical_evidence_requires_owner_ref")
    import tempfile
    from release_repair import qualification_adapter as qa
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "mac-check-result.json"
        f.write_text(json.dumps(ev["record"]))
        try:
            rows = qa.mac_check(f, state["candidate_sha"])
        except qa.ShaMismatch as exc:
            raise Refused("physical_record_for_another_sha") from exc
    for r in rows:
        r["owner_ref"] = ev["owner_ref"]
    return h_results(state, {"sha": state["candidate_sha"], "results": rows}, pol, acc, now)


def h_cancel(state, ev, pol, acc, now):
    if ev.get("actor") != "owner" or not ev.get("owner_ref"):
        raise Refused("cancel_requires_owner_ref")
    state["cancelled"] = True
    for t in state["tasks"].values():
        if t["status"] not in gates.TERMINAL_TASK:
            t["status"] = "CANCELLED"
    return state


HANDLERS = {"start": h_start, "results": h_results, "assign": h_assign, "agent_result": h_agent_result,
            "verification": h_verification, "authorization": h_authorization, "integrated": h_integrated,
            "physical": h_physical, "cancel": h_cancel}


def _task(state, tid):
    if tid not in state["tasks"]:
        raise Refused("unknown_task")
    return state["tasks"][tid]


# ── apply / summary ──────────────────────────────────────────────────────────
def apply(store: state_store.Store, event: dict, pol, acc, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    kind, eid = event["kind"], event["event_id"]
    if kind not in HANDLERS:
        raise Refused("unknown_event_kind")

    def run(state):
        if state is None and kind != "start":
            raise state_store.SnapshotError("no_state_for_cycle")
        before = json.dumps(state, sort_keys=True)
        try:
            new = HANDLERS[kind](json.loads(before) if state is not None else None, event, pol, acc, now)
        except Refused as exc:
            return state, False, str(exc)
        ev = gates.evaluate(new, acc)
        new["status"], new["blockers"], new["gates"] = ev["status"], ev["blockers"], ev["gates"]
        new["release_status"] = ev["release_status"]
        if ev["terminal"] and not any(n["kind"] == "terminal" for n in new["notifications"]):
            new["notifications"].append({"kind": "terminal", "status": ev["status"], "at": now})
        return new, True, None

    return store.transact(eid, kind, {k: v for k, v in event.items() if k != "result"}, now, run)


def summary(store: state_store.Store) -> dict:
    s = store.get("state") or {}
    return {"kind": "ReleaseRepairSummary", "cycle_id": s.get("cycle_id"), "candidate_sha": s.get("candidate_sha"),
            "status": s.get("status"), "release_status": s.get("release_status", "HOLD"),
            "approved_for_distribution": False,
            "acceptance": {"label": s.get("acceptance_label"), "test_only": s.get("test_only")},
            "gates": s.get("gates", {}), "blockers": s.get("blockers", []),
            "failures": {k: {x: f[x] for x in ("status", "release_blocking", "suppress_repair", "root_cause", "occurrences")}
                         for k, f in s.get("failures", {}).items()},
            "tasks": {k: {x: t.get(x) for x in ("failure_key", "status", "attempt", "base_sha", "branch",
                                                "resolved_sha", "session_ids", "lease_id", "lease_generation", "reason")}
                      for k, t in s.get("tasks", {}).items()},
            "notifications": s.get("notifications", []),
            "events": store.events(), "snapshot": store.get("snapshot")}


def envelope(store, task_id: str, pol=None) -> dict:
    """The RepairTask a coordinator hands a child session."""
    s = store.get("state")
    t = s["tasks"][task_id]
    return {"kind": "RepairTask", "task_id": task_id, "release_cycle_id": s["cycle_id"], "failure_id": t["failure_key"],
            "assignment": {"agent_role": ROLE_FOR_STATUS.get(t["status"]), "branch": f"release-repair/{s['cycle_id']}/{task_id}",
                           "lease_id": t["lease_id"], "lease_generation": t["lease_generation"],
                           "session_id": t["session_ids"].get(ROLE_FOR_STATUS.get(t["status"]))},
            "revision": {"base_sha": t["base_sha"], "policy_sha": s["policy_revision"]},
            "problem": {"evidence_refs": s["failures"][t["failure_key"]]["evidence"],
                        "root_cause_status": s["failures"][t["failure_key"]]["root_cause"]},
            "budget": {"attempt": t["attempt"], "maximum_attempts": pol.repair_budget if pol else None}}


def reconcile(store, submitted: list[str]) -> dict:
    seen = {e["event_id"] for e in store.events()}
    return {"acknowledged": [e for e in submitted if e in seen], "unacknowledged": [e for e in submitted if e not in seen]}


# ── CLI ──────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--action", required=True, choices=["start", "record", "status", "reconcile", "cancel", "envelope"])
    p.add_argument("--cycle", required=True)
    p.add_argument("--snapshot-in")
    p.add_argument("--snapshot-out")
    p.add_argument("--work", required=True)
    p.add_argument("--event", help="JSON file: one event or a list of events")
    p.add_argument("--task")
    p.add_argument("--policy", default=str(policy_mod.DEFAULT_POLICY))
    p.add_argument("--acceptance", default=str(policy_mod.REPO / "config" / "acceptance" / "bede-release.json"))
    p.add_argument("--controller-revision", default="unknown")
    p.add_argument("--run-id", default="local")
    p.add_argument("--run-attempt", default="1")
    p.add_argument("--summary-out")
    a = p.parse_args(argv)
    pol, acc = policy_mod.load(a.policy), policy_mod.load_acceptance(a.acceptance)
    try:
        store = (state_store.Store(Path(a.work)) if a.action == "start"
                 else state_store.load(Path(a.snapshot_in or ""), Path(a.work), cycle_id=a.cycle))
    except state_store.SnapshotError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}))
        return EXIT_BLOCKED
    events = []
    if a.event:
        loaded = json.loads(Path(a.event).read_text())
        events = loaded if isinstance(loaded, list) else [loaded]
    if a.action == "start":
        events = [{"kind": "start", "event_id": f"{a.cycle}-start", "cycle_id": a.cycle,
                   "controller_revision": a.controller_revision, **(events[0] if events else {})}]
    if a.action == "cancel":
        events = [{**e, "kind": "cancel"} for e in events]
    ack = []
    for e in events:
        try:
            out = apply(store, e, pol, acc)
        except (Refused, state_store.SnapshotError) as exc:
            out = {"accepted": False, "reason": str(exc), "duplicate": False}
        ack.append({"event_id": e.get("event_id"), **out})
    result = {"ack": ack}
    if a.action == "envelope":
        result = envelope(store, a.task, pol)
    elif a.action == "reconcile":
        result = reconcile(store, [e["event_id"] for e in events])
    if a.snapshot_out and a.action in ("start", "record", "cancel"):
        result["snapshot"] = store.export(Path(a.snapshot_out), cycle_id=a.cycle, controller_revision=a.controller_revision,
                                          run_id=a.run_id, run_attempt=a.run_attempt)
    result["summary"] = summary(store)
    text = json.dumps(result, indent=2, sort_keys=True)
    if sanitize.findings(text):
        print(json.dumps({"status": "BLOCKED", "reason": "credential_shape_in_output"}))
        return EXIT_BLOCKED
    if a.summary_out:
        Path(a.summary_out).write_text(text + "\n")
    print(text)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
