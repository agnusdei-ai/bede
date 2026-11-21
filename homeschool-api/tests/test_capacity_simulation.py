"""The capacity planning simulation (scripts/qualification/capacity/sim_profiles.py).

It is a planning tool, not a measurement, and these tests pin that: a profile
without a real measurement can never come out PASS, queueing counts toward the
deadline, and the thresholds apply per user so an average cannot hide an
underserved learner. Each guard was verified by breaking it.
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

CAP = Path(__file__).resolve().parents[2] / "scripts" / "qualification" / "capacity"
sys.path.insert(0, str(CAP))
import sim_profiles as sim  # noqa: E402

FAST = sim.Profile("fast", prefill_tok_s=20000, decode_tok_s=60, slots=8, batch_alpha=0.7)


def _w(**kw):
    return sim.Workload(duration_s=kw.pop("duration_s", 900), **kw)


def test_one_user_on_a_fast_profile_meets_every_threshold():
    r = sim.simulate(FAST, _w(users=1))
    assert r["meets_thresholds"] and all(r["checks"].values())


def test_a_profile_without_a_measurement_is_never_a_pass():
    r = sim.simulate(FAST, _w(users=1))
    assert r["meets_thresholds"] and r["verdict"] == "NOT_MEASURED" and r["planning_only"] is True
    measured = sim.simulate(replace(FAST, measured=True), _w(users=1))
    assert measured["verdict"] == "PASS" and measured["planning_only"] is False


def test_shipped_profiles_are_all_unmeasured_so_none_can_be_called_qualified():
    for p in sim.load_profiles(str(CAP / "sim_profiles.json")):
        assert p.measured is None and p.basis in {"assumption", "project_doc"}, p.name


def test_queueing_counts_toward_the_latency():
    one_slot = replace(FAST, slots=1, batch_alpha=0.0)
    alone = sim.simulate(one_slot, _w(users=1, pattern="burst", duration_s=300))
    crowd = sim.simulate(one_slot, _w(users=6, pattern="burst", duration_s=300))
    assert crowd["first_useful"]["p95_s"] > alone["first_useful"]["p95_s"] * 2


def test_more_users_never_make_the_worst_case_better():
    a = sim.simulate(FAST, _w(users=2, pattern="burst"))["first_useful"]["worst_user_p95_s"]
    b = sim.simulate(FAST, _w(users=12, pattern="burst"))["first_useful"]["worst_user_p95_s"]
    assert b >= a


def test_the_threshold_is_judged_per_user_not_on_the_average():
    """A server that serves most users well and one badly must fail."""
    r = sim.simulate(replace(FAST, slots=1, batch_alpha=0.0), _w(users=10, pattern="burst"))
    assert r["first_useful"]["worst_user_p95_s"] >= r["first_useful"]["p95_s"]
    assert r["checks"]["first_useful"] is (r["first_useful"]["worst_user_p95_s"] <= sim.THRESHOLDS["first_useful_p95_s"])


def test_a_shared_constant_prefix_reduces_latency_and_code_checked_practice_reduces_load():
    slow = sim.Profile("slow", prefill_tok_s=800, decode_tok_s=20, slots=2, batch_alpha=0.3)
    base = sim.simulate(slow, _w(users=6))
    cached = sim.simulate(replace(slow, prefix_cache_hit=0.9), _w(users=6))
    assert cached["first_useful"]["p95_s"] < base["first_useful"]["p95_s"]
    heavy_code = sim.simulate(slow, _w(users=6, deterministic_share=0.7))
    assert (heavy_code["first_useful"]["n"] / heavy_code["turns"]
            < base["first_useful"]["n"] / base["turns"])


def test_deterministic_practice_does_not_queue_behind_the_model():
    r = sim.simulate(replace(FAST, slots=1, batch_alpha=0.0, decode_tok_s=2, prefill_tok_s=100),
                     _w(users=8, deterministic_share=0.5))
    assert r["deterministic"]["worst_user_p95_s"] <= sim.THRESHOLDS["deterministic_p95_s"]


def test_a_tool_activity_has_two_rounds():
    one = sim.simulate(FAST, _w(users=1, mix={"tool": 1.0}, deterministic_share=0.0, seed=3))
    other = sim.simulate(FAST, _w(users=1, mix={"tutor": 1.0}, deterministic_share=0.0, seed=3))
    assert one["tool"]["p95_s"] > 0 and other["tutor"]["p95_s"] > 0
    assert one["tool"]["p95_s"] >= 2 * (sim.FIRST_USEFUL_TOKENS / FAST.decode_tok_s)


def test_results_are_repeatable_for_a_seed():
    a = sim.simulate(FAST, _w(users=5, seed=9))
    b = sim.simulate(FAST, _w(users=5, seed=9))
    assert a == b


def test_required_throughput_is_the_smallest_passing_rate():
    w = _w(users=10, duration_s=600)
    base = sim.Profile("probe", prefill_tok_s=1, decode_tok_s=1, slots=4, batch_alpha=0.5)
    need = sim.required_throughput(w, base)
    assert need is not None
    assert sim.meets(replace(base, decode_tok_s=need, prefill_tok_s=need * 8), w)
    assert not sim.meets(replace(base, decode_tok_s=need * 0.85, prefill_tok_s=need * 0.85 * 8), w)


def test_every_threshold_is_the_owners_figure():
    assert sim.THRESHOLDS == {"first_useful_p95_s": 5.0, "hint_done_p95_s": 12.0,
                              "tool_ready_p95_s": 15.0, "deterministic_p95_s": 0.5,
                              "turn_deadline_s": 30.0}


def test_the_simulation_carries_no_learner_content():
    src = (CAP / "sim_profiles.py").read_text(encoding="utf-8")
    for word in ("student_name", "child_message", "conversation_history", "requests", "httpx"):
        assert word not in src
