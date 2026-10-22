"""Pure, evidence-based learner evolution contract.

No database access, learner names, network calls, or automatic placement decisions.
A profile is a versioned interpretation of evidence, not a fixed learning-style label.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
import re

_OPAQUE = re.compile(r"^[A-Za-z0-9_-]{8,}$")
_ALLOWED_KINDS = frozenset({"diagnostic", "practice", "retention", "educator_observation", "parent_observation"})
_ALLOWED_RESPONSES = frozenset({"independent", "hinted", "reexplained", "not_observed"})


@dataclass(frozen=True)
class LearningEvidence:
    evidence_ref: str
    skill_id: str
    kind: str
    observed_at: datetime
    mastery_signal: float
    instructional_response: str = "not_observed"

    def __post_init__(self) -> None:
        if not self.evidence_ref.startswith("evidence:") or len(self.evidence_ref) < 10:
            raise ValueError("An opaque evidence reference is required")
        if not self.skill_id.strip() or self.kind not in _ALLOWED_KINDS:
            raise ValueError("Invalid skill or evidence kind")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("Evidence time must be timezone-aware")
        if not isfinite(self.mastery_signal) or not 0 <= self.mastery_signal <= 1:
            raise ValueError("Mastery signal must be finite and between 0 and 1")
        if self.instructional_response not in _ALLOWED_RESPONSES:
            raise ValueError("Invalid instructional response")


@dataclass(frozen=True)
class SkillEstimate:
    skill_id: str
    mastery: float
    confidence: float
    evidence_refs: tuple[str, ...]
    last_observed_at: datetime

    def __post_init__(self) -> None:
        if not self.skill_id or not self.evidence_refs:
            raise ValueError("A skill estimate requires evidence")
        if any(not isfinite(x) or not 0 <= x <= 1 for x in (self.mastery, self.confidence)):
            raise ValueError("Mastery and confidence must be finite probabilities")
        if self.last_observed_at.tzinfo is None or self.last_observed_at.utcoffset() is None:
            raise ValueError("Estimate timestamp must be timezone-aware")


@dataclass(frozen=True)
class LearnerEvolutionProfile:
    campus_id: str
    learner_ref: str
    version: int
    updated_at: datetime
    skills: tuple[SkillEstimate, ...]

    def __post_init__(self) -> None:
        if not self.campus_id.strip() or not _OPAQUE.fullmatch(self.learner_ref):
            raise ValueError("Campus and opaque learner reference are required")
        if self.version < 1 or self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("Positive version and timezone-aware timestamp required")
        ids = [skill.skill_id for skill in self.skills]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate skill estimates")


def summarize_skill(skill_id: str, evidence: tuple[LearningEvidence, ...]) -> SkillEstimate:
    """Conservative deterministic synthetic baseline, not a diagnostic model.

    Equal-weight observations, with confidence capped below 1.0; no evidence
    produces no estimate. Later versions can calibrate against held-out outcomes.
    """
    relevant = tuple(e for e in evidence if e.skill_id == skill_id)
    if not relevant:
        raise ValueError("Cannot estimate mastery without evidence")
    if len({e.evidence_ref for e in relevant}) != len(relevant):
        raise ValueError("Duplicate evidence references")
    mastery = sum(e.mastery_signal for e in relevant) / len(relevant)
    confidence = min(0.8, len(relevant) / (len(relevant) + 3))
    return SkillEstimate(skill_id, mastery, confidence,
                         tuple(e.evidence_ref for e in relevant),
                         max(e.observed_at for e in relevant))
