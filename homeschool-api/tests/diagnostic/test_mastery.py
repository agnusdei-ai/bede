"""
Real check for Diagnostic build-loop unit 1.7 (mastery.py) — see
docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md. This is Phase 1's
**acceptance** unit: a synthetic evidence stream must demonstrably
converge the vector and never leave a "secure" skill's prerequisites
behind — the whole pipeline (qmatrix -> cdm -> kst) composed together.
"""

from services.diagnostic.mastery import (
    CALIBRATION_THRESHOLD,
    MasteryUpdate,
    aggregate_for_parent,
    bayesian_update,
    calibration_weight_for,
    new_vector,
)
from services.diagnostic.skill_map import (
    GradeBand,
    all_skill_ids,
    get_skill,
    prerequisites_of,
    skills_in_band,
)

# ── new_vector ────────────────────────────────────────────────────────────────


def test_new_vector_on_band_prior_is_half():
    vector = new_vector("3-5")
    for skill_id in skills_in_band(GradeBand.THREE_5):
        assert vector[skill_id] == 0.5


def test_new_vector_above_band_prior_is_lower():
    vector = new_vector("3-5")
    for skill_id in skills_in_band(GradeBand.SIX_8):
        assert vector[skill_id] < 0.5


def test_new_vector_below_band_prior_is_higher():
    vector = new_vector("3-5")
    for skill_id in skills_in_band(GradeBand.K_2):
        assert vector[skill_id] > 0.5


def test_new_vector_covers_every_skill():
    assert set(new_vector("K-2").keys()) == set(all_skill_ids())


def test_new_vector_unrecognized_band_defaults_to_flat_half():
    vector = new_vector("not-a-real-band")
    assert all(p == 0.5 for p in vector.values())


# ── bayesian_update ──────────────────────────────────────────────────────────


def test_bayesian_update_unknown_probe_leaves_vector_unchanged():
    vector = {"cc.rote_count_20": 0.5}
    new, updates = bayesian_update(vector, {"probe_id": "not.a.real.probe", "outcome": "correct", "confidence": 1.0})
    assert new == vector
    assert updates == []


def test_bayesian_update_correct_evidence_increases_posterior():
    vector = new_vector("K-2")
    new, _ = bayesian_update(vector, {"probe_id": "probe.cc.rote_count_20", "outcome": "correct", "confidence": 1.0})
    assert new["cc.rote_count_20"] > vector["cc.rote_count_20"]


def test_bayesian_update_returns_mastery_update_records():
    vector = new_vector("K-2")
    _, updates = bayesian_update(vector, {"probe_id": "probe.cc.rote_count_20", "outcome": "correct", "confidence": 1.0})
    assert len(updates) == 1
    update = updates[0]
    assert isinstance(update, MasteryUpdate)
    assert update.skill_id == "cc.rote_count_20"
    assert update.probe_id == "probe.cc.rote_count_20"
    assert update.model_used == "dina"
    assert update.prior == vector["cc.rote_count_20"]
    assert update.posterior > update.prior
    assert update.observed_at  # non-empty ISO8601 string


def test_bayesian_update_does_not_mutate_input_vector():
    vector = new_vector("K-2")
    original = dict(vector)
    bayesian_update(vector, {"probe_id": "probe.cc.rote_count_20", "outcome": "correct", "confidence": 1.0})
    assert vector == original


def test_bayesian_update_calibration_weight_above_one_moves_further_than_normal():
    vector = new_vector("K-2")
    normal, _ = bayesian_update(
        vector, {"probe_id": "probe.cc.rote_count_20", "outcome": "correct", "confidence": 1.0}, calibration_weight=1.0
    )
    boosted, _ = bayesian_update(
        vector, {"probe_id": "probe.cc.rote_count_20", "outcome": "correct", "confidence": 1.0}, calibration_weight=2.0
    )
    assert boosted["cc.rote_count_20"] > normal["cc.rote_count_20"]


def test_bayesian_update_result_stays_within_unit_interval():
    vector = new_vector("K-2")
    for _ in range(5):
        vector, _ = bayesian_update(
            vector, {"probe_id": "probe.cc.rote_count_20", "outcome": "correct", "confidence": 1.0}, calibration_weight=3.0
        )
    assert 0.0 <= vector["cc.rote_count_20"] <= 1.0


# ── calibration_weight_for (unit 3.3) ───────────────────────────────────────


def test_calibration_weight_is_maximum_at_zero_evidence():
    assert calibration_weight_for(0) == 2.0


def test_calibration_weight_is_exactly_one_at_threshold():
    assert calibration_weight_for(CALIBRATION_THRESHOLD) == 1.0


