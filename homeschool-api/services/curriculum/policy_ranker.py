"""PR 7: transparent, offline prerequisite and observed-support policy ranking.

This is a pure domain primitive, NOT an authenticated learner-facing endpoint.
The future caller must verify campus/learner grants and source/annotation review
records before supplying RankedCitation, PolicyContext, and profile evidence.
No model, network, database, filesystem, telemetry, or learner PII is accessed.
No fixed learning-style labels or automatic consequential decisions are made.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from services.curriculum.citation_retriever import RankedCitation
from services.curriculum.flag import curriculum_engine_enabled
from services.curriculum.learner_evolution import LearnerEvolutionProfile, LearningEvidence

_MAX_ITEMS = 1000
_MAX_OBSERVATIONS = 200
_SUPPORTED_RESPONSE = {"independent": 0.0, "hinted": 0.5, "reexplained": 1.0}
_SUPPORT_KINDS = frozenset({
    "practice", "retention", "educator_observation", "parent_observation",
})


class PolicyRankingDenied(ValueError):
    """Disabled engine, missing provenance, or mismatched authorization scope."""


def _valid_unit(value: object) -> bool:
    return type(value) in (int, float) and isfinite(value) and 0 <= value <= 1


@dataclass(frozen=True)
class PolicyWeights:
    """Versioned, bounded weights. E stays zero pending separate authorization."""

    version: str = "curriculum-prerequisite-observation-v1"
    rrf: float = 0.42
    reliability: float = 0.15
    alignment: float = 0.10
    objective: float = 0.10
    prerequisite: float = 0.13
    learner_fit: float = 0.10
    effectiveness: float = 0.0

    def __post_init__(self) -> None:
        values = (self.rrf, self.reliability, self.alignment, self.objective,
                  self.prerequisite, self.learner_fit, self.effectiveness)
        if (not isinstance(self.version, str) or not self.version.strip()
                or any(not _valid_unit(v) for v in values)
                or self.effectiveness != 0.0
                or abs(sum(values) - 1.0) > 1e-9):
            raise PolicyRankingDenied("Invalid or unauthorized policy weights")


@dataclass(frozen=True)
class PolicyContext:
    """Human-reviewed curriculum metadata supplied by an authorized service."""

    campus_id: str
    chunk_id: str
    version: int
    review_ref: str
    objective_id: str
    prerequisite_skill_ids: tuple[str, ...]
    target_skill_ids: tuple[str, ...]
    scaffolding_intensity: float

    def __post_init__(self) -> None:
        if (any(not isinstance(v, str) or not v.strip()
                for v in (self.campus_id, self.chunk_id, self.review_ref,
                          self.objective_id))
                or not self.review_ref.startswith("review:")
                or type(self.version) is not int or self.version < 1
                or not _valid_unit(self.scaffolding_intensity)
                or not isinstance(self.prerequisite_skill_ids, tuple)
                or not isinstance(self.target_skill_ids, tuple)
                or not self.target_skill_ids):
            raise PolicyRankingDenied("Invalid reviewed curriculum policy context")
        for skills in (self.prerequisite_skill_ids, self.target_skill_ids):
            if (len(skills) != len(set(skills))
                    or any(not isinstance(x, str) or not x.strip() for x in skills)):
                raise PolicyRankingDenied("Invalid prerequisite or target skills")


@dataclass(frozen=True)
class ScopedObservation:
    """Evidence scoped to the learner by an independently authorized caller."""

    campus_id: str
    learner_ref: str
    evidence: LearningEvidence


@dataclass(frozen=True)
class PolicyRankedCitation:
    """Inspectable per-term score output; deliberately no learner ID or log."""

    citation: RankedCitation
    weight_version: str
    prerequisite_score: float
    learner_fit_score: float
    prerequisite_evidence_refs: tuple[str, ...]
    observation_evidence_refs: tuple[str, ...]
    effectiveness_score: float
    score: float

    @property
    def terms(self) -> tuple[tuple[str, float], ...]:
        """A PII-free, stable term breakdown for authorized UI inspection."""
        return (
            ("rrf", self.citation.rrf_score),
            ("reliability", self.citation.reliability_score),
            ("alignment", self.citation.alignment_score),
            ("objective", self.citation.objective_score),
            ("prerequisite", self.prerequisite_score),
            ("learner_fit", self.learner_fit_score),
            ("effectiveness", self.effectiveness_score),
        )


def rerank_for_learner(
    citations: tuple[RankedCitation, ...] | list[RankedCitation],
    contexts: tuple[PolicyContext, ...] | list[PolicyContext],
    profile: LearnerEvolutionProfile,
    observations: tuple[ScopedObservation, ...] | list[ScopedObservation],
    *,
    campus_id: str,
    learner_ref: str,
    objective_id: str,
    weights: PolicyWeights = PolicyWeights(),
    limit: int = 10,
) -> tuple[PolicyRankedCitation, ...]:
    """Add P (prerequisites) and L (observed support) without inferring labels.

    Missing skill evidence produces a neutral score, never a diagnostic claim.
    Human/parent observations are signals, not permanent learner attributes.
    This cannot authorize a lesson, mutate a profile, or approve a follow-up.
    """
    if not curriculum_engine_enabled():
        raise PolicyRankingDenied("Curriculum engine disabled")
    if (not isinstance(profile, LearnerEvolutionProfile)
            or not isinstance(weights, PolicyWeights)
            or not isinstance(campus_id, str) or not campus_id.strip()
            or not isinstance(learner_ref, str) or not learner_ref.strip()
            or not isinstance(objective_id, str) or not objective_id.strip()
            or profile.campus_id != campus_id or profile.learner_ref != learner_ref
            or type(limit) is not int or not 1 <= limit <= 20
            or not isinstance(citations, (tuple, list))
            or not isinstance(contexts, (tuple, list))
            or not isinstance(observations, (tuple, list))
            or len(citations) > _MAX_ITEMS or len(contexts) > _MAX_ITEMS
            or len(observations) > _MAX_OBSERVATIONS):
        raise PolicyRankingDenied("Invalid or mismatched learner policy scope")
    if (any(not isinstance(c, RankedCitation) for c in citations)
            or any(not isinstance(c, PolicyContext) for c in contexts)
            or any(not isinstance(o, ScopedObservation) or
                   not isinstance(o.evidence, LearningEvidence) for o in observations)):
        raise PolicyRankingDenied("Invalid reviewed ranking or scoped evidence")

    by_key = {(c.chunk_id, c.version): c for c in contexts}
    citation_keys = [(c.hit.chunk_id, c.hit.version) for c in citations]
    if (len(by_key) != len(contexts)
            or len(set(citation_keys)) != len(citation_keys)
            or set(by_key) != set(citation_keys)):
        raise PolicyRankingDenied("Duplicate or missing policy metadata")

    skills = {s.skill_id: s for s in profile.skills}
    known_refs = {
        (s.skill_id, ref) for s in profile.skills for ref in s.evidence_refs
    }
    observation_refs: set[str] = set()
    for item in observations:
        evidence = item.evidence
        if (item.campus_id != campus_id or item.learner_ref != learner_ref
                or evidence.evidence_ref in observation_refs
                or (evidence.skill_id, evidence.evidence_ref) not in known_refs
                or evidence.observed_at > profile.updated_at):
            raise PolicyRankingDenied("Observation not bound to this learner profile")
        observation_refs.add(evidence.evidence_ref)

    ranked = []
    for citation in citations:
        key = (citation.hit.chunk_id, citation.hit.version)
        context = by_key[key]
        if (context.campus_id != campus_id or context.objective_id != objective_id
                or citation.objective_id != objective_id
                or context.review_ref != citation.review_ref
                or not all(_valid_unit(v) for v in (
                    citation.rrf_score, citation.reliability_score,
                    citation.alignment_score, citation.objective_score,
                    citation.effectiveness_score))
                or citation.effectiveness_score != 0.0):
            raise PolicyRankingDenied("Review or objective mismatch in ranked citation")

        prereq_refs: set[str] = set()
        prereq_terms = []
        for skill_id in context.prerequisite_skill_ids:
            skill = skills.get(skill_id)
            if skill is None:
                prereq_terms.append(0.5)  # Unknown is not failure or mastery.
            else:
                prereq_refs.update(skill.evidence_refs)
                prereq_terms.append(
                    0.5 + skill.confidence * (skill.mastery - 0.5)
                )
        p = sum(prereq_terms) / len(prereq_terms) if prereq_terms else 1.0

        relevant = tuple(
            item.evidence for item in observations
            if item.evidence.skill_id in context.target_skill_ids
            and item.evidence.kind in _SUPPORT_KINDS
            and item.evidence.instructional_response in _SUPPORTED_RESPONSE
        )
        if relevant:
            observed_need = sum(
                _SUPPORTED_RESPONSE[e.instructional_response] for e in relevant
            ) / len(relevant)
            confidence = min(0.8, len(relevant) / (len(relevant) + 3))
            # Learner-fit expresses temporary response to *observed* support,
            # not a preferred modality or permanent learning-style identity.
            raw_fit = 1.0 - abs(context.scaffolding_intensity - observed_need)
            learner_fit = 0.5 + confidence * (raw_fit - 0.5)
        else:
            learner_fit = 0.5  # No evidence: neutral, no personalization claim.

        score = (
            weights.rrf * citation.rrf_score
            + weights.reliability * citation.reliability_score
            + weights.alignment * citation.alignment_score
            + weights.objective * citation.objective_score
            + weights.prerequisite * p
            + weights.learner_fit * learner_fit
        )
        ranked.append(PolicyRankedCitation(
            citation=citation, weight_version=weights.version,
            prerequisite_score=round(p, 8),
            learner_fit_score=round(learner_fit, 8),
            prerequisite_evidence_refs=tuple(sorted(prereq_refs)),
            observation_evidence_refs=tuple(sorted(e.evidence_ref for e in relevant)),
            effectiveness_score=0.0, score=round(score, 8),
        ))
    return tuple(sorted(
        ranked,
        key=lambda item: (-item.score, item.citation.hit.chunk_id,
                          item.citation.hit.version),
    )[:limit])
