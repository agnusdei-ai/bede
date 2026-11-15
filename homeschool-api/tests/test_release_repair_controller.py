"""The release-repair controller's state machine (docs/release/REPAIR_LOOP.md).

These are CONTROLLER tests with fake inputs. They prove the rules; they do not
prove the live loop (sessions, CI dispatch, wakeups) works. That is a
separate, post-merge demonstration.
"""
from __future__ import annotations

import pytest

from release_repair_helpers import A, B, C, WEBKIT, Cycle, fail_row, pass_row


# ── WebKit stays in the repair queue ─────────────────────────────────────────
def test_the_webkit_crash_is_an_active_task_from_the_first_event(tmp_path):
    c = Cycle(tmp_path)
    f = c.s["failures"][WEBKIT]
    assert f["release_blocking"] and not f["suppress_repair"] and f["root_cause"] == "unconfirmed"
    assert c.task_for(WEBKIT)["status"] == "TRIAGING"


def test_repeated_webkit_failures_deduplicate_into_one_investigation(tmp_path):
    c = Cycle(tmp_path)
    for i in range(3):
        c.ev("results", sha=A, results=[fail_row("child3_webkit/reopen_after_restart",
                                                 crash_frames=["WebCore::Navigation::initializeForNewWindow"])])
    f = c.s["failures"][WEBKIT]
    assert f["occurrences"] == 3
    assert len([t for t in f["task_ids"] if c.s["tasks"][t]["status"] not in ("SUPERSEDED",)]) == 1
    assert c.task_for(WEBKIT)["status"] == "TRIAGING"     # deduplicated, not suppressed


def test_a_different_crash_frame_is_a_different_failure(tmp_path):
    c = Cycle(tmp_path)
    c.ev("results", sha=A, results=[fail_row("child3_webkit/reopen_after_restart", crash_frames=["WebCore::Other::x"])])
    assert "browser_journeys:child3_webkit/reopen_after_restart" in c.s["failures"]


def test_the_shipped_policy_suppresses_nothing():
    from release_repair_helpers import pol
    assert all(not r.get("suppress_repair") for r in pol().failure_rules())


# ── leases ───────────────────────────────────────────────────────────────────
def test_a_stale_lease_cannot_land_a_result(tmp_path):
    c = Cycle(tmp_path)
    tid = c.task_for(WEBKIT)["task_id"]
    c.ev("assign", task_id=tid, role="triage", session_id="s1")
    old = c.lease(tid)
    c.ev("assign", task_id=tid, role="triage", session_id="s2", replace_session=True)
    out = c.ev("agent_result", task_id=tid, lease=old, result={"agent_role": "triage", "status": "done"})
    assert not out["accepted"] and out["reason"] == "stale_lease"


def test_an_expired_lease_is_refused(tmp_path):
    c = Cycle(tmp_path)
    tid = c.task_for(WEBKIT)["task_id"]
    c.ev("assign", task_id=tid, role="triage", session_id="s1")
    c.now += c.pol.lease_ttl + 1
    out = c.ev("agent_result", task_id=tid, lease=c.lease(tid), result={"agent_role": "triage", "status": "done"})
    assert out["reason"] == "lease_expired"


def test_resuming_never_creates_a_duplicate_session(tmp_path):
    c = Cycle(tmp_path)
    tid = c.task_for(WEBKIT)["task_id"]
    assert c.ev("assign", task_id=tid, role="triage", session_id="s1")["accepted"]
    again = c.ev("assign", task_id=tid, role="triage", session_id="s-new")
    assert not again["accepted"] and again["reason"] == "session_already_assigned"
    assert c.s["tasks"][tid]["session_ids"]["triage"] == "s1"


# ── claims are not evidence ──────────────────────────────────────────────────
def test_an_agent_cannot_mark_its_own_repair_verified(tmp_path):
    c = Cycle(tmp_path)
    tid = c.task_for(WEBKIT)["task_id"]
    c.run_role(tid, "triage", status="done")
    c.run_role(tid, "reproduce", status="reproduced")
    c.run_role(tid, "repair", status="patch_pushed", branch="release-repair/c1/x", tests_passed=True)
    assert c.s["tasks"][tid]["status"] == "VERIFYING"     # waits for trusted facts


