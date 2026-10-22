"""Offline, teacher-governed classical source retrieval and learning-gap proposals.

No web access, model calls, student profiling, or automatic curriculum changes.
Only independently verified, commercially compatible source records may enter search.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import log
import re
from typing import Iterable

ALLOWED_RIGHTS = frozenset({"US_PUBLIC_DOMAIN_VERIFIED", "CC0", "CC_BY_4_0", "ORIGINAL_APPROVED"})
WORDS = re.compile(r"[a-z0-9]+")


def tokens(value: str) -> set[str]:
    return set(WORDS.findall(value.lower()))


@dataclass(frozen=True)
class ClassicalSource:
    source_id: str
    title: str
    text: str
    subject: str
    skills: tuple[str, ...]
    rights: str
    rights_verified: bool
    approved: bool
    citation: str
    version: str


@dataclass(frozen=True)
class SkillEvidence:
    skill_id: str
    correct: int
    attempted: int
    independently_scored: bool
    session_id: str


@dataclass(frozen=True)
class LearningProposal:
    skill_id: str
    reason: str
    source_ids: tuple[str, ...]
    citations: tuple[str, ...]
    requires_educator_approval: bool = True


def eligible(source: ClassicalSource) -> bool:
    return bool(
        source.approved and source.rights_verified
        and source.rights in ALLOWED_RIGHTS
        and source.source_id and source.version and source.citation
    )


def search(
    sources: Iterable[ClassicalSource],
    *,
    subject: str,
    skill_id: str,
    query: str,
    limit: int = 5,
) -> list[ClassicalSource]:
    """Deterministic lexical retrieval over an approved local source index.

    A later hybrid embedding index may rerank, but cannot bypass eligibility.
    """
    if limit < 1 or limit > 20:
        raise ValueError("limit must be 1..20")
    query_terms = tokens(query) | tokens(skill_id.replace("_", " "))
    ranked = []
    for source in sources:
        if not eligible(source) or source.subject != subject or skill_id not in source.skills:
            continue
        title_hits = len(query_terms & tokens(source.title))
        body_hits = len(query_terms & tokens(source.text))
        score = 3 * title_hits + min(body_hits, 20)
        ranked.append((score, source.source_id, source))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked[:limit]]


def propose_follow_up(
    *,
    sources: Iterable[ClassicalSource],
    subject: str,
    skill_id: str,
    evidence: Iterable[SkillEvidence],
    query: str,
) -> LearningProposal:
    """Flag repeated academic difficulty without inferring a diagnosis.

    Independent scoring is required. Missing data yields a review request,
    never a claim that a learner lacks aptitude or has a disorder.
    """
    observations = [
        e for e in evidence
        if e.skill_id == skill_id and e.independently_scored
        and 0 <= e.correct <= e.attempted and e.attempted > 0
    ]
    total = sum(e.attempted for e in observations)
    correct = sum(e.correct for e in observations)
    sessions = len({e.session_id for e in observations})
    if total < 5 or sessions < 2:
        return LearningProposal(skill_id, "insufficient_independent_evidence_request_teacher_review", (), ())
    if correct / total >= 0.7:
        return LearningProposal(skill_id, "no_repeated_gap_established", (), ())
    matches = search(sources, subject=subject, skill_id=skill_id, query=query)
    if not matches:
        return LearningProposal(skill_id, "repeated_difficulty_no_verified_source_escalate_to_educator", (), ())
    return LearningProposal(
        skill_id, "repeated_difficulty_propose_alternative_representation_and_recheck",
        tuple(s.source_id for s in matches), tuple(s.citation for s in matches)
    )
