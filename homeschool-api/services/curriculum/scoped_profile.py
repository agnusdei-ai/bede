"""Pure, flag-gated learner-evidence assembly with an explicit tenant boundary.

This is not an authorization service, database adapter, diagnostic model, or
learner-facing feature. The caller must independently verify live campus and
learner grants and supply opaque identifiers. No personal data is logged.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from services.curriculum.flag import curriculum_engine_enabled
from services.curriculum.learner_evolution import (
    LearnerEvolutionProfile, LearningEvidence, summarize_skill,
)

_OPAQUE = re.compile(r"^[A-Za-z0-9_-]{8,}$")
_MAX_EVIDENCE = 1000


class ScopedProfileDenied(ValueError):
    """Invalid scope, evidence, timestamp, or disabled curriculum feature."""


@dataclass(frozen=True)
class ScopedLearningEvidence:
    """Evidence tagged by an upstream, independently authorized adapter."""

    campus_id: str
    learner_ref: str
    evidence: LearningEvidence

    def __post_init__(self) -> None:
        if (not isinstance(self.campus_id, str) or not self.campus_id.strip()
                or not isinstance(self.learner_ref, str)
                or not _OPAQUE.fullmatch(self.learner_ref)
                or not isinstance(self.evidence, LearningEvidence)):
            raise ScopedProfileDenied("Invalid scoped evidence identity")


def assemble_scoped_profile(
    *, campus_id: str, learner_ref: str, version: int,
    updated_at: datetime, observations: tuple[ScopedLearningEvidence, ...],
) -> LearnerEvolutionProfile:
    """Build a conservative, versioned estimate from same-learner evidence only.

    An empty evidence set cannot support a mastery conclusion. A duplicate
    reference, future-dated observation, or cross-campus/learner record denies
    the entire assembly rather than silently dropping inconvenient evidence.
    Confidence remains capped by summarize_skill; no placement or teaching
    decision is made and no result is persisted.
    """
    if not curriculum_engine_enabled():
        raise ScopedProfileDenied("Curriculum engine disabled")
    if (not isinstance(observations, tuple) or not observations
            or len(observations) > _MAX_EVIDENCE
            or not isinstance(campus_id, str) or not campus_id.strip()
            or not isinstance(learner_ref, str)
            or not _OPAQUE.fullmatch(learner_ref)
            or type(version) is not int or version < 1
            or not isinstance(updated_at, datetime)
            or updated_at.tzinfo is None or updated_at.utcoffset() is None):
        raise ScopedProfileDenied("Invalid profile assembly request")
    seen: set[str] = set()
    grouped: dict[str, list[LearningEvidence]] = {}
    for item in observations:
        if (not isinstance(item, ScopedLearningEvidence)
                or item.campus_id != campus_id or item.learner_ref != learner_ref
                or item.evidence.observed_at > updated_at
                or item.evidence.evidence_ref in seen):
            raise ScopedProfileDenied("Out-of-scope, future, or duplicate evidence")
        seen.add(item.evidence.evidence_ref)
        grouped.setdefault(item.evidence.skill_id, []).append(item.evidence)
    skills = tuple(
        summarize_skill(skill, tuple(grouped[skill])) for skill in sorted(grouped)
    )
    return LearnerEvolutionProfile(campus_id, learner_ref, version, updated_at, skills)
