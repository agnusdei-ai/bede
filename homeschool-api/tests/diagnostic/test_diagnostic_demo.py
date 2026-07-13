"""
Real check for services/diagnostic_demo.py — the demo-only, in-memory
adapter between the diagnostic engine and core/demo_code_session.py's
per-code store. Not part of the diagnostic build loop's own phase
numbering (that loop is paused before Phase 3/production integration);
this is the demo-scoped Phase 3/4 substitute described in
docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md's sign-off scope.
"""

import pytest

import core.demo_code_session as demo_code_session
from services.diagnostic_demo import get_mastery_summary_demo, record_skill_evidence_demo


def setup_function():
    demo_code_session._codes = {}


def test_get_mastery_summary_demo_returns_none_before_any_evidence():
    code = demo_code_session.generate_code("Ellie", "3")
    assert get_mastery_summary_demo(code, "Ellie") is None


def test_get_mastery_summary_demo_returns_none_for_unknown_code():
    assert get_mastery_summary_demo("000000", "Ellie") is None


@pytest.mark.asyncio
async def test_record_skill_evidence_demo_cold_starts_a_vector():
    code = demo_code_session.generate_code("Ellie", "3")
    assert demo_code_session.get_mastery_vector(code) is None

    await record_skill_evidence_demo(code, "3-5", "probe.oa.multiplication_facts", "correct")

    vector = demo_code_session.get_mastery_vector(code)
    assert vector is not None
    assert vector["oa.multiplication_facts"] > 0.5


@pytest.mark.asyncio
async def test_record_skill_evidence_demo_unknown_probe_is_a_no_op():
    code = demo_code_session.generate_code("Ellie", "3")
    await record_skill_evidence_demo(code, "3-5", "not.a.real.probe", "correct")
    assert demo_code_session.get_mastery_vector(code) is None
    assert demo_code_session.get_mastery_evidence_count(code) == 0


@pytest.mark.asyncio
async def test_record_skill_evidence_demo_unknown_code_does_not_raise():
    await record_skill_evidence_demo("000000", "3-5", "probe.oa.multiplication_facts", "correct")


@pytest.mark.asyncio
async def test_evidence_count_increments_once_per_real_observation():
    code = demo_code_session.generate_code("Ellie", "3")
    await record_skill_evidence_demo(code, "3-5", "probe.oa.multiplication_facts", "correct")
    await record_skill_evidence_demo(code, "3-5", "probe.oa.division_facts", "correct")
    assert demo_code_session.get_mastery_evidence_count(code) == 2


@pytest.mark.asyncio
async def test_get_mastery_summary_demo_reflects_recorded_evidence():
    code = demo_code_session.generate_code("Ellie", "3")
    await record_skill_evidence_demo(code, "3-5", "probe.oa.multiplication_facts", "correct")

    summary = get_mastery_summary_demo(code, "Ellie")
    assert summary["student_name"] == "Ellie"
    assert summary["subject_area"] == "mathematics"
    assert summary["evidence_count"] == 1
    assert len(summary["domains"]) > 0
    all_skill_ids = {skill["skill_id"] for domain in summary["domains"] for skill in domain["skills"]}
    assert "oa.multiplication_facts" in all_skill_ids


@pytest.mark.asyncio
async def test_calibration_is_true_below_threshold_and_false_at_or_above():
    from services.diagnostic_demo import CALIBRATION_THRESHOLD

    code = demo_code_session.generate_code("Ellie", "3")
    probes = [
        "probe.oa.multiplication_facts", "probe.oa.division_facts",
        "probe.ns.integers", "probe.sp.mean_median_mode", "probe.geo.coordinate_plane",
        "probe.nbt.long_division",
    ]
    for i in range(CALIBRATION_THRESHOLD - 1):
        await record_skill_evidence_demo(code, "3-5", probes[i], "correct")
    assert get_mastery_summary_demo(code, "Ellie")["calibration"] is True

    await record_skill_evidence_demo(code, "3-5", probes[CALIBRATION_THRESHOLD - 1], "correct")
    assert get_mastery_summary_demo(code, "Ellie")["calibration"] is False


@pytest.mark.asyncio
async def test_calibration_weight_decays_as_evidence_count_grows():
    """Unit 3.3: record_skill_evidence_demo now passes a decaying
    calibration_weight (mastery.calibration_weight_for, parameterized by
    this module's own CALIBRATION_THRESHOLD) instead of apply_evidence's
    flat 1.0 default — mirrors process_evidence's real-backend behavior."""
    from services.diagnostic_demo import CALIBRATION_THRESHOLD

    code = demo_code_session.generate_code("Ellie", "3")

    await record_skill_evidence_demo(code, "3-5", "probe.oa.multiplication_facts", "correct")
    first_call_delta = demo_code_session.get_mastery_vector(code)["oa.multiplication_facts"] - 0.5

    for _ in range(CALIBRATION_THRESHOLD):
        await record_skill_evidence_demo(code, "3-5", "probe.oa.multiplication_facts", "correct")

    before = demo_code_session.get_mastery_vector(code)["oa.multiplication_facts"]
    await record_skill_evidence_demo(code, "3-5", "probe.oa.multiplication_facts", "incorrect")
    after = demo_code_session.get_mastery_vector(code)["oa.multiplication_facts"]
    late_call_delta = before - after

    assert first_call_delta > 0
    assert abs(late_call_delta) < first_call_delta


@pytest.mark.asyncio
async def test_two_different_codes_never_share_a_vector():
    code_a = demo_code_session.generate_code("Ellie", "3")
    code_b = demo_code_session.generate_code("Sam", "5")
    await record_skill_evidence_demo(code_a, "3-5", "probe.oa.multiplication_facts", "correct")

    assert get_mastery_summary_demo(code_b, "Sam") is None
    assert get_mastery_summary_demo(code_a, "Ellie") is not None
