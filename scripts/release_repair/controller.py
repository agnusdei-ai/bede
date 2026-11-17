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
import re
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release_repair import gates, leases, sanitize  # noqa: E402
from release_repair import policy as policy_mod  # noqa: E402
from release_repair import state_store  # noqa: E402

ROLES = ("triage", "reproduce", "repair", "review")
CLAIM_FIELDS = ("status", "summary", "blocked_code", "blocked_reason", "verdict", "branch")
ENVIRONMENT_UNAVAILABLE = "environment_unavailable"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
ROLE_FOR_STATUS = {"TRIAGING": "triage", "REPRODUCING": "reproduce", "REPAIRING": "repair", "REVIEWING": "review"}
MAX_EVIDENCE = 25
MAX_INVALID_VERIFICATIONS = 2
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
    # The claim is stored as the child wrote it and never edited afterwards.
    t["claims"] = (t["claims"] + [{"role": role, **{k: res.get(k) for k in CLAIM_FIELDS}}])[-10:]
    st = res.get("status")
    if role == "triage":
        t["status"] = "REPRODUCING" if st == "done" else "BLOCKED"
    elif role == "reproduce":
        t["status"] = {"reproduced": "REPAIRING", "blocked": "BLOCKED"}.get(st, "BLOCKED")
        if st == "blocked" and res.get("blocked_code") == ENVIRONMENT_UNAVAILABLE:
            if pol.diagnosis_for(t["failure_key"]):
                # Not a dead end: the trusted record job can reproduce it.
                t["status"] = "AWAITING_DIAGNOSIS"
            else:
                t["reasons"] = [res.get("blocked_reason") or ENVIRONMENT_UNAVAILABLE, "no_trusted_diagnosis_configured"]
    elif role == "repair":
        if st != "patch_pushed" or not res.get("branch"):
            _spend(t, pol, "repair_produced_no_branch")
        else:
            t["branch"], t["status"] = res["branch"], "VERIFYING"
    elif role == "review":
        _review(state, t, res, pol)
    if (st == "blocked" and role != "review") or t["status"] == "BLOCKED":
        t["reason"] = res.get("blocked_reason") or t["reason"] or "agent_reported_blocked"
    t["lease_id"] = None
    return state


def _review(state, t, res, pol):
    """A review is a RECORD: the reviewer session's assignment, a digest of the
    diff it was shown, and its findings. A review with no findings field, or
    one that could not complete (status other than `reviewed`, e.g. a Copilot
    review that never finished), is NOT_RUN: it is recorded and approves
    nothing, and the task waits for another review."""
    verdict, st = res.get("verdict"), res.get("status")
    digest = res.get("diff_digest")
    rec = {"task_id": t["task_id"], "reviewer": res.get("reviewer") or "session",
           "assignment": {"role": "review", "session_id": t["session_ids"].get("review"),
                          "lease_generation": t["lease_generation"]},
           "base_sha": t["base_sha"], "resolved_sha": t.get("resolved_sha"),
           "diff_digest": digest, "findings": res.get("findings"), "verdict": verdict, "status": st}
    complete = (st == "reviewed" and isinstance(res.get("findings"), list)
                and isinstance(digest, str) and _HEX64.match(digest) is not None
                and bool(rec["assignment"]["session_id"]))
    if verdict == "escalate":
        rec["outcome"] = "escalate"          # an escalation always reaches the owner
    elif not complete:
        rec["outcome"] = "NOT_RUN"
    elif verdict in ("approve", "changes_requested"):
        rec["outcome"] = verdict
    else:
        rec["outcome"] = "escalate"          # a finished review with no verdict
    reviews = state["reviews"].get(t["task_id"])
    state["reviews"][t["task_id"]] = (reviews if isinstance(reviews, list) else []) + [rec]
    if rec["outcome"] == "escalate":
        t["status"], t["reason"] = "AWAITING_AUTHORIZATION", "reviewer_escalated"
    elif rec["outcome"] == "NOT_RUN":
        t["reason"] = "review_not_run"       # stays REVIEWING; a new review is needed
    elif rec["outcome"] == "approve":
        t["status"], t["reached_ready"] = "READY_TO_INTEGRATE", True
    else:
        _spend(t, pol, "review_requested_changes")


