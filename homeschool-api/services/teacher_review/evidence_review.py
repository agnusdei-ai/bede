"""Bede interpretations are evidence-linked, provisional teaching hypotheses.

Model output never grants access or changes official assessment records.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field

from .official_assessment import StrictRecord

Confidence = Literal["low", "medium", "high"]


class CandidatePattern(StrictRecord):
    pattern_tag: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1800)
    confidence_level: Confidence
    evidence_refs: list[UUID] = Field(default_factory=list, max_length=100)
    affected_learner_ids: list[str] = Field(default_factory=list, max_length=90)


class CandidateMisconception(StrictRecord):
    concept_tag: str = Field(min_length=1, max_length=100)
    hypothesis: str = Field(min_length=1, max_length=1800)
    confidence_level: Confidence
    severity: Literal["isolated", "small_group", "widespread", "critical"]
    evidence_refs: list[UUID] = Field(default_factory=list, max_length=100)
    affected_learner_ids: list[str] = Field(default_factory=list, max_length=90)
    teacher_review_required: Literal[True] = True


class EvidenceReview(StrictRecord):
    candidate_patterns: list[CandidatePattern] = Field(default_factory=list, max_length=100)
    candidate_misconceptions: list[CandidateMisconception] = Field(default_factory=list, max_length=100)
    instructional_considerations: list[str] = Field(default_factory=list, max_length=40)
    sources_used: list[str] = Field(default_factory=list, max_length=100)


class SuggestedGrouping(StrictRecord):
    group_label: str = Field(min_length=1, max_length=100)
    learner_ids: list[str] = Field(min_length=1, max_length=90)
    rationale: str = Field(min_length=1, max_length=1200)


class TeacherSupportPlan(StrictRecord):
    pacing_phase: Literal[
        "introduction_socratic", "guided_practice", "mastery_assessment",
        "remediation_tiering", "review_conference", "data_day_review",
    ]
    suggested_socratic_prompts: list[str] = Field(default_factory=list, max_length=20)
    suggested_whiteboard_structure: str = Field(default="", max_length=1800)
    suggested_groupings: list[SuggestedGrouping] = Field(default_factory=list, max_length=30)
    suggested_next_steps: list[str] = Field(default_factory=list, max_length=30)
    classical_mode: Literal["grammar", "logic", "rhetoric", "mixed"] | None = None
    instructional_domain: Literal[
        "phonics", "fluency", "comprehension", "composition", "math",
        "latin", "seminar",
    ] | None = None
    review_priority: Literal["routine", "urgent", "data_day"] = "routine"
