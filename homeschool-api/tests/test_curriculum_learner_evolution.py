"""Synthetic contract tests for learner evolution; no real learner data."""
from datetime import datetime, timezone

import pytest

from services.curriculum.learner_evolution import (
    LearnerEvolutionProfile, LearningEvidence, summarize_skill,
)


NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)


def evidence(ref="evidence:synthetic-001", skill="oa.add_within_20", signal=0.7):
    return LearningEvidence(ref, skill, "diagnostic", NOW, signal, "hinted")


def test_evidence_based_estimate_has_provenance_and_uncertainty():
    result = summarize_skill("oa.add_within_20", (evidence(),))
    assert result.mastery == pytest.approx(0.7)
    assert result.confidence < 1
    assert result.evidence_refs == ("evidence:synthetic-001",)


def test_no_evidence_no_estimate():
    with pytest.raises(ValueError, match="without evidence"):
        summarize_skill("oa.add_within_20", ())


def test_duplicate_evidence_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        summarize_skill("oa.add_within_20", (evidence(), evidence()))


@pytest.mark.parametrize("signal", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_signal_rejected(signal):
    with pytest.raises(ValueError):
        evidence(signal=signal)


def test_profile_requires_opaque_learner_ref_and_unique_skills():
    estimate = summarize_skill("oa.add_within_20", (evidence(),))
    with pytest.raises(ValueError, match="opaque"):
        LearnerEvolutionProfile("campus-a", "Amy", 1, NOW, (estimate,))
    with pytest.raises(ValueError, match="Duplicate"):
        LearnerEvolutionProfile("campus-a", "synthetic_learner_001", 1, NOW, (estimate, estimate))


def test_cross_skill_evidence_does_not_contaminate_estimate():
    other = evidence(ref="evidence:synthetic-002", skill="geo.identify_shapes", signal=0.1)
    result = summarize_skill("oa.add_within_20", (evidence(), other))
    assert result.evidence_refs == ("evidence:synthetic-001",)