def qualifying_approval(state, task) -> bool:
    """An approving review record for the diff this task now resolves to (one
    definition, shared with the independent_review gate)."""
    return gates._approved(state, task)


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
    elif reg.get("pre_fix_passed") is True and reg.get("post_fix_passed"):
        # The new test passes on the base too, so it proves nothing about the
        # fix. That is an invalid verification, not a failed repair: the
        # attempt is not consumed, but a second one blocks the task.
        t["invalid_verifications"] = int(t.get("invalid_verifications") or 0) + 1
        t["lease_id"] = None
        if t["invalid_verifications"] >= MAX_INVALID_VERIFICATIONS:
            t["status"], t["reason"] = "BLOCKED", "invalid_verification_repeated"
        else:
            t["status"], t["reason"] = "REPAIRING", "invalid_verification_test_passes_on_base"
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
    elif qualifying_approval(state, t):
        t["status"], t["reached_ready"] = "READY_TO_INTEGRATE", True
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


def _crashed(version: dict, engine: str) -> bool:
    return any(t["crashed"] > 0 for k, t in version["tallies"].items()
               if k.split("/", 1)[0] == engine and t["runs"] > 0)


def _diagnosis_refusal(t, ev, cfg) -> str | None:
    run = ev.get("run") or {}
    if run.get("workflow_path") != cfg["workflow"]:
        return "diagnosis_from_another_workflow"
    if run.get("status") != "completed":
        return "diagnosis_run_not_finished"
    if run.get("head_sha") != t["base_sha"]:
        return "diagnosis_for_another_sha"
    if ev.get("ambiguous"):
        return "diagnosis_artifacts_ambiguous"
    versions = ev.get("versions") or {}
    for side in ("baseline", "comparison"):
        pin = cfg[side]
        v = versions.get(pin["playwright"])
        if not v or not v.get("results_present") or not v.get("runner_present"):
            return f"diagnosis_{side}_{pin['playwright']}_missing"
        if v.get("artifact_sha") != t["base_sha"] or v.get("candidate") != t["base_sha"]:
            return "diagnosis_for_another_sha"
        env = v.get("verified") or {}
        try:
            macos_major = int(str(env.get("macos", "")).split(".")[0])
        except ValueError:
            macos_major = 0
        if (env.get("playwright") != pin["playwright"] or env.get("webkit") != pin["webkit"]
                or env.get("node") != cfg["node"] or macos_major < int(cfg["macos_min_major"])):
            return "diagnosis_environment_does_not_match_the_pins"
        if not any(k.split("/", 1)[0] == cfg["engine"] and x.get("runs", 0) > 0
                   for k, x in (v.get("tallies") or {}).items()):
            return f"diagnosis_{side}_engine_did_not_run"
    return None


def h_diagnosis(state, ev, pol, acc, now):
    """Facts from the trusted record job, read from a named run of the
    configured diagnosis workflow (diagnosis.py). Never typed by the
    coordinator: intake.py refuses one submitted as event_json.

    Owner ruling 2026-11-16. The baseline is the CONTROL. If the control did
    not crash, the harness did not show it can detect the failure. If both
    crashed, the failure is reproduced and goes to repair with the diagnosis
    attached. If only the control crashed, it is not reproducible on the
    version the candidate pins. Never a pass, never a waiver."""
    t = _task(state, ev["task_id"])
    if t["status"] != "AWAITING_DIAGNOSIS":
        raise Refused("task_not_awaiting_diagnosis")
    cfg = pol.diagnosis_for(t["failure_key"])
    if not cfg:
        raise Refused("no_trusted_diagnosis_for_this_failure")
    why = _diagnosis_refusal(t, ev, cfg)
    if why:
        raise Refused(why)
    versions, run = ev["versions"], ev["run"]
    bpw, cpw = cfg["baseline"]["playwright"], cfg["comparison"]["playwright"]
    record = {"run_id": run.get("run_id"), "run_attempt": run.get("run_attempt"), "sha": t["base_sha"],
              "workflow_path": run.get("workflow_path"), "head_branch": run.get("head_branch"),
              "versions": {pw: {"role": "baseline" if pw == bpw else "comparison",
                                "verified": versions[pw].get("verified"), "tallies": versions[pw].get("tallies"),
                                "not_run": versions[pw].get("not_run", [])} for pw in (bpw, cpw)},
              "control_crashed": _crashed(versions[bpw], cfg["engine"]),
              "comparison_crashed": _crashed(versions[cpw], cfg["engine"])}
    t["diagnosis"] = sanitize.obj(record)
    f = state["failures"][t["failure_key"]]
    f["evidence"] = (f["evidence"] + [
        f"trusted diagnosis run {record['run_id']} attempt {record['run_attempt']} @{t['base_sha'][:12]}: "
        f"control {bpw} {'crashed' if record['control_crashed'] else 'did not crash'}, "
        f"comparison {cpw} {'crashed' if record['comparison_crashed'] else 'did not crash'}"])[-MAX_EVIDENCE:]
    original = t.get("reason") or ENVIRONMENT_UNAVAILABLE
    if not record["control_crashed"]:
        t["status"], t["reason"] = "BLOCKED", "diagnosis_control_did_not_reproduce"
        t["reasons"] = ["diagnosis_control_did_not_reproduce"]
    elif record["comparison_crashed"]:
        t["status"], t["reason"] = "REPAIRING", "reproduced_in_trusted_environment"
    else:
        t["status"], t["reason"] = "BLOCKED", f"{original}; not_reproducible_in_trusted_environment"
        t["reasons"] = [original, "not_reproducible_in_trusted_environment"]
    return state