def test_calibration_weight_is_exactly_one_past_threshold():
    assert calibration_weight_for(CALIBRATION_THRESHOLD + 50) == 1.0


def test_calibration_weight_decreases_monotonically_toward_threshold():
    weights = [calibration_weight_for(n) for n in range(CALIBRATION_THRESHOLD + 1)]
    assert weights == sorted(weights, reverse=True)
    assert weights[0] > weights[-1]


def test_calibration_weight_never_drops_below_one():
    for n in range(0, CALIBRATION_THRESHOLD * 3):
        assert calibration_weight_for(n) >= 1.0


def test_calibration_weight_respects_a_caller_supplied_threshold():
    # services/diagnostic_demo.py's own (deliberately different) threshold.
    assert calibration_weight_for(3, threshold=5) > calibration_weight_for(3, threshold=3)


def test_bayesian_update_propagates_prerequisites_once_a_skill_is_secure():
    vector = new_vector("3-5")
    # Push oa.division_facts to secure with several strong, calibration-boosted updates.
    for _ in range(6):
        vector, _ = bayesian_update(
            vector, {"probe_id": "probe.oa.division_facts", "outcome": "correct", "confidence": 1.0}, calibration_weight=2.0
        )
    assert vector["oa.division_facts"] >= 0.8
    for prereq_id in prerequisites_of("oa.division_facts"):
        assert vector[prereq_id] >= 0.8, f"{prereq_id} should have been raised by propagate_prerequisites"


# ── aggregate_for_parent ─────────────────────────────────────────────────────


def test_aggregate_for_parent_classifies_domains():
    vector = {"cc.rote_count_20": 0.9, "cc.count_objects_20": 0.5, "cc.compare_quantities": 0.1}
    summary = aggregate_for_parent(vector)
    domain = summary["domains"]["Counting & Cardinality"]
    assert domain["average_probability"] == (0.9 + 0.5 + 0.1) / 3
    assert domain["level"] == "developing"  # average (0.5) falls in the developing band


def test_aggregate_for_parent_gaps_lists_only_gap_level_skills_worst_first():
    vector = {"cc.rote_count_20": 0.9, "cc.count_objects_20": 0.1, "cc.compare_quantities": 0.3}
    summary = aggregate_for_parent(vector)
    assert summary["gaps"] == ["cc.count_objects_20", "cc.compare_quantities"]


def test_aggregate_for_parent_next_steps_matches_fringe():
    vector = new_vector("K-2")
    summary = aggregate_for_parent(vector)
    from services.diagnostic.kst import fringe
    assert summary["next_steps"] == fringe(vector)


# ── Phase 1 acceptance: synthetic evidence stream ───────────────────────────


def test_synthetic_stream_converges_and_never_leaves_prerequisites_behind():
    """
    The Phase 1 acceptance test. Walks a real prerequisite chain
    (cc.rote_count_20 -> cc.count_objects_20 -> oa.add_within_20 ->
    oa.multiplication_facts -> oa.division_facts), feeding repeated
    "correct" evidence up the chain one skill at a time, mirroring how a
    real student would actually progress. After EVERY single update
    (not just at the end), asserts the core invariant: no skill is ever
    "secure" (>=0.8) while one of its direct prerequisites sits below
    "developing" (0.4) -- propagate_prerequisites must hold this at
    every step, not just eventually.
    """
    chain = [
        "cc.rote_count_20",
        "cc.count_objects_20",
        "oa.add_within_20",
        "oa.multiplication_facts",
        "oa.division_facts",
    ]
    vector = new_vector("3-5")

    def assert_prereq_invariant(v: dict[str, float]) -> None:
        for skill_id, probability in v.items():
            if probability < 0.8:
                continue
            for prereq_id in prerequisites_of(skill_id):
                assert v.get(prereq_id, 0.0) >= 0.4, (
                    f"{skill_id} is secure ({probability}) but prerequisite "
                    f"{prereq_id} is only {v.get(prereq_id, 0.0)} (below 'developing')"
                )

    for skill_id in chain:
        probe_id = f"probe.{skill_id}"
        for _ in range(8):
            vector, _ = bayesian_update(
                vector, {"probe_id": probe_id, "outcome": "correct", "confidence": 1.0}, calibration_weight=2.0
            )
            assert_prereq_invariant(vector)

    for skill_id in chain:
        assert vector[skill_id] >= 0.8, f"{skill_id} did not converge to secure: {vector[skill_id]}"

    summary = aggregate_for_parent(vector)
    for skill_id in chain:
        assert skill_id not in summary["gaps"]
