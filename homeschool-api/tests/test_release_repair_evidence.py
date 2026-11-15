"""Results, gates, evidence binding, redaction and the main provenance audit.

Missing evidence is NOT_RUN, never a pass. ABSENT, BLOCKED and UNVERIFIED are
failures. A result for another SHA is refused. Nothing published carries a
credential, and READY is never approval.
"""
from __future__ import annotations

import json

import pytest

from release_repair_helpers import A, B, REPO, Cycle, acc
from release_repair import evidence, gates, main_audit, sanitize
from release_repair import qualification_adapter as qa


def test_absent_outputs_are_not_run(tmp_path):
    for rows in (qa.qualification_matrix(tmp_path, A), qa.browser_journeys(tmp_path, A),
                 qa.qa_runner(tmp_path / "r.json", A, "backend"), qa.release_provenance(tmp_path / "p.json", A),
                 qa.mac_check(tmp_path / "m.json", A)):
        assert [r["status"] for r in rows] == ["NOT_RUN"]


@pytest.mark.parametrize("status", ["ABSENT", "BLOCKED", "UNVERIFIED", "FAIL", "SOMETHING_NEW"])
def test_no_matrix_status_but_pass_is_a_pass(tmp_path, status):
    (tmp_path / "matrix.json").write_text(json.dumps({"cells": [{"group": "G1", "cell": "x", "status": status}]}))
    (r,) = qa.qualification_matrix(tmp_path, A)
    assert r["status"] == "FAIL" and r["original_status"] == status


def test_a_result_for_another_sha_is_refused(tmp_path):
    (tmp_path / "results.json").write_text(json.dumps({"summary": {"sha": B}, "checks": [], "steps": []}))
    with pytest.raises(qa.ShaMismatch):
        qa.browser_journeys(tmp_path, A)


def test_journey_missing_checks_and_crash_frames_come_through(tmp_path):
    (tmp_path / "results.json").write_text(json.dumps({
        "summary": {"sha": A, "os": "darwin", "missing_checks": ["child3_webkit/answer_retry_is_idempotent"]},
        "checks": [{"user": "child3_webkit", "check": "answer_persisted_after_restart", "ok": False, "note": "Target crashed"}],
        "steps": [{"user": "child3_webkit", "step": "reopen_after_restart", "ok": False, "note": "page.reload: Page crashed"}]}))
    (tmp_path / "crash-reports").mkdir()
    (tmp_path / "crash-reports" / "summary.txt").write_text(
        "    WebCore WebCore::Navigation::initializeForNewWindow(std::optional)\n")
    (tmp_path / "crash-reports" / "raw.ips").write_text("    WebCore WebCore::Secret::frame(x)\n")
    rows = {r["check"]: r for r in qa.browser_journeys(tmp_path, A)}
    assert rows["child3_webkit/answer_retry_is_idempotent"]["status"] == "NOT_RUN"
    step = rows["child3_webkit/reopen_after_restart"]
    assert step["status"] == "FAIL" and step["crash_frames"] == ["WebCore::Navigation::initializeForNewWindow"]


def test_a_mac_check_skip_is_not_run_and_a_no_is_a_failure(tmp_path):
    f = tmp_path / "m.json"
    f.write_text(json.dumps({"candidate_sha": A, "finished": True, "browser_requested": "safari", "items": {
        "a": {"server_says": "PASS", "you_said": "(skipped)"}, "b": {"server_says": "PASS", "you_said": "no"},
        "c": {"server_says": "PASS", "you_said": "yes"}}}))
    assert {r["check"]: r["status"] for r in qa.mac_check(f, A)} == {"a": "NOT_RUN", "b": "FAIL", "c": "PASS"}


def test_only_results_for_the_current_candidate_count_toward_gates(tmp_path):
    c = Cycle(tmp_path)
    state = c.s
    state["results"] = [{"source": "qa_runner", "check": "backend", "status": "PASS", "sha": B, "scope": "backend"}]
    assert gates.evaluate(state, acc())["gates"]["backend_tests"] == "NOT_RUN"


def test_redaction_removes_credentials_emails_and_home_paths():
    raw = "token=abc sk-ant-" + "x" * 30 + " parent@example.com /Users/someone/Library/x"
    out = sanitize.text(raw)
    assert "abc" not in out and "sk-ant" not in out and "@example.com" not in out and "someone" not in out
    assert sanitize.findings(out) == []


def test_results_are_redacted_before_they_are_stored(tmp_path):
    c = Cycle(tmp_path)
    c.ev("results", sha=A, results=[{"source": "browser_journeys", "check": "x/y", "status": "FAIL", "sha": A,
                                     "detail": "Authorization: Bearer sk-" + "y" * 30}])
    assert "sk-yyyy" not in json.dumps(c.s)


def test_evidence_says_ready_is_not_approval_and_sums_every_file(tmp_path):
    from release_repair import controller
    c = Cycle(tmp_path)
    manifest = evidence.write(tmp_path / "ev", controller.summary(c.store))
    assert manifest["approved_for_distribution"] is False and "owner decides" in manifest["decision_authority"]
    sums = (tmp_path / "ev" / "SHA256SUMS").read_text()
    for name in ("summary.json", "summary.md", "manifest.json"):
        assert name in sums
    assert "Approved for distribution: **no**" in (tmp_path / "ev" / "summary.md").read_text()


def test_evidence_refuses_to_publish_a_credential(tmp_path, monkeypatch):
    monkeypatch.setattr(sanitize, "obj", lambda v: v)
    with pytest.raises(ValueError):
        evidence.write(tmp_path / "ev", {"cycle_id": "sk-ant-" + "z" * 30, "acceptance": {"label": "", "test_only": True}})


# ── main provenance audit ────────────────────────────────────────────────────
MERGED = {"merged_at": "2026-11-15T00:00:00Z", "base": {"ref": "main"}}


def test_a_squash_merge_commit_passes():
    assert main_audit.audit(["s1"], lambda c: [{**MERGED, "merge_commit_sha": "s1"}], head_commit="s1") == []


def test_a_merged_prs_own_commits_arriving_with_its_merge_commit_pass():
    prs = {"c1": [{**MERGED, "merge_commit_sha": "m"}], "m": [{**MERGED, "merge_commit_sha": "m"}]}
    assert main_audit.audit(["c1", "m"], prs.get, head_commit="m") == []


def test_a_direct_push_is_flagged():
    found = main_audit.audit(["d1"], lambda c: [], head_commit="d1")
    assert found == [{"commit": "d1", "code": "no_merged_pull_request"}]


def test_an_unmerged_or_other_base_pr_does_not_count():
    prs = [{"merged_at": None, "base": {"ref": "main"}, "merge_commit_sha": "d1"},
           {**MERGED, "base": {"ref": "release-repair/c1/t"}, "merge_commit_sha": "d1"}]
    assert main_audit.audit(["d1"], lambda c: prs, head_commit="d1")[0]["code"] == "no_merged_pull_request"


def test_a_stray_commit_alongside_a_merge_is_flagged():
    prs = {"m": [{**MERGED, "merge_commit_sha": "m"}], "stray": [{**MERGED, "merge_commit_sha": "other"}]}
    assert main_audit.audit(["stray", "m"], prs.get, head_commit="m") == [
        {"commit": "stray", "code": "commit_not_part_of_a_pr_merge"}]