def test_verification_under_another_policy_revision_is_refused(tmp_path):
    c = Cycle(tmp_path)
    tid = c.task_for(WEBKIT)["task_id"]
    c.run_role(tid, "triage", status="done"); c.run_role(tid, "reproduce", status="reproduced")
    c.run_role(tid, "repair", status="patch_pushed", branch="release-repair/c1/x")
    out = c.verify(tid, policy_revision="0" * 64)
    assert out["reason"] == "verified_under_a_different_policy_revision"


def test_a_regression_that_did_not_fail_before_the_fix_spends_an_attempt(tmp_path):
    c = Cycle(tmp_path)
    tid = c.task_for(WEBKIT)["task_id"]
    c.run_role(tid, "triage", status="done"); c.run_role(tid, "reproduce", status="reproduced")
    c.run_role(tid, "repair", status="patch_pushed", branch="release-repair/c1/x")
    c.verify(tid, pre=False)
    t = c.s["tasks"][tid]
    assert t["status"] == "REPAIRING" and t["attempt"] == 1


# ── budget ───────────────────────────────────────────────────────────────────
def test_two_failed_attempts_exhaust_the_budget(tmp_path):
    c = Cycle(tmp_path)
    tid = c.task_for(WEBKIT)["task_id"]
    c.run_role(tid, "triage", status="done"); c.run_role(tid, "reproduce", status="reproduced")
    for _ in range(2):
        c.run_role(tid, "repair", status="patch_pushed", branch="release-repair/c1/x")
        c.verify(tid, post=False)
    assert c.s["tasks"][tid]["status"] == "BUDGET_EXHAUSTED"
    with pytest.raises(AssertionError):
        c.run_role(tid, "repair", status="patch_pushed", branch="release-repair/c1/x")


# ── authorization ────────────────────────────────────────────────────────────
def test_a_protected_change_waits_for_the_owner_and_an_agent_cannot_grant_it(tmp_path):
    c = Cycle(tmp_path)
    tid = c.task_for(WEBKIT)["task_id"]
    c.run_role(tid, "triage", status="done"); c.run_role(tid, "reproduce", status="reproduced")
    c.run_role(tid, "repair", status="patch_pushed", branch="release-repair/c1/x")
    c.verify(tid, validation={"ok": False, "refused": False, "needs_authorization": True,
                              "violations": [{"code": "existing_test_changed"}]})
    assert c.s["tasks"][tid]["status"] == "AWAITING_AUTHORIZATION"
    forged = c.ev("authorization", task_id=tid, decision="allow", actor="agent", owner_ref="")
    assert not forged["accepted"]
    ok = c.ev("authorization", task_id=tid, decision="allow", actor="owner", owner_ref="chat message 2026-11-15")
    assert ok["accepted"] and c.s["tasks"][tid]["status"] == "REVIEWING"


# ── integration, supersession, idempotency ───────────────────────────────────
def test_integration_moves_the_candidate_and_supersedes_open_tasks_on_the_old_base(tmp_path):
    c = Cycle(tmp_path)
    c.ev("results", sha=A, results=[fail_row("child1_chrome/answer_persisted_after_restart")])
    other = c.task_for("browser_journeys:child1_chrome/answer_persisted_after_restart")["task_id"]
    tid = c.task_for(WEBKIT)["task_id"]
    c.drive_to_review(tid)
    c.run_role(tid, "review", status="reviewed", verdict="approve")
    assert c.ev("integrated", new_candidate_sha=B, merged_task_ids=[tid])["accepted"]
    s = c.s
    assert s["candidate_sha"] == B
    assert s["tasks"][other]["status"] == "SUPERSEDED"
    fresh = c.task_for("browser_journeys:child1_chrome/answer_persisted_after_restart")
    assert fresh["base_sha"] == B and fresh["task_id"] != other


def test_integrating_an_unreviewed_task_is_refused(tmp_path):
    c = Cycle(tmp_path)
    tid = c.task_for(WEBKIT)["task_id"]
    out = c.ev("integrated", new_candidate_sha=B, merged_task_ids=[tid])
    assert not out["accepted"]


