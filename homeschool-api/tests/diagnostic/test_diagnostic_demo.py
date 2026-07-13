"""
Real check for services/diagnostic_demo.py — the demo-only adapter between
the diagnostic engine and core/demo_code_session.py's per-code store. Not
part of the diagnostic build loop's own phase numbering (that loop is
paused before Phase 3/production integration); this is the demo-scoped
Phase 3/4 substitute described in
docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md's sign-off scope.

Postgres-backed (see core.database.DemoCodeSession) rather than an
in-memory dict, so every test here runs against the isolated per-test
SQLite engine the `demo_db` fixture (tests/conftest.py) swaps in for
core.database.AsyncSessionLocal.
"""

import pytest

import core.demo_code_session as demo_code_session
from services.diagnostic import apply_evidence
from services.diagnostic_demo import get_mastery_summary_demo, record_skill_evidence_demo

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


async def test_get_mastery_summary_demo_returns_none_before_any_evidence():
    code = await demo_code_session.generate_code("Ellie", "3")
    assert await get_mastery_summary_demo(code, "Ellie") is None


async def test_get_mastery_summary_demo_returns_none_for_unknown_code():
    assert await get_mastery_summary_demo("000000", "Ellie") is None


async def test_record_skill_evidence_demo_cold_starts_a_vector():
    code = await demo_code_session.generate_code("Ellie", "3")
    assert await demo_code_session.get_mastery_vector(code) is None

    await record_skill_evidence_demo(code, "3-5", "probe.oa.multiplication_facts", "correct")

    vector = await demo_code_session.get_mastery_vector(code)
    assert vector is not None
    assert vector["oa.multiplication_facts"] > 0.5


async def test_record_skill_evidence_demo_unknown_probe_is_a_no_op():
    code = await demo_code_session.generate_code("Ellie", "3")
    await record_skill_evidence_demo(code, "3-5", "not.a.real.probe", "correct")
    assert await demo_code_session.get_mastery_vector(code) is None
    assert await demo_code_session.get_mastery_evidence_count(code) == 0


async def test_record_skill_evidence_demo_unknown_code_does_not_raise():
    await record_skill_evidence_demo("000000", "3-5", "probe.oa.multiplication_facts", "correct")


async def test_evidence_count_increments_once_per_real_observation():
    code = await demo_code_session.generate_code("Ellie", "3")
    await record_skill_evidence_demo(code, "3-5", "probe.oa.multiplication_facts", "correct")
    await record_skill_evidence_demo(code, "3-5", "probe.oa.division_facts", "correct")
    assert await demo_code_session.get_mastery_evidence_count(code) == 2


async def test_get_mastery_summary_demo_reflects_recorded_evidence():
    code = await demo_code_session.generate_code("Ellie", "3")
    await record_skill_evidence_demo(code, "3-5", "probe.oa.multiplication_facts", "correct")

    summary = await get_mastery_summary_demo(code, "Ellie")
    assert summary["student_name"] == "Ellie"
    assert summary["subject_area"] == "mathematics"
    assert summary["evidence_count"] == 1
    assert len(summary["domains"]) > 0
    all_skill_ids = {skill["skill_id"] for domain in summary["domains"] for skill in domain["skills"]}
    assert "oa.multiplication_facts" in all_skill_ids


async def test_calibration_is_true_below_threshold_and_false_at_or_above():
    from services.diagnostic_demo import CALIBRATION_THRESHOLD

    code = await demo_code_session.generate_code("Ellie", "3")
    probes = [
        "probe.oa.multiplication_facts", "probe.oa.division_facts",
        "probe.ns.integers", "probe.sp.mean_median_mode", "probe.geo.coordinate_plane",
        "probe.nbt.long_division",
    ]
    for i in range(CALIBRATION_THRESHOLD - 1):
        await record_skill_evidence_demo(code, "3-5", probes[i], "correct")
    assert (await get_mastery_summary_demo(code, "Ellie"))["calibration"] is True

    await record_skill_evidence_demo(code, "3-5", probes[CALIBRATION_THRESHOLD - 1], "correct")
    assert (await get_mastery_summary_demo(code, "Ellie"))["calibration"] is False


async def test_record_skill_evidence_demo_uses_calibration_weight_for_evidence_count(monkeypatch):
    """Unit 3.3's Fable-backed review found the original version of this
    test didn't actually distinguish the new weight-decay behavior from
    apply_evidence's flat 1.0 default — mutation-verified: reverting
    record_skill_evidence_demo's weight computation still made the old
    "early vs. late delta shrinks" assertions pass, since that shrinkage
    also happens as the posterior saturates near the [0,1] clamp,
    independent of calibration weighting. Pins the wiring directly:
    monkeypatch calibration_weight_for to a distinctive, unmistakable
    constant and confirm the persisted vector matches apply_evidence
    called with that exact weight — not the flat-1.0 default."""
    import services.diagnostic_demo as demo_module
    from services.diagnostic.mastery import new_vector

    monkeypatch.setattr(demo_module, "calibration_weight_for", lambda evidence_count, threshold: 5.0)

    expected, _ = await apply_evidence(
        new_vector("3-5"), "probe.oa.multiplication_facts", "correct", 1.0, calibration_weight=5.0,
    )
    unweighted, _ = await apply_evidence(
        new_vector("3-5"), "probe.oa.multiplication_facts", "correct", 1.0, calibration_weight=1.0,
    )
    assert expected != unweighted  # sanity: the distinctive weight actually changes the result

    code = await demo_code_session.generate_code("Ellie", "3")
    await record_skill_evidence_demo(code, "3-5", "probe.oa.multiplication_facts", "correct")

    actual = await demo_code_session.get_mastery_vector(code)
    assert actual == expected
    assert actual != unweighted


async def test_two_different_codes_never_share_a_vector():
    code_a = await demo_code_session.generate_code("Ellie", "3")
    code_b = await demo_code_session.generate_code("Sam", "5")
    await record_skill_evidence_demo(code_a, "3-5", "probe.oa.multiplication_facts", "correct")

    assert await get_mastery_summary_demo(code_b, "Sam") is None
    assert await get_mastery_summary_demo(code_a, "Ellie") is not None
