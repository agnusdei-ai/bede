"""The capacity run's arithmetic says what it claims (scripts/qualification/capacity/report.py).

The run publishes one number a family's deployment decisions lean on (how
many children one backend serves at once) and one verdict at 10 browser
sessions. Both are computed here, so each rule is stated as a situation:
percentiles, the per-step thresholds, the contiguous supported count, the
required point, which limit binds, and the fail-closed rules: a step that
errored or never ran is never supported, and 10 sessions that did not run are
NOT_RUN, never PASS. Each guard was verified by breaking it (see the PR).
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

CAP = Path(__file__).resolve().parents[2] / "scripts" / "qualification" / "capacity"
sys.path.insert(0, str(CAP))
sys.path.insert(0, str(CAP.parent))
import loadgen  # noqa: E402
import report as rpt  # noqa: E402

TH = json.loads((CAP / "capacity.json").read_text())["thresholds"]


def turns(n, first=1.5, done=1.9, outcome="ok"):
    return [{"outcome": outcome, "first_s": first, "done_s": done} for _ in range(n)]


def step(sessions=1, first=1.5, extra=None, **kw):
    t = turns(3 * sessions, first=first)
    s = {"kind": "api", "sessions": sessions, "status": "ran", "summary": rpt.summarize_turns(t),
         "turns_per_session": {f"s{i}": 3 for i in range(sessions)}, "duplicated_turns": 0,
         "practice": {"answered": sessions, "accepted": sessions, "missing": 0, "duplicated": 0, "429": 0, "refused": 0},
         "session_errors": [], "api": {"rss_fraction_of_limit": 0.3, "cpu_fraction_p75": 0.4, "pool_capacity": 10,
                                       "pool_checkedout_max": 3, "pool_wait_p95_s": 0.001},
         "host": {"cpu_fraction_p75": 0.3, "mem_fraction_max": 0.2}, "container": {"oom_killed": False, "restarts": 0},
         "log_errors": {"io": 0, "memory": 0, "threads_fds": 0}, "stub": {"p95_s": 1.0, "configured_s": 1.0},
         "rate": {"busiest_client_per_min": {"api": 15}, "limits": {"api": 120}, "refused_by_bucket": {}}}
    if extra:
        for path, value in extra.items():
            d = s
            keys = path.split(".")
            for k in keys[:-1]:
                d = d[k]
            d[keys[-1]] = value
    s.update(kw)
    return s


# ── percentiles ─────────────────────────────────────────────────────────────
def test_percentile_is_nearest_rank():
    v = list(range(1, 11))
    assert rpt.percentile(v, 0.5) == 5
    assert rpt.percentile(v, 0.95) == 10
    assert rpt.percentile(v, 0.1) == 1
    assert rpt.percentile([7.0], 0.95) == 7.0
    assert rpt.percentile([], 0.5) is None
    assert rpt.percentile([3, None, 1], 0.5) == 1
    with pytest.raises(ValueError):
        rpt.percentile(v, 0)


def test_summary_counts_only_completed_turns_in_latency():
    t = turns(4, first=1.0, done=2.0) + [{"outcome": "5xx"}, {"outcome": "stall"}]
    s = rpt.summarize_turns(t)
    assert s["turns"] == 6 and s["completed"] == 4
    assert s["outcomes"] == {"ok": 4, "5xx": 1, "stall": 1}
    assert s["first_token_s"] == {"n": 4, "p50": 1.0, "p95": 1.0, "max": 1.0}


# ── per-step thresholds ─────────────────────────────────────────────────────
def test_a_clean_step_passes():
    v = rpt.step_verdict(step(4), TH, 1.5)
    assert v == {"passed": True, "reasons": [], "classes": []}


@pytest.mark.parametrize("change,cls", [
    ({"summary.outcomes.5xx": 1}, "response"),
    ({"summary.outcomes.429": 1}, "response"),
    ({"practice.429": 1}, "response"),
    ({"summary.outcomes.dropped": 1}, "response"),
    ({"summary.outcomes.timeout": 1}, "response"),
    ({"summary.outcomes.stall": 1}, "response"),
    ({"practice.missing": 1}, "response"),
    ({"practice.refused": 1}, "response"),
    ({"practice.duplicated": 1}, "response"),
    ({"duplicated_turns": 1}, "response"),
    ({"session_errors": ["reload left the lesson"]}, "response"),
    ({"container.oom_killed": True}, "memory"),
    ({"container.restarts": 1}, "memory"),
    ({"api.rss_fraction_of_limit": 0.95}, "memory"),
    ({"log_errors.io": 2}, "io"),
    ({"log_errors.threads_fds": 1}, "threads_fds"),
    ({"log_errors.memory": 1}, "memory"),
    ({"host.cpu_fraction_p75": 0.97}, "client_side"),
    ({"host.mem_fraction_max": 0.95}, "client_side"),
])
def test_each_threshold_fails_the_step_and_names_its_class(change, cls):
    v = rpt.step_verdict(step(4, extra=change), TH, 1.5)
    assert not v["passed"] and cls in v["classes"], v


def test_first_token_is_judged_against_the_one_session_median():
    assert rpt.step_verdict(step(4, first=1.5 + TH["first_token_p95_excess_s"] - 0.1), TH, 1.5)["passed"]
    v = rpt.step_verdict(step(4, first=1.5 + TH["first_token_p95_excess_s"] + 0.1), TH, 1.5)
    assert not v["passed"] and "over the one-session median" in v["reasons"][0]


def test_no_baseline_means_no_pass():
    """Unknown data never passes: without a one-session step there is
    nothing to measure contention against."""
    assert not rpt.step_verdict(step(4), TH, None)["passed"]


def test_a_session_that_completed_nothing_fails_the_step():
    s = step(4)
    s["turns_per_session"] = {"s0": 3, "s1": 0, "s2": 3, "s3": 3}
    assert not rpt.step_verdict(s, TH, 1.5)["passed"]
    s["turns_per_session"] = {"s0": 3}  # three sessions reported nothing at all
    assert not rpt.step_verdict(s, TH, 1.5)["passed"]


@pytest.mark.parametrize("status", ["error", "not_run", None])
def test_a_step_that_did_not_run_never_passes(status):
    s = {"kind": "api", "sessions": 4, "status": status, "error": "x"}
    assert not rpt.step_verdict(s, TH, 1.5)["passed"]
    # Even with numbers that would pass: a step that errored part-way may
    # carry clean-looking partial results, and they never count.
    full = step(4)
    full["status"] = status
    assert not rpt.step_verdict(full, TH, 1.5)["passed"]


# ── the supported count is contiguous from the smallest step ───────────────
def judged(*verdicts):
    out = []
    for n, ok in verdicts:
        out.append({"sessions": n, "status": "ran" if ok is not None else "error", "verdict": {"passed": bool(ok)}})
    return out


def test_supported_is_the_last_step_of_an_unbroken_run_of_passes():
    assert rpt.supported_sessions(judged((1, True), (2, True), (4, True), (8, False))) == 4
    # A pass above a failure is noise, not capacity.
    assert rpt.supported_sessions(judged((1, True), (2, True), (4, False), (8, True))) == 2
    # An errored step in the middle stops the count just the same.
    assert rpt.supported_sessions(judged((1, True), (2, None), (4, True))) == 1
    assert rpt.supported_sessions(judged((1, False), (2, True))) == 0
    assert rpt.supported_sessions([]) == 0


def test_steps_are_ordered_by_count_not_by_position():
    assert rpt.supported_sessions(judged((4, True), (1, True), (2, True))) == 4


def test_judge_end_to_end_uses_the_one_session_step_as_baseline():
    steps = [step(1, first=1.5), step(2, first=1.6), step(4, first=6.0)]
    j = rpt.judge(steps, TH, required=4)
    assert j["baseline_first_token_s"] == 1.5
    assert j["supported_sessions"] == 2
    assert j["required"]["result"] == "FAIL"
    assert j["first_failure_by_class"]["response"] == 4


# ── the required point is PASS only when it ran and passed ─────────────────
def test_required_point_not_run_is_never_pass():
    steps = [step(1), step(8)]
    rpt.judge(steps, TH)
    assert rpt.required_point(steps, 10)["result"] == "NOT_RUN"
    errored = steps + [{"kind": "browser", "sessions": 10, "status": "error", "error": "driver exited 1"}]
    rpt.judge(errored, TH)
    r = rpt.required_point(errored, 10)
    assert r["result"] == "NOT_RUN" and "driver exited" in r["reason"]


def test_required_point_pass_and_fail():
    steps = [step(1), step(10)]
    assert rpt.judge(steps, TH, required=10)["required"]["result"] == "PASS"
    steps = [step(1), step(10, extra={"summary.outcomes.5xx": 2})]
    r = rpt.judge(steps, TH, required=10)["required"]
    assert r["result"] == "FAIL" and "5xx" in r["reason"]


# ── which limit binds ───────────────────────────────────────────────────────
def test_binding_limit_is_the_highest_utilisation_at_the_first_failing_step():
    steps = [step(1), step(2, extra={"api.pool_checkedout_max": 10, "summary.outcomes.5xx": 1})]
    j = rpt.judge(steps, TH)
    assert j["binding"]["limit"] == "db_pool" and j["binding"]["at_sessions"] == 2
    assert j["binding"]["basis"] == "first failing step"


def test_a_429_makes_the_rate_limit_binding():
    steps = [step(1), step(2, extra={"rate.refused_by_bucket": {"auth": 3}, "summary.outcomes.429": 3})]
    assert rpt.judge(steps, TH)["binding"]["limit"] == "rate_limit"


def test_with_no_failure_the_nearest_limit_at_the_supported_step_is_named():
    steps = [step(1), step(2, extra={"api.cpu_fraction_p75": 0.8})]
    b = rpt.judge(steps, TH)["binding"]
    assert b["limit"] == "cpu" and b["at_sessions"] == 2 and "nothing failed" in b["basis"]


def test_the_stub_only_binds_when_its_own_calls_slow_down():
    u = rpt.utilisation(step(2, extra={"stub.p95_s": 1.0}))
    assert u["model_stub"] == 0.0
    u = rpt.utilisation(step(2, extra={"stub.p95_s": 1.5}))
    assert u["model_stub"] == pytest.approx(1.0)


# ── practice answers: dropped and duplicated ────────────────────────────────
def test_practice_check_finds_missing_and_duplicated_answers():
    answers = [
        {"learner": "A", "set_id": 1, "item": 0, "status": 200, "already_recorded": False},
        {"learner": "A", "set_id": 1, "item": 0, "status": 200, "already_recorded": True},   # a correct retry
        {"learner": "B", "set_id": 2, "item": 1, "status": 200, "already_recorded": False},  # never stored
        {"learner": "C", "set_id": 3, "item": 0, "status": 200, "already_recorded": False},
        {"learner": "C", "set_id": 3, "item": 0, "status": 200, "already_recorded": False},  # written twice
        {"learner": "D", "set_id": 4, "item": 0, "status": 429},
        {"learner": "D", "set_id": 4, "item": 0, "status": None},
    ]
    rec = {"A/1": {0}, "B/2": set(), "C/3": {0}}
    out = loadgen.practice_check(answers, rec)
    assert out == {"answered": 7, "accepted": 5, "missing": 1, "duplicated": 1, "429": 1, "refused": 1}


# ── the written report ──────────────────────────────────────────────────────
def _report(non_default):
    steps = [step(1), step(6), step(10)]
    return {"meta": {"sha": "a" * 40, "target": "stack", "layout": "x", "model": "stub", "stub": {"_note": "n", "x": 1},
                     "non_default": non_default, "settings": {}, "reference_seats": 6},
            "browser": {"steps": steps, "judgement": rpt.judge(steps, TH, required=10)}}


def test_the_markdown_labels_a_non_default_run_and_the_seat_line():
    md = rpt.markdown(_report(["db_pool_size"]))
    assert "**NON-DEFAULT**" in md
    assert "6 (seats)" in md
    assert "At 10 sessions: PASS" in md
    assert "gates nothing" in md
    assert "_note" not in md
    assert "**NON-DEFAULT**" not in rpt.markdown(_report([]))


def test_evidence_has_checksums_over_every_file(tmp_path):
    rpt.write_evidence(tmp_path, _report([]))
    sums = (tmp_path / "SHA256SUMS").read_text()
    assert "report.json" in sums and "report.md" in sums


def test_the_credential_scan_fails_closed_on_a_learner_pin(tmp_path):
    import run_capacity
    (tmp_path / "report.md").write_text("Sample Learner A signed in with 582916\n")
    assert run_capacity.credential_scan(tmp_path, {}, ["582916"])
    (tmp_path / "report.md").write_text("timestamp 17635829160\n")  # digits inside a longer number are not a PIN
    assert not run_capacity.credential_scan(tmp_path, {}, ["582916"])
    (tmp_path / "report.md").write_text("password cap-0123456789abcdef\n")
    assert run_capacity.credential_scan(tmp_path, {"PARENT_PASSWORD": "cap-0123456789abcdef"}, [])


def test_copy_is_not_mutated_by_judging():
    steps = [step(1)]
    before = copy.deepcopy(steps[0]["summary"])
    rpt.judge(steps, TH)
    assert steps[0]["summary"] == before