def h_resolved_outside_loop(state, ev, pol, acc, now):
    """Owner ruling 2026-11-16: a failure fixed by an owner-directed PR outside
    the loop closes only here, and only when (a) the owner said so, (b) the
    record job verified with git that the fix is in the CURRENT candidate, and
    (c) every current-candidate result for the failure's checks passes."""
    if ev.get("actor") != "owner" or not ev.get("owner_ref"):
        raise Refused("resolved_outside_loop_requires_owner_ref")
    merge = str(ev.get("merge_sha", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", merge):
        raise Refused("merge_sha_must_be_40_hex")
    if not ev.get("fixing_pr"):
        raise Refused("resolved_outside_loop_requires_the_fixing_pr")
    key = ev.get("failure_key")
    if key not in state["failures"]:
        raise Refused("unknown_failure")
    anc = ev.get("ancestry") or {}
    if anc.get("checked_by") != "record" or anc.get("merge_sha") != merge:
        raise Refused("fix_ancestry_not_verified_by_the_record_job")
    if anc.get("candidate_sha") != state["candidate_sha"]:
        raise Refused("ancestry_checked_against_another_candidate")
    if anc.get("is_ancestor") is None:
        raise Refused("fix_ancestry_could_not_be_checked")
    if anc.get("is_ancestor") is not True:
        raise Refused("fix_is_not_in_the_current_candidate")
    rows = [r for r in state["results"] if r["sha"] == state["candidate_sha"] and _failure_key(r, pol)[0] == key]
    if not rows:
        raise Refused("no_current_candidate_results_for_the_failure")
    if any(r["status"] != "PASS" for r in rows):
        raise Refused("failure_checks_do_not_all_pass_on_the_current_candidate")
    ref = f"resolved_outside_loop:{ev['fixing_pr']}@{merge[:12]}"
    f = state["failures"][key]
    f["status"] = "FIXED_VERIFIED"
    f["evidence"] = (f["evidence"] + [f"{ref} owner_ref={ev['owner_ref']}; "
                                      f"{len(rows)} current-candidate check(s) pass"])[-MAX_EVIDENCE:]
    for tid in f["task_ids"]:
        t = state["tasks"][tid]
        if t["status"] not in gates.TERMINAL_TASK:
            t["status"], t["reason"], t["lease_id"] = "FIXED", ref, None
    state.setdefault("outside_loop_resolutions", []).append(
        {"failure_key": key, "owner_ref": ev["owner_ref"], "fixing_pr": ev["fixing_pr"], "merge_sha": merge,
         "candidate_sha": state["candidate_sha"], "is_ancestor": True, "passing_checks": len(rows)})
    return state


def h_coordinator_refused(state, ev, pol, acc, now):
    """intake.py replaces a coordinator event that tried to supply a trusted
    kind or field with this one, so the refusal is recorded."""
    raise Refused(str(ev.get("reason") or "coordinator_event_refused"))


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
            "physical": h_physical, "cancel": h_cancel, "diagnosis": h_diagnosis,
            "resolved_outside_loop": h_resolved_outside_loop, "coordinator_refused": h_coordinator_refused}


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
                                                "resolved_sha", "session_ids", "lease_id", "lease_generation", "reason",
                                                "reasons", "invalid_verifications", "diagnosis")}
                      for k, t in s.get("tasks", {}).items()},
            "reviews": s.get("reviews", {}), "outside_loop_resolutions": s.get("outside_loop_resolutions", []),
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
