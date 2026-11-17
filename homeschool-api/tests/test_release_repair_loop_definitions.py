"""The loop definitions and owner rulings of 2026-11-16 (docs/release/REPAIR_LOOP.md).

1. Trusted diagnosis: an environment-unavailable reproduce result waits for a
   trusted diagnosis; the 1.56.0 baseline is the control.
2. A failure fixed outside the loop closes only through the owner's
   resolved_outside_loop event, verified against the current candidate.
3. independent_review: PASS only on a recorded, qualifying review;
   NOT_REQUIRED when no repair got that far; never a vacuous pass.
4. A regression test that passes on the base is an invalid verification.
5. Package evidence is recorded per artifact; a missing checksum is NOT_RUN.

CONTROLLER tests with fake inputs where a live run is not reachable. Where the
real thing is reachable (git, a tarball, the artifact formats #848 writes,
the workflow YAML) it is used instead of a stand-in.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

from release_repair_helpers import A, B, C, REPO, WEBKIT, Cycle, fail_row, pass_row
from release_repair import build_event, collect_results, diagnosis, gates, intake, verify_regression
from release_repair import qualification_adapter as qa

DIAG_WF = ".github/workflows/webkit-reload-diagnosis.yml"
RECORD_SH = REPO / "scripts" / "release_repair" / "record.sh"
LOOP = REPO / ".github" / "workflows" / "release-repair.yml"
WEBKIT_CHECK = "child3_webkit/reopen_after_restart"


# ── helpers ──────────────────────────────────────────────────────────────────
def to_awaiting_diagnosis(c: Cycle) -> str:
    tid = c.task_for(WEBKIT)["task_id"]
    assert c.run_role(tid, "triage", status="done")["accepted"]
    out = c.run_role(tid, "reproduce", status="blocked", blocked_code="environment_unavailable",
                     blocked_reason="no macOS runner in a cloud session")
    assert out["accepted"], out
    return tid


def version(pw, webkit, sha=A, crashed=0, runs=3, node="v24.22.2", macos="15.7.1", engine="webkit"):
    return {"artifact": f"webkit-repro-minimal-{pw}-{sha}", "artifact_sha": sha, "candidate": sha,
            "results_present": True, "runner_present": True,
            "verified": {"playwright": pw, "webkit": webkit, "node": node, "macos": macos, "arch": "arm64"},
            "tallies": {f"{engine}/B_push_two_reloads": {"crashed": crashed, "runs": runs, "not_run": 0},
                        "chromium/B_push_two_reloads": {"crashed": 0, "runs": 3, "not_run": 0}},
            "not_run": [{"variant": "firefox/I_push_navigation_api_reloads", "reason": "no Navigation API"}]}


def diag_event(tid, control=3, comparison=3, sha=A, **over):
    ev = {"task_id": tid,
          "run": {"run_id": "777", "run_attempt": "1", "workflow_path": DIAG_WF, "head_sha": sha,
                  "head_branch": "main", "event": "workflow_dispatch", "status": "completed", "conclusion": "success"},
          "versions": {"1.56.0": version("1.56.0", "26.0", sha, crashed=control),
                       "1.63.0": version("1.63.0", "26.6", sha, crashed=comparison)},
          "ambiguous": []}
    ev.update(over)
    return ev


# ── 1. trusted diagnosis ─────────────────────────────────────────────────────
def test_an_environment_unavailable_reproduce_result_waits_for_a_trusted_diagnosis(tmp_path):
    c = Cycle(tmp_path)
    tid = to_awaiting_diagnosis(c)
    t = c.s["tasks"][tid]
    assert t["status"] == "AWAITING_DIAGNOSIS" and t["status"] not in gates.TERMINAL_TASK
    assert c.s["status"] == "AWAITING_DIAGNOSIS"
    assert [n["kind"] for n in c.s["notifications"]] == ["started"]       # not a terminal state
    assert t["claims"][-1]["blocked_code"] == "environment_unavailable"
    assert t["reason"] == "no macOS runner in a cloud session"


def test_any_other_blocked_reproduce_result_is_still_blocked(tmp_path):
    c = Cycle(tmp_path)
    tid = c.task_for(WEBKIT)["task_id"]
    c.run_role(tid, "triage", status="done")
    c.run_role(tid, "reproduce", status="blocked", blocked_reason="could not reduce it")
    assert c.s["tasks"][tid]["status"] == "BLOCKED" and c.s["status"] == "BLOCKED"


def test_environment_unavailable_without_a_configured_diagnosis_is_blocked_not_stuck(tmp_path):
    c = Cycle(tmp_path)
    c.ev("results", sha=A, results=[fail_row("child1_chrome/x")])
    tid = c.task_for("browser_journeys:child1_chrome/x")["task_id"]
    c.run_role(tid, "triage", status="done")
    c.run_role(tid, "reproduce", status="blocked", blocked_code="environment_unavailable", blocked_reason="no device")
    t = c.s["tasks"][tid]
    assert t["status"] == "BLOCKED" and t["reasons"] == ["no device", "no_trusted_diagnosis_configured"]


def test_a_reproduced_diagnosis_sends_the_task_to_repair_with_the_evidence_attached(tmp_path):
    c = Cycle(tmp_path)
    tid = to_awaiting_diagnosis(c)
    claims_before = json.loads(json.dumps(c.s["tasks"][tid]["claims"]))
    out = c.ev("diagnosis", **diag_event(tid, control=3, comparison=2))
    assert out["accepted"], out
    t = c.s["tasks"][tid]
    assert t["status"] == "REPAIRING" and t["attempt"] == 0
    assert t["diagnosis"]["control_crashed"] and t["diagnosis"]["comparison_crashed"]
    assert t["diagnosis"]["run_id"] == "777" and t["diagnosis"]["sha"] == A
    assert t["diagnosis"]["versions"]["1.56.0"]["role"] == "baseline"
    assert t["diagnosis"]["versions"]["1.63.0"]["not_run"][0]["reason"] == "no Navigation API"
    assert any("trusted diagnosis run 777" in e for e in c.s["failures"][WEBKIT]["evidence"])
    assert t["claims"] == claims_before                                      # the child's claim is untouched
    assert c.s["failures"][WEBKIT]["status"] == "OPEN"                       # reproduced is not fixed


def test_a_control_that_did_not_crash_blocks_the_task(tmp_path):
    c = Cycle(tmp_path)
    tid = to_awaiting_diagnosis(c)
    assert c.ev("diagnosis", **diag_event(tid, control=0, comparison=0))["accepted"]
    t = c.s["tasks"][tid]
    assert t["status"] == "BLOCKED" and t["reason"] == "diagnosis_control_did_not_reproduce"


def test_a_crash_only_on_the_control_is_not_reproducible_and_never_a_pass(tmp_path):
    c = Cycle(tmp_path)
    tid = to_awaiting_diagnosis(c)
    assert c.ev("diagnosis", **diag_event(tid, control=3, comparison=0))["accepted"]
    s = c.s
    t = s["tasks"][tid]
    assert t["status"] == "BLOCKED"
    assert t["reasons"] == ["no macOS runner in a cloud session", "not_reproducible_in_trusted_environment"]
    codes = {b["code"] for b in s["blockers"]}
    assert {"task_blocked", "release_blocking_failure_open"} <= codes
    assert s["failures"][WEBKIT]["status"] == "OPEN" and s["release_status"] == "HOLD"


@pytest.mark.parametrize("change,reason", [
    (lambda e: e["run"].update(workflow_path=".github/workflows/test.yml"), "diagnosis_from_another_workflow"),
    (lambda e: e["run"].update(status="in_progress"), "diagnosis_run_not_finished"),
    (lambda e: e["run"].update(head_sha=B), "diagnosis_for_another_sha"),
    (lambda e: e["versions"]["1.56.0"].update(artifact_sha=B), "diagnosis_for_another_sha"),
    (lambda e: e["versions"]["1.63.0"].update(candidate=B), "diagnosis_for_another_sha"),
    (lambda e: e["versions"]["1.56.0"]["verified"].update(node="v22.12.0"), "diagnosis_environment_does_not_match_the_pins"),
    (lambda e: e["versions"]["1.63.0"]["verified"].update(webkit="27.2"), "diagnosis_environment_does_not_match_the_pins"),
    (lambda e: e["versions"]["1.56.0"]["verified"].update(macos="14.6"), "diagnosis_environment_does_not_match_the_pins"),
    (lambda e: e["versions"]["1.56.0"].update(verified=None), "diagnosis_environment_does_not_match_the_pins"),
    (lambda e: e["versions"].pop("1.63.0"), "diagnosis_comparison_1.63.0_missing"),
    (lambda e: e["versions"]["1.56.0"].update(results_present=False), "diagnosis_baseline_1.56.0_missing"),
    (lambda e: e["versions"]["1.56.0"].update(tallies={"chromium/B": {"crashed": 0, "runs": 3, "not_run": 0}}),
     "diagnosis_baseline_engine_did_not_run"),
    (lambda e: e.update(ambiguous=["webkit-repro-minimal-1.56.0-" + A]), "diagnosis_artifacts_ambiguous"),
])
def test_a_diagnosis_that_does_not_match_the_task_or_the_pins_is_refused(tmp_path, change, reason):
    c = Cycle(tmp_path)
    tid = to_awaiting_diagnosis(c)
    ev = diag_event(tid)
    change(ev)
    out = c.ev("diagnosis", **ev)
    assert not out["accepted"] and out["reason"] == reason
    assert c.s["tasks"][tid]["status"] == "AWAITING_DIAGNOSIS"


def test_a_diagnosis_for_a_task_not_awaiting_one_is_refused(tmp_path):
    c = Cycle(tmp_path)
    tid = c.task_for(WEBKIT)["task_id"]
    out = c.ev("diagnosis", **diag_event(tid))
    assert out["reason"] == "task_not_awaiting_diagnosis"


def test_an_awaiting_diagnosis_task_is_superseded_and_reissued_when_the_candidate_moves(tmp_path):
    c = Cycle(tmp_path)
    c.ev("results", sha=A, results=[fail_row("child1_chrome/x")])
    other = c.task_for("browser_journeys:child1_chrome/x")["task_id"]
    c.drive_to_review(other)
    c.run_role(other, "review", status="reviewed", verdict="approve")
    tid = to_awaiting_diagnosis(c)
    assert c.ev("integrated", new_candidate_sha=B, merged_task_ids=[other])["accepted"]
    assert c.s["tasks"][tid]["status"] == "SUPERSEDED"
    fresh = c.task_for(WEBKIT)
    assert fresh["base_sha"] == B and fresh["status"] == "TRIAGING"
    # a diagnosis bound to the old SHA cannot land on the new task
    assert not c.ev("diagnosis", **diag_event(fresh["task_id"]))["accepted"]


def test_awaiting_authorization_is_still_exempt_from_supersession(tmp_path):
    """An existing rule: an owner decision is pending, so the task is kept."""
    c = Cycle(tmp_path)
    c.ev("results", sha=A, results=[fail_row("child1_chrome/x")])
    other = c.task_for("browser_journeys:child1_chrome/x")["task_id"]
    c.drive_to_review(other)
    c.run_role(other, "review", status="reviewed", verdict="approve")
    tid = c.task_for(WEBKIT)["task_id"]
    c.run_role(tid, "triage", status="done"); c.run_role(tid, "reproduce", status="reproduced")
    c.run_role(tid, "repair", status="patch_pushed", branch="release-repair/c1/w")
    c.verify(tid, validation={"ok": False, "refused": False, "needs_authorization": True,
                              "violations": [{"code": "existing_test_changed"}]})
    c.ev("integrated", new_candidate_sha=B, merged_task_ids=[other])
    assert c.s["tasks"][tid]["status"] == "AWAITING_AUTHORIZATION"


ARTIFACT_RUNNER = f"""ProductName:		macOS
ProductVersion:		15.7.1
arch: arm64
candidate: {A}
playwright: 1.56.0
command: node webkit_nav_repro.cjs (REPEATS=3) exit=0
verified: playwright=1.56.0 webkit=26.0 (expected 26.0) node=v24.22.2 macos=15.7.1 arch=arm64
"""


def write_artifact(d: Path, pw: str, webkit: str, crashed: int):
    d.mkdir(parents=True)
    (d / "runner.txt").write_text(ARTIFACT_RUNNER.replace("1.56.0", pw).replace("webkit=26.0", f"webkit={webkit}")
                                  .replace("expected 26.0", f"expected {webkit}"))
    tally = {"webkit/B_push_two_reloads": {"crashed": crashed, "runs": 3, "not_run": 0},
             "firefox/I_push_navigation_api_reloads": {"crashed": 0, "runs": 0, "not_run": 3}}
    runs = [{"engine": "firefox", "variant": "I_push_navigation_api_reloads", "run": 1,
             "outcome": "not_run: no Navigation API", "trail": []}]
    (d / "results.json").write_text(json.dumps({"env": {}, "versions": {}, "repeats": 3, "tally": tally, "runs": runs}))
    (d / "traces").mkdir()
    (d / "repro.log").write_text("TALLY webkit/B_push_two_reloads crashed 3/3\n")


def test_the_record_job_builds_the_event_from_the_artifacts_848_writes(tmp_path):
    """diagnosis.py reads #848's real formats (results.json + runner.txt's
    verified line) and the controller accepts what it builds."""
    found = {}
    for pw, wk, crashed in (("1.56.0", "26.0", 3), ("1.63.0", "26.6", 1)):
        name = f"webkit-repro-minimal-{pw}-{A}"
        write_artifact(tmp_path / name, pw, wk, crashed)
        found[name] = [tmp_path / name]
    found["something-else"] = [tmp_path]
    c = Cycle(tmp_path / "cycle")
    tid = to_awaiting_diagnosis(c)
    run = {"id": 777, "run_attempt": 1, "path": DIAG_WF, "head_sha": A, "head_branch": "main",
           "event": "workflow_dispatch", "status": "completed", "conclusion": "success"}
    ev = diagnosis.build(run, found, tid, "webkit-repro-minimal-")
    v = ev["versions"]["1.56.0"]
    assert v["verified"] == {"playwright": "1.56.0", "webkit": "26.0", "node": "v24.22.2", "macos": "15.7.1",
                             "arch": "arm64"}
    assert v["candidate"] == A
    assert v["not_run"] == [{"variant": "firefox/I_push_navigation_api_reloads", "reason": "no Navigation API"}]
    out = c.ev("diagnosis", **{k: x for k, x in ev.items() if k not in ("kind", "event_id")})
    assert out["accepted"], out
    assert c.s["tasks"][tid]["status"] == "REPAIRING"


def test_two_artifacts_for_one_version_are_ambiguous(tmp_path):
    name = f"webkit-repro-minimal-1.56.0-{A}"
    write_artifact(tmp_path / "x", "1.56.0", "26.0", 1)
    write_artifact(tmp_path / "y", "1.56.0", "26.0", 0)
    ev = diagnosis.build({"id": 1, "path": DIAG_WF}, {name: [tmp_path / "x", tmp_path / "y"]}, "t", "webkit-repro-minimal-")
    assert ev["ambiguous"] == [name] and "1.56.0" not in ev["versions"]


# ── the coordinator cannot hand-type trusted facts ───────────────────────────
@pytest.mark.parametrize("ev", [
    {"kind": "diagnosis", "event_id": "x"}, {"kind": "verification", "event_id": "x"},
    {"kind": "results", "event_id": "x"},
    {"kind": "resolved_outside_loop", "event_id": "x", "ancestry": {"is_ancestor": True}},
])
def test_intake_refuses_trusted_kinds_and_fields_from_event_json(tmp_path, ev):
    (screened,) = intake.screen([ev])
    assert screened["kind"] == "coordinator_refused"
    c = Cycle(tmp_path)
    out = c.ev(**{k: v for k, v in screened.items() if k != "event_id"}, event_id="typed")
    assert not out["accepted"] and "record_job" in out["reason"]
    assert c.store.seen("typed")["accepted"] is False                         # the refusal is in the log


def test_intake_passes_ordinary_coordinator_events_through():
    evs = [{"kind": "agent_result", "event_id": "a"}, {"kind": "resolved_outside_loop", "event_id": "b"}]
    assert intake.screen(evs) == evs


def test_record_sh_screens_event_json_and_builds_diagnosis_and_ancestry_itself():
    text = RECORD_SH.read_text()
    screen = text.index("intake.py screen")
    assert text.index("00-raw.json") < screen < text.index('events+=("$RR/events/00-input.json")')
    assert "diagnosis.py --run \"$DIAGNOSIS_RUN\"" in text
    enrich = text.index("intake.py enrich")
    assert text.index("artifacts.py latest --cycle \"$CYCLE\" --out \"$RR/snapshot-in\"") < enrich
    assert enrich < text.index('--action record --event "$RR/events/all.json"')


def test_the_loop_validates_the_diagnosis_run_before_anything_runs():
    wf = yaml.safe_load(LOOP.read_text())
    wf["on"] = wf.pop(True, wf.get("on"))
    assert "diagnosis_run" in wf["on"]["workflow_dispatch"]["inputs"]
    guard = wf["jobs"]["resolve"]["steps"][0]
    assert guard["env"]["DIAGNOSIS_RUN"] == "${{ inputs.diagnosis_run }}"
    assert "diagnosis_run must be a run id" in guard["run"] and "task_id is required with diagnosis_run" in guard["run"]
    record = next(s for s in wf["jobs"]["record"]["steps"] if s.get("id") == "apply")
    assert record["env"]["DIAGNOSIS_RUN"] == "${{ inputs.diagnosis_run }}"


def test_the_diagnosis_workflow_stays_read_only_and_dispatch_only():
    path = REPO / DIAG_WF
    wf = yaml.safe_load(path.read_text())
    wf["on"] = wf.pop(True, wf.get("on"))
    assert set(wf["on"]) == {"workflow_dispatch"}
    assert wf["permissions"] == {"contents": "read"}
    assert all(j.get("permissions", {"contents": "read"}) == {"contents": "read"} for j in wf["jobs"].values())
    assert "secrets." not in path.read_text()


def test_the_policy_pins_are_848s_rule():
    from release_repair_helpers import pol
    d = pol().diagnosis_for(WEBKIT)
    assert d["workflow"] == DIAG_WF and d["node"] == "v24.22.2"
    assert d["baseline"] == {"playwright": "1.56.0", "webkit": "26.0"}
    assert d["comparison"] == {"playwright": "1.63.0", "webkit": "26.6"}
    wf = yaml.safe_load((REPO / DIAG_WF).read_text())
    minimal = wf["jobs"]["minimal"]
    assert set(minimal["strategy"]["matrix"]["playwright"]) == {"1.56.0", "1.63.0"}
    node = next(s for s in minimal["steps"] if str(s.get("uses", "")).startswith("actions/setup-node@"))
    assert "v" + node["with"]["node-version"] == d["node"]
    upload = next(s for s in minimal["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact@"))
    assert upload["with"]["name"].startswith(d["artifact_prefix"])


@pytest.mark.parametrize("mutate,match", [
    (lambda d: d.update(workflow="anything"), "must name one workflow"),
    (lambda d: d.update(node="24"), "one exact version"),
    (lambda d: d["comparison"].update(playwright="1.56.0"), "must be different"),
    (lambda d: d["baseline"].update(playwright="1.x"), "exact playwright"),
])
def test_the_policy_loader_refuses_a_loose_diagnosis_pin(tmp_path, mutate, match):
    from release_repair import policy
    data = json.loads((REPO / "config" / "release-repair.json").read_text())
    mutate(data["failures"][0]["trusted_diagnosis"])
    p = tmp_path / "p.json"
    p.write_text(json.dumps(data))
    with pytest.raises(policy.PolicyError, match=match):
        policy.load(p)


# ── 2. resolved outside the loop ─────────────────────────────────────────────
def outside(**over):
    ev = {"actor": "owner", "owner_ref": "owner message 2026-11-16", "fixing_pr": "#841", "merge_sha": C,
          "failure_key": WEBKIT, "ancestry": {"merge_sha": C, "candidate_sha": A, "is_ancestor": True,
                                              "checked_by": "record"}}
    ev.update(over)
    return ev


def test_a_fix_outside_the_loop_closes_the_failure_and_its_open_task(tmp_path):
    c = Cycle(tmp_path)
    tid = to_awaiting_diagnosis(c)
    c.ev("results", sha=A, results=[pass_row(WEBKIT_CHECK)])
    out = c.ev("resolved_outside_loop", **outside())
    assert out["accepted"], out
    s = c.s
    assert s["failures"][WEBKIT]["status"] == "FIXED_VERIFIED"
    assert s["tasks"][tid]["status"] == "FIXED"
    assert s["tasks"][tid]["reason"] == f"resolved_outside_loop:#841@{C[:12]}"
    assert s["outside_loop_resolutions"][0]["owner_ref"] == "owner message 2026-11-16"
    assert "release_blocking_failure_open" not in {b["code"] for b in s["blockers"]}
    assert s["gates"]["independent_review"] == "NOT_REQUIRED"               # nothing was repaired here


@pytest.mark.parametrize("over,reason", [
    ({"owner_ref": ""}, "resolved_outside_loop_requires_owner_ref"),
    ({"actor": "coordinator"}, "resolved_outside_loop_requires_owner_ref"),
    ({"merge_sha": "c" * 12}, "merge_sha_must_be_40_hex"),
    ({"fixing_pr": ""}, "resolved_outside_loop_requires_the_fixing_pr"),
    ({"failure_key": "nope"}, "unknown_failure"),
    ({"ancestry": None}, "fix_ancestry_not_verified_by_the_record_job"),
    ({"ancestry": {"merge_sha": C, "candidate_sha": A, "is_ancestor": True}}, "fix_ancestry_not_verified_by_the_record_job"),
    ({"ancestry": {"merge_sha": C, "candidate_sha": B, "is_ancestor": True, "checked_by": "record"}},
     "ancestry_checked_against_another_candidate"),
    ({"ancestry": {"merge_sha": C, "candidate_sha": A, "is_ancestor": False, "checked_by": "record"}},
     "fix_is_not_in_the_current_candidate"),
    ({"ancestry": {"merge_sha": C, "candidate_sha": A, "is_ancestor": None, "checked_by": "record"}},
     "fix_ancestry_could_not_be_checked"),
])
def test_resolved_outside_loop_is_refused_without_every_condition(tmp_path, over, reason):
    c = Cycle(tmp_path)
    c.ev("results", sha=A, results=[pass_row(WEBKIT_CHECK)])
    out = c.ev("resolved_outside_loop", **outside(**over))
    assert not out["accepted"] and out["reason"] == reason
    assert c.s["failures"][WEBKIT]["status"] == "OPEN"


def test_resolved_outside_loop_needs_current_candidate_results_that_all_pass(tmp_path):
    c = Cycle(tmp_path)
    assert c.ev("resolved_outside_loop", **outside())["reason"] == "no_current_candidate_results_for_the_failure"
    c.ev("results", sha=A, results=[pass_row(WEBKIT_CHECK), fail_row("child4_webkit/reopen_after_restart")])
    assert (c.ev("resolved_outside_loop", **outside())["reason"]
            == "failure_checks_do_not_all_pass_on_the_current_candidate")


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def test_the_ancestry_fact_comes_from_real_git(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.invalid"); git(repo, "config", "user.name", "t")
    (repo / "f").write_text("1"); git(repo, "add", "f"); git(repo, "commit", "-qm", "one")
    fix = git(repo, "rev-parse", "HEAD")
    (repo / "f").write_text("2"); git(repo, "commit", "-qam", "two")
    candidate = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "side", fix)
    (repo / "g").write_text("x"); git(repo, "add", "g"); git(repo, "commit", "-qm", "side")
    elsewhere = git(repo, "rev-parse", "HEAD")
    url = repo.as_uri()
    assert intake.git_is_ancestor(url, None, fix, candidate, tmp_path / "w1") is True
    assert intake.git_is_ancestor(url, None, elsewhere, candidate, tmp_path / "w2") is False
    assert intake.git_is_ancestor(url, None, "--upload-pack=x" + "0" * 26, candidate, tmp_path / "w3") is None
    (ev,) = intake.enrich([{"kind": "resolved_outside_loop", "merge_sha": fix}], candidate,
                          lambda a, d: intake.git_is_ancestor(url, None, a, d, tmp_path / "w4"))
    assert ev["ancestry"] == {"merge_sha": fix, "candidate_sha": candidate, "is_ancestor": True, "checked_by": "record"}


# ── 3. independent review ────────────────────────────────────────────────────
def test_a_cycle_with_no_repair_reports_review_as_not_required_and_can_finish(tmp_path):
    c = Cycle(tmp_path)
    c.ev("results", sha=A, results=[pass_row(WEBKIT_CHECK)])
    c.ev("resolved_outside_loop", **outside())
    c.ev("results", sha=A, results=[pass_row("backend", source="qa_runner", scope="backend")])
    s = c.s
    assert s["gates"]["independent_review"] == "NOT_REQUIRED"
    assert "independent_review" not in {b.get("gate") for b in s["blockers"]}
    assert s["status"] == "READY_FOR_RELEASE_DECISION"


def test_not_required_is_never_reported_as_pass(tmp_path):
    c = Cycle(tmp_path)
    assert gates.review_gate(c.s) == "NOT_REQUIRED" != "PASS"
    from release_repair import evidence, controller
    assert "| independent_review | NOT_REQUIRED |" in evidence.markdown(controller.summary(c.store))


def review_ready(c: Cycle):
    tid = c.task_for(WEBKIT)["task_id"]
    c.drive_to_review(tid)
    return tid


@pytest.mark.parametrize("result", [
    {"status": "reviewed", "verdict": "approve", "findings": None},
    {"status": "reviewed", "verdict": "approve", "diff_digest": "short"},
    {"status": "blocked", "verdict": None, "reviewer": "copilot", "blocked_reason": "review did not complete"},
    {"status": "blocked", "verdict": "approve", "reviewer": "copilot"},
])
def test_a_review_without_findings_or_that_did_not_complete_is_not_run(tmp_path, result):
    c = Cycle(tmp_path)
    tid = review_ready(c)
    assert c.run_role(tid, "review", **result)["accepted"]
    s = c.s
    assert s["tasks"][tid]["status"] == "REVIEWING" and s["tasks"][tid]["attempt"] == 0
    assert s["reviews"][tid][-1]["outcome"] == "NOT_RUN"
    assert not c.ev("integrated", new_candidate_sha=B, merged_task_ids=[tid])["accepted"]


def test_a_qualifying_review_is_a_record_and_passes_the_gate(tmp_path):
    c = Cycle(tmp_path)
    tid = review_ready(c)
    c.run_role(tid, "review", status="reviewed", verdict="approve", findings=["scope ok"], diff_digest="e" * 64)
    rec = c.s["reviews"][tid][-1]
    assert rec["assignment"]["session_id"] == f"session_review_{tid}" and rec["assignment"]["role"] == "review"
    assert rec["diff_digest"] == "e" * 64 and rec["findings"] == ["scope ok"] and rec["resolved_sha"] == C
    assert c.s["gates"]["independent_review"] == "PASS"
    c.ev("integrated", new_candidate_sha=B, merged_task_ids=[tid])
    assert c.s["gates"]["independent_review"] == "PASS"


def test_an_integrated_task_without_a_qualifying_review_blocks(tmp_path):
    c = Cycle(tmp_path)
    tid = review_ready(c)
    c.run_role(tid, "review", status="reviewed", verdict="approve")
    c.ev("integrated", new_candidate_sha=B, merged_task_ids=[tid])
    state = c.s
    for legacy in ("approve", [{**state["reviews"][tid][0], "resolved_sha": B}]):
        state["reviews"][tid] = legacy          # a pre-ruling string, or an approval of another diff
        assert gates.review_gate(state) == "NOT_RUN"
        ev = gates.evaluate(state, c.acc)
        assert {"code": "gate_not_passed", "gate": "independent_review", "status": "NOT_RUN"} in ev["blockers"]


def test_one_reviewed_repair_does_not_cover_another_that_was_not(tmp_path):
    c = Cycle(tmp_path)
    tid = review_ready(c)
    c.run_role(tid, "review", status="reviewed", verdict="approve")
    c.ev("integrated", new_candidate_sha=B, merged_task_ids=[tid])
    state = c.s
    assert gates.review_gate(state) == "PASS"
    state["tasks"]["t999-unreviewed"] = {**state["tasks"][tid], "task_id": "t999-unreviewed"}
    assert gates.review_gate(state) == "NOT_RUN"


def test_an_escalation_still_reaches_the_owner(tmp_path):
    c = Cycle(tmp_path)
    tid = review_ready(c)
    c.run_role(tid, "review", status="reviewed", verdict="escalate", findings=None)
    assert c.s["tasks"][tid]["status"] == "AWAITING_AUTHORIZATION"


# ── 4. verification ──────────────────────────────────────────────────────────
def to_verifying(c: Cycle):
    tid = c.task_for(WEBKIT)["task_id"]
    c.run_role(tid, "triage", status="done"); c.run_role(tid, "reproduce", status="reproduced")
    c.run_role(tid, "repair", status="patch_pushed", branch=f"release-repair/c1/{tid}")
    return tid


def verify_ev(c, tid, regression, **over):
    t = c.s["tasks"][tid]
    ev = {"task_id": tid, "branch": t["branch"], "base_sha": t["base_sha"], "resolved_sha": C,
          "validation": {"ok": True, "refused": False, "needs_authorization": False, "violations": []},
          "regression": regression,
          "run": {"run_id": "r1", "run_attempt": "1", "controller_revision": "x", "policy_revision": c.pol.revision}}
    ev.update(over)
    return c.ev("verification", **ev)


PASSES_ON_BASE = {"pre_fix_failed": False, "pre_fix_passed": True, "post_fix_passed": True, "adjacent_passed": True}


def test_a_test_that_passes_on_the_base_is_an_invalid_verification_and_costs_no_attempt(tmp_path):
    c = Cycle(tmp_path)
    tid = to_verifying(c)
    assert verify_ev(c, tid, PASSES_ON_BASE)["accepted"]
    t = c.s["tasks"][tid]
    assert (t["status"], t["attempt"], t["reason"], t["invalid_verifications"]) == (
        "REPAIRING", 0, "invalid_verification_test_passes_on_base", 1)
    c.run_role(tid, "repair", status="patch_pushed", branch=f"release-repair/c1/{tid}")
    verify_ev(c, tid, PASSES_ON_BASE)
    t = c.s["tasks"][tid]
    assert (t["status"], t["attempt"], t["reason"]) == ("BLOCKED", 0, "invalid_verification_repeated")


def test_a_base_that_timed_out_is_not_a_pass_on_the_base(tmp_path):
    c = Cycle(tmp_path)
    tid = to_verifying(c)
    verify_ev(c, tid, {"pre_fix_failed": False, "pre_fix_passed": False, "post_fix_passed": True, "adjacent_passed": True})
    t = c.s["tasks"][tid]
    assert t["attempt"] == 1 and not t.get("invalid_verifications")


@pytest.mark.parametrize("over,reason", [
    ({"branch": "release-repair/c1/other"}, "verification_for_another_branch"),
    ({"base_sha": B}, "verification_against_a_stale_base"),
    ({"resolved_sha": "c" * 39}, "branch_not_resolved_to_a_sha"),
])
def test_a_verification_for_the_wrong_branch_base_or_sha_is_refused(tmp_path, over, reason):
    c = Cycle(tmp_path)
    tid = to_verifying(c)
    out = verify_ev(c, tid, PASSES_ON_BASE, **over)
    assert not out["accepted"] and out["reason"] == reason
    assert c.s["tasks"][tid]["status"] == "VERIFYING"


def test_the_trusted_verifier_reports_a_pass_on_the_base(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.invalid"); git(repo, "config", "user.name", "t")
    (repo / "README").write_text("x"); git(repo, "add", "README"); git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "homeschool-api" / "tests").mkdir(parents=True)
    (repo / "homeschool-api" / "tests" / "test_new.py").write_text("def test_x():\n    pass\n")
    git(repo, "add", "."); git(repo, "commit", "-qm", "fix")
    head = git(repo, "rev-parse", "HEAD")
    from release_repair_helpers import pol
    for base_code, passed, failed in ((0, True, False), (1, False, True), (124, False, False)):
        codes = iter([base_code, 0])
        rep = verify_regression.verify(repo, base, head, pol(), runner=lambda cmd, cwd, t: next(codes))
        assert (rep["pre_fix_passed"], rep["pre_fix_failed"], rep["post_fix_passed"]) == (passed, failed, True)
    ev = build_event.verification("t", "b", base, head, {}, {"pre_fix_passed": True}, {"run_id": "1", "run_attempt": "1"})
    assert ev["regression"]["pre_fix_passed"] is True


# ── 5. qualify and package ───────────────────────────────────────────────────
def provenance(sha=A, arch="arm64"):
    return {"source_sha": sha, "architecture": arch, "prior_qualification_carries_to_this_sha": False,
            "pilot_go": "HOLD"}


def tarball(path: Path, prov: dict):
    with tarfile.open(path, "w:gz") as tar:
        data = json.dumps(prov).encode()
        info = tarfile.TarInfo("bede-operator/RELEASE_PROVENANCE.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return path


def sidecar(path: Path, digest: str | None = None):
    digest = digest or hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_name(path.name + ".sha256").write_text(f"{digest}  {path.name}\n")


def test_a_package_row_records_each_field_and_reads_provenance_inside_the_tarball(tmp_path):
    f = tarball(tmp_path / f"bede-operator-{A}-arm64.tar.gz", provenance())
    sidecar(f)
    (row,) = qa.package_artifacts(tmp_path, A, "bede-offline-linux-arm64-" + A)
    pkg = row["package"]
    assert row["status"] == "PASS" and row["source"] == "release_provenance"
    assert pkg["filename"] == f.name and pkg["embedded_sha"] == A and pkg["architecture"] == "arm64"
    assert pkg["checksum"]["status"] == "PASS" and pkg["checksum"]["sha256"] == hashlib.sha256(f.read_bytes()).hexdigest()
    assert pkg["os"]["status"] == "NOT_RUN" and "no OS" in pkg["os"]["reason"]
    assert pkg["signing"]["status"] == "NOT_RUN" and "signing" in pkg["signing"]["reason"]


def test_a_missing_checksum_is_not_run_never_inferred(tmp_path):
    f = tarball(tmp_path / "bede.tar.gz", provenance())
    (row,) = qa.package_artifacts(tmp_path, A)
    assert row["status"] == "NOT_RUN" and row["package"]["checksum"]["status"] == "NOT_RUN"
    sidecar(f, "0" * 64)
    (row,) = qa.package_artifacts(tmp_path, A)
    assert row["status"] == "FAIL"


def test_a_package_with_no_readable_provenance_is_not_run(tmp_path):
    dmg = tmp_path / "Bede-Engineering-Mac-arm64.dmg"
    dmg.write_bytes(b"not really a dmg")
    sidecar(dmg)
    (tmp_path / "NOT_FOR_DISTRIBUTION.txt").write_text("x")
    (row,) = qa.package_artifacts(tmp_path, A)
    assert row["status"] == "NOT_RUN" and row["package"]["embedded_sha"]["status"] == "NOT_RUN"
    assert row["package"]["not_for_distribution_notice"] is True


def test_a_package_built_from_another_sha_is_refused(tmp_path):
    sidecar(tarball(tmp_path / "x.tar.gz", provenance(sha=B)))
    with pytest.raises(qa.ShaMismatch):
        qa.package_artifacts(tmp_path, A)


@pytest.mark.parametrize("platform,architecture,runner", [
    ("linux", "amd64", "ubuntu-24.04"),
    ("linux", "arm64", "ubuntu-24.04-arm"),
    ("mac", "arm64", "macos-15"),
])
def test_the_adapter_records_only_fields_the_build_writes(tmp_path, platform, architecture, runner):
    """Execute the build's provenance writer, then read the actual artifact contract.

    Only sw_vers and artifact bytes are stand-ins; no native build, signing,
    physical acceptance, or qualification is performed by this test.
    """
    workflow = yaml.safe_load((REPO / ".github/workflows/build-bede-operator.yml").read_text())
    job = workflow["jobs"]["package" if platform == "linux" else "package-mac-pilot"]
    step_name = ("Generate source-free installer and seal embedded images" if platform == "linux"
                 else "Compile branded Mac installer and package native app")
    script = next(s["run"] for s in job["steps"] if s.get("name") == step_name)
    if platform == "linux":
        assert {"arch": architecture, "target_os": "linux", "runner": runner} in job["strategy"]["matrix"]["include"]
        script = script.replace("${{ matrix.arch }}", architecture).replace("${{ matrix.runner }}", runner)
        start = script.index("python - <<'PY'")
        directory = tmp_path / "dist/bede-operator"
        directory.mkdir(parents=True)
    else:
        start = script.index('MACOS_VERSION="$(sw_vers -productVersion)" python3')
        directory = tmp_path
    command = script[start:script.index("\nPY", start) + len("\nPY")]
    env = {**os.environ, "SOURCE_SHA": B, "RUNNER_TEMP": str(tmp_path),
           "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "example/sample",
           "GITHUB_RUN_ID": "12345", "MACOS_VERSION": "must-not-use-inherited-version",
           "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]}
    dmg = tmp_path / "Bede-Engineering-Mac-arm64.dmg"
    dmg.write_bytes(b"sample package bytes, not a native installer")
    sidecar(dmg)
    sw_vers = 'sw_vers() { test "$*" = "-productVersion" || return 1; printf "15.7.2\\n"; }\n'
    subprocess.run(["bash", "-euc", sw_vers + command], cwd=tmp_path, env=env, check=True)
    data = json.loads((directory / "RELEASE_PROVENANCE.json").read_text())
    expected = {
        "source_sha": B, "architecture": architecture,
        "os": runner if platform == "linux" else "macOS 15.7.2",
        "signing": ("unsigned" if platform == "linux"
                    else "ad hoc (codesign --sign -); codesign --verify --deep --strict passed"),
        "notarization": "not_applicable" if platform == "linux" else "none (not notarized)",
        "build_run_url": "https://github.com/example/sample/actions/runs/12345",
        "contents": ("source-free operator images and launchers" if platform == "linux"
                     else "compact source-free Mac engineering candidate (no embedded container images)"),
        "scope": "teacher-directed, sample-only Valor pilot evaluation",
        "learner_delivery": "NOT_REQUESTED", "physical_mac": "NOT_RUN",
        "engineering_acceptance": "NOT_SIGNED", "pilot_go": "HOLD",
        "prior_qualification_carries_to_this_sha": False,
    }
    if platform == "linux":
        artifact = tarball(tmp_path / f"linux-{architecture}.tar.gz", data)
        sidecar(artifact)
        dmg.unlink()
    else:
        artifact = dmg
        expected["digest"] = hashlib.sha256(dmg.read_bytes()).hexdigest()
        assert set(data) == set(expected)
        upload = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/upload-artifact"))
        paths = upload["with"]["path"].splitlines()
        for name in (dmg.name, dmg.name + ".sha256", "RELEASE_PROVENANCE.json", "NOT_FOR_DISTRIBUTION.txt"):
            assert "${{ runner.temp }}/" + name in paths
        assert 'codesign --force --deep --sign - "$RUNNER_TEMP/native/Bede Installer.app"' in script
        assert 'codesign --verify --deep --strict "$RUNNER_TEMP/native/Bede Installer.app"' in script
        notice = next(line for line in script.splitlines() if '> "$RUNNER_TEMP/NOT_FOR_DISTRIBUTION.txt"' in line)
        subprocess.run(["bash", "-euc", notice], cwd=tmp_path, env=env, check=True)
        assert (tmp_path / "NOT_FOR_DISTRIBUTION.txt").read_text() == (
            "ENGINEERING TEST ONLY: ad hoc signed, unnotarized, not approved for external distribution.\n")
    assert {key: data[key] for key in expected} == expected
    assert data["prior_qualification_carries_to_this_sha"] is False
    (row,) = qa.package_artifacts(tmp_path, B)
    assert row["status"] == "PASS"
    package = row["package"]
    assert package["filename"] == artifact.name
    assert package["embedded_sha"] == B and package["architecture"] == architecture
    assert package["os"] == expected["os"]
    assert package["signing"] == {"status": "RECORDED", "value": expected["signing"]}
    assert package["checksum"]["status"] == "PASS"
    assert package["checksum"]["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert package["not_for_distribution_notice"] is (platform == "mac")


def test_the_collector_routes_package_artifacts_through_the_per_artifact_adapter(tmp_path):
    sidecar(tarball(tmp_path / "bede.tar.gz", provenance()))
    rows = collect_results.adapt("package", "bede-standard-linux-arm64-" + A, tmp_path, A)
    assert rows[0]["check"] == "package/bede.tar.gz" and rows[0]["package"]["artifact"].startswith("bede-standard")
    assert collect_results.adapt("package", "bede-valor-prepilot-walkthrough", tmp_path / "empty", A) == []


def test_unchanged_passes_on_the_same_sha_are_reused_and_not_on_a_new_one(tmp_path):
    c = Cycle(tmp_path, acceptance="bede-release.json")
    sidecar(tarball(tmp_path / "bede.tar.gz", provenance()))
    c.ev("results", sha=A, results=qa.package_artifacts(tmp_path, A))
    assert c.s["gates"]["package_provenance"] == "PASS"
    c.ev("results", sha=A, results=[pass_row("backend", source="qa_runner", scope="backend")])
    assert c.s["gates"]["package_provenance"] == "PASS"            # still there, not re-run
    tid = c.task_for(WEBKIT)["task_id"]
    c.drive_to_review(tid); c.run_role(tid, "review", status="reviewed", verdict="approve")
    c.ev("integrated", new_candidate_sha=B, merged_task_ids=[tid])
    assert c.s["gates"]["package_provenance"] == "NOT_RUN"         # a new SHA earns its own


# ── 6. integration ───────────────────────────────────────────────────────────
def test_a_superseded_task_keeps_its_attempt_count(tmp_path):
    c = Cycle(tmp_path)
    c.ev("results", sha=A, results=[fail_row("child1_chrome/x")])
    other = c.task_for("browser_journeys:child1_chrome/x")["task_id"]
    c.drive_to_review(other); c.run_role(other, "review", status="reviewed", verdict="approve")
    tid = to_verifying(c)
    verify_ev(c, tid, {"pre_fix_failed": True, "pre_fix_passed": False, "post_fix_passed": False,
                       "adjacent_passed": True})
    assert c.s["tasks"][tid]["attempt"] == 1
    c.ev("integrated", new_candidate_sha=B, merged_task_ids=[other])
    assert c.task_for(WEBKIT)["attempt"] == 1 and c.task_for(WEBKIT)["base_sha"] == B