def test_results_for_a_superseded_candidate_are_refused(tmp_path):
    c = Cycle(tmp_path)
    tid = c.task_for(WEBKIT)["task_id"]
    c.drive_to_review(tid); c.run_role(tid, "review", status="reviewed", verdict="approve")
    c.ev("integrated", new_candidate_sha=B, merged_task_ids=[tid])
    out = c.ev("results", sha=A, results=[pass_row("x")])
    assert out["reason"] == "results_for_a_superseded_candidate"


def test_a_duplicate_submission_is_acknowledged_as_a_no_op(tmp_path):
    c = Cycle(tmp_path)
    first = c.ev("results", sha=A, results=[fail_row("child1_chrome/x")], event_id="same")
    before = c.s
    again = c.ev("results", sha=A, results=[fail_row("child1_chrome/x")], event_id="same")
    assert first["accepted"] and again["duplicate"] and c.s == before
    assert c.s["failures"]["browser_journeys:child1_chrome/x"]["occurrences"] == 1


def test_a_refused_event_changes_nothing_but_is_still_acknowledged(tmp_path):
    c = Cycle(tmp_path)
    before = c.s
    out = c.ev("integrated", new_candidate_sha="short", merged_task_ids=[])
    assert not out["accepted"] and c.s == before
    assert c.store.seen("e2") == {"accepted": False, "reason": "candidate_sha_must_be_40_hex"}


def test_a_fixed_failure_that_returns_reopens_as_a_new_task(tmp_path):
    c = Cycle(tmp_path)
    tid = c.task_for(WEBKIT)["task_id"]
    c.drive_to_review(tid); c.run_role(tid, "review", status="reviewed", verdict="approve")
    c.ev("integrated", new_candidate_sha=B, merged_task_ids=[tid])
    c.ev("results", sha=B, results=[pass_row("child3_webkit/reopen_after_restart")])
    assert c.s["failures"][WEBKIT]["status"] == "FIXED_VERIFIED"
    c.ev("results", sha=B, results=[fail_row("child3_webkit/reopen_after_restart", sha=B)])
    assert c.s["failures"][WEBKIT]["status"] == "OPEN"
    assert c.task_for(WEBKIT)["status"] == "TRIAGING"


# ── terminal outcomes keep their real reasons ────────────────────────────────
def test_demo_budget_exhausted_and_missing_mac_evidence_report_both_blockers(tmp_path):
    """Controller demonstration 2: a safe stop. Real (bede-release) gates."""
    c = Cycle(tmp_path, acceptance="bede-release.json")
    tid = c.task_for(WEBKIT)["task_id"]
    c.run_role(tid, "triage", status="done"); c.run_role(tid, "reproduce", status="reproduced")
    for _ in range(2):
        c.run_role(tid, "repair", status="patch_pushed", branch="release-repair/c1/x")
        c.verify(tid, post=False)
    for scope in ("backend", "homeschool-tutor"):
        c.ev("results", sha=A, results=[pass_row(scope, source="qa_runner", scope=scope)])
    s = c.s
    codes = {b["code"] for b in s["blockers"]}
    assert s["status"] == "BUDGET_EXHAUSTED" and s["release_status"] == "HOLD"
    assert {"repair_budget_exhausted", "physical_mac_evidence_missing", "real_safari_evidence_missing",
            "release_blocking_failure_open"} <= codes
    assert [n["kind"] for n in s["notifications"]] == ["started", "terminal"]


