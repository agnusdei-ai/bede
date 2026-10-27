"""Synthetic-only tests for tenant-safe learner-evidence assembly."""
from datetime import datetime, timedelta, timezone

import pytest

from services.curriculum.learner_evolution import LearningEvidence
from services.curriculum.scoped_profile import (
    ScopedLearningEvidence, ScopedProfileDenied, assemble_scoped_profile,
)

NOW = datetime(2026, 10, 27, tzinfo=timezone.utc)
CAMPUS = "synthetic-campus-a"
LEARNER = "synthetic_learner_001"


def item(ref="evidence:synthetic-001", *, campus=CAMPUS, learner=LEARNER,
         skill="math.addition", kind="diagnostic", signal=0.6,
         when=NOW):
    return ScopedLearningEvidence(
        campus, learner, LearningEvidence(ref, skill, kind, when, signal),
    )


def build(*observations, **overrides):
    args = dict(campus_id=CAMPUS, learner_ref=LEARNER, version=1,
                updated_at=NOW, observations=tuple(observations))
    args.update(overrides)
    return assemble_scoped_profile(**args)


def test_feature_off_denies_even_valid_evidence(monkeypatch):
    monkeypatch.delenv("CURRICULUM_ENGINE_ENABLED", raising=False)
    with pytest.raises(ScopedProfileDenied, match="disabled"):
        build(item())


def test_mixed_evidence_retention_and_observations_preserve_provenance(monkeypatch):
    monkeypatch.setenv("CURRICULUM_ENGINE_ENABLED", "true")
    profile = build(
        item(),
        item("evidence:synthetic-002", kind="practice", signal=0.8),
        item("evidence:synthetic-003", kind="retention", signal=0.4),
        item("evidence:synthetic-004", kind="educator_observation", signal=0.7),
        item("evidence:synthetic-005", kind="parent_observation", signal=0.5),
    )
    assert profile.campus_id == CAMPUS and profile.learner_ref == LEARNER
    assert profile.skills[0].mastery == pytest.approx(0.6)
    assert profile.skills[0].confidence < 1
    assert len(profile.skills[0].evidence_refs) == 5
    assert not hasattr(profile, "learning_style")


@pytest.mark.parametrize("bad", [
    {"campus": "synthetic-campus-b"},
    {"learner": "synthetic_learner_002"},
])
def test_cross_scope_evidence_denies_whole_profile(monkeypatch, bad):
    monkeypatch.setenv("CURRICULUM_ENGINE_ENABLED", "1")
    with pytest.raises(ScopedProfileDenied, match="Out-of-scope"):
        build(item(), item("evidence:synthetic-002", **bad))


def test_duplicate_reference_even_across_skills_denied(monkeypatch):
    monkeypatch.setenv("CURRICULUM_ENGINE_ENABLED", "1")
    with pytest.raises(ScopedProfileDenied, match="duplicate"):
        build(item(), item(skill="reading.comprehension"))


def test_future_evidence_denied(monkeypatch):
    monkeypatch.setenv("CURRICULUM_ENGINE_ENABLED", "1")
    with pytest.raises(ScopedProfileDenied, match="future"):
        build(item(when=NOW + timedelta(days=1)))


def test_empty_evidence_and_invalid_version_denied(monkeypatch):
    monkeypatch.setenv("CURRICULUM_ENGINE_ENABLED", "1")
    with pytest.raises(ScopedProfileDenied):
        build()
    with pytest.raises(ScopedProfileDenied):
        build(item(), version=True)


def test_deterministic_skill_order_and_no_automatic_action(monkeypatch):
    monkeypatch.setenv("CURRICULUM_ENGINE_ENABLED", "1")
    profile = build(item(skill="zeta"), item("evidence:synthetic-002", skill="alpha"))
    assert [skill.skill_id for skill in profile.skills] == ["alpha", "zeta"]
    assert not hasattr(profile, "placement")
