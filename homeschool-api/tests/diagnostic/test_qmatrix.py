"""
Real check for Diagnostic build-loop unit 1.2 (qmatrix.py) — see
docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md. Asserts every probe maps to
at least one real skill attribute, unknown lookups degrade gracefully
rather than raising, and outcome scoring is monotonic.
"""

from services.diagnostic.qmatrix import (
    EvidenceObservation,
    Q_MATRIX,
    outcome_to_score,
    probes_for_skill,
    q_row,
)
from services.diagnostic.skill_map import SKILL_MAP, all_skill_ids


def test_evidence_observation_shape():
    obs: EvidenceObservation = {
        "probe_id": "probe.cc.rote_count_20",
        "outcome": "correct",
        "confidence": 0.9,
    }
    assert set(obs.keys()) == {"probe_id", "outcome", "confidence"}
    assert q_row(obs["probe_id"]) == ["cc.rote_count_20"]


def test_every_probe_maps_to_at_least_one_real_attribute():
    for probe in Q_MATRIX.values():
        assert probe.skills, f"{probe.id} has no attributes"
        for skill_id in probe.skills:
            assert skill_id in SKILL_MAP, f"{probe.id} references unknown skill {skill_id}"


def test_unknown_probe_id_resolves_to_nothing():
    assert Q_MATRIX.get("not.a.real.probe") is None
    assert q_row("not.a.real.probe") == []
    assert q_row("") == []


def test_every_skill_has_at_least_one_probe():
    for skill_id in all_skill_ids():
        assert probes_for_skill(skill_id), f"{skill_id} has no probe archetype"


def test_probes_for_skill_is_the_inverse_of_q_row():
    for probe in Q_MATRIX.values():
        for skill_id in probe.skills:
            assert probe.id in probes_for_skill(skill_id)


def test_outcome_to_score_is_monotonic_and_bounded():
    scores = {
        outcome: outcome_to_score(outcome)
        for outcome in ("incorrect", "hint_dependent", "partial", "correct")
    }
    ordered = list(scores.values())
    assert ordered == sorted(ordered), "outcome_to_score is not monotonically increasing"
    assert scores["incorrect"] == 0.0
    assert scores["correct"] == 1.0
    assert all(0.0 <= v <= 1.0 for v in scores.values())


def test_outcome_to_score_unknown_outcome_defaults_to_zero():
    assert outcome_to_score("not_a_real_outcome") == 0.0


def test_no_duplicate_probe_ids():
    ids = [p.id for p in Q_MATRIX.values()]
    assert len(ids) == len(set(ids))