def test_demo_staged_failure_reaches_ready_only_against_the_test_only_manifest(tmp_path):
    """Controller demonstration 1: detect → reproduce → repair → verify →
    review → integrate → qualify. Labelled TEST ONLY: it says nothing about
    Bede's real (physical) release gates."""
    c = Cycle(tmp_path)
    c.ev("results", sha=A, results=[fail_row("child3_webkit/reopen_after_restart",
                                             crash_frames=["WebCore::Navigation::initializeForNewWindow"])])
    tid = c.task_for(WEBKIT)["task_id"]
    c.drive_to_review(tid)
    c.run_role(tid, "review", status="reviewed", verdict="approve")
    c.ev("integrated", new_candidate_sha=B, merged_task_ids=[tid])
    c.ev("results", sha=B, results=[pass_row("child3_webkit/reopen_after_restart", sha=B),
                                    pass_row("backend", sha=B, source="qa_runner", scope="backend")])
    s = c.s
    assert s["status"] == "READY_FOR_RELEASE_DECISION" and s["test_only"] is True
    assert s["release_status"] == "READY_FOR_RELEASE_DECISION"
    from release_repair import controller
    summ = controller.summary(c.store)
    assert summ["approved_for_distribution"] is False
    assert summ["acceptance"]["label"].startswith("TEST ONLY")


def test_the_same_staged_repair_holds_against_the_real_manifest(tmp_path):
    c = Cycle(tmp_path, acceptance="bede-release.json")
    tid = c.task_for(WEBKIT)["task_id"]
    c.drive_to_review(tid); c.run_role(tid, "review", status="reviewed", verdict="approve")
    c.ev("integrated", new_candidate_sha=B, merged_task_ids=[tid])
    c.ev("results", sha=B, results=[pass_row("child3_webkit/reopen_after_restart", sha=B)])
    assert c.s["release_status"] == "HOLD"
    assert "physical_mac_evidence_missing" in {b["code"] for b in c.s["blockers"]}


def test_physical_evidence_needs_the_owner_and_the_right_sha(tmp_path):
    c = Cycle(tmp_path, acceptance="bede-release.json")
    rec = {"candidate_sha": A, "browser_requested": "safari", "finished": True,
           "items": {"enroll": {"server_says": "PASS", "you_said": "yes"}}}
    assert not c.ev("physical", record=rec, actor="agent", owner_ref="x")["accepted"]
    assert not c.ev("physical", record={**rec, "candidate_sha": B}, actor="owner", owner_ref="x")["accepted"]
    assert c.ev("physical", record=rec, actor="owner", owner_ref="owner upload")["accepted"]
    assert c.s["gates"]["physical_mac"] == "PASS" and c.s["gates"]["real_safari"] == "PASS"


def test_cancel_needs_the_owner(tmp_path):
    c = Cycle(tmp_path)
    assert not c.ev("cancel", actor="coordinator")["accepted"]
    assert c.ev("cancel", actor="owner", owner_ref="owner said stop")["accepted"]
    assert c.s["status"] == "CANCELLED"


# ── the policy loader refuses a policy that would weaken the loop ────────────
@pytest.mark.parametrize("mutate,match", [
    (lambda d: d["failures"][0].update(suppress_repair=True), "suppress_repair needs an owner_approval_ref"),
    (lambda d: d["failures"][0].update(disposition="waive"), "only 'investigate' needs no owner approval"),
    (lambda d: d["budgets"].update(repair_attempts_per_task=5), "bounded to 1 or 2"),
    (lambda d: d["execution"].update(merge=True), "may not enable"),
    (lambda d: d["existing_test_changes"].update(default="allow"), "require_authorization"),
    (lambda d: d["existing_test_changes"]["never_allow_silently"].pop(), "never-silent"),
])
def test_the_policy_loader_refuses_a_weakened_policy(tmp_path, mutate, match):
    import json
    from release_repair_helpers import REPO
    from release_repair import policy
    data = json.loads((REPO / "config" / "release-repair.json").read_text())
    mutate(data)
    p = tmp_path / "p.json"
    p.write_text(json.dumps(data))
    with pytest.raises(policy.PolicyError, match=match):
        policy.load(p)


def test_a_suppression_the_owner_recorded_is_honored(tmp_path):
    import json
    from release_repair_helpers import REPO
    from release_repair import policy
    data = json.loads((REPO / "config" / "release-repair.json").read_text())
    data["failures"][0].update(suppress_repair=True, owner_approval_ref="owner decision, issue #000")
    p = tmp_path / "p.json"
    p.write_text(json.dumps(data))
    assert policy.load(p).failure_rules()[0]["suppress_repair"] is True
