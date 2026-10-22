"""Data model and invariants for Bede's curriculum corpus.

These are plain, frozen dataclasses. They hold no database code. Persistence
(new tables only) comes in a later PR.

The approved base library changes only through staged, human-reviewed
promotion. Per-learner adaptation lives in LessonVariant, a derived record that
expires so it is regenerated instead of going stale.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Set, Tuple


class CurriculumModelError(ValueError):
    """Raised when a record breaks a curriculum invariant."""


class RightsStatus(str, Enum):
    public_domain_verified = "public_domain_verified"
    licensed = "licensed"
    original = "original"
    teacher_private = "teacher_private"
    unverified = "unverified"


class ItemStatus(str, Enum):
    staged = "staged"
    in_review = "in_review"
    approved = "approved"
    retired = "retired"


class Visibility(str, Enum):
    campus = "campus"
    teacher_private = "teacher_private"


class ReviewDecision(str, Enum):
    approve = "approve"
    reject = "reject"
    request_changes = "request_changes"


_NON_HUMAN_PREFIXES = ("agent:", "system:", "ai:", "bot:", "copilot", "claude", "gpt")
_OPAQUE_REF = re.compile(r"^[A-Za-z0-9_-]{8,}$")


def is_human_reviewer(name: str) -> bool:
    """A reviewer name counts as human unless it is blank or names an agent."""
    cleaned = (name or "").strip().lower()
    return bool(cleaned) and not cleaned.startswith(_NON_HUMAN_PREFIXES)


def _require(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CurriculumModelError(f"{label} is required.")


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    edition: str
    source_url: str
    retrieved_at: datetime
    content_hash: str
    rights_status: RightsStatus

    def __post_init__(self) -> None:
        for label in ("source_id", "edition", "source_url", "content_hash"):
            _require(getattr(self, label), label)


@dataclass(frozen=True)
class ReviewRecord:
    review_id: str
    item_id: str
    item_version: int
    reviewed_by: str
    reviewed_at: datetime
    decision: ReviewDecision
    notes: str = ""

    def __post_init__(self) -> None:
        for label in ("review_id", "item_id", "reviewed_by"):
            _require(getattr(self, label), label)
        if self.item_version < 1:
            raise CurriculumModelError("item_version must be 1 or greater.")


def require_approvable(
    *,
    item_id: str,
    version: int,
    rights: Tuple[RightsStatus, ...],
    review: Optional[ReviewRecord],
) -> None:
    """Raise unless an item may hold the approved status."""
    if not rights:
        raise CurriculumModelError("An approved item must declare its rights status.")
    if RightsStatus.unverified in rights:
        raise CurriculumModelError("An item with unverified rights cannot be approved.")
    if review is None:
        raise CurriculumModelError("Approval requires a ReviewRecord.")
    if review.decision != ReviewDecision.approve:
        raise CurriculumModelError("The ReviewRecord does not approve this item.")
    if review.item_id != item_id or review.item_version != version:
        raise CurriculumModelError("The ReviewRecord is for a different item or version.")
    if not is_human_reviewer(review.reviewed_by):
        raise CurriculumModelError("Approval requires a human reviewer.")


@dataclass(frozen=True)
class ContentChunk:
    chunk_id: str
    source_id: str
    locator: str
    text: str
    verbatim: bool
    source_edition: str
    rights_status: RightsStatus
    objective_ids: Tuple[str, ...]
    subject: str
    stage: str
    campus_id: str
    visibility: Visibility
    status: ItemStatus
    version: int
    generated: bool = False
    review: Optional[ReviewRecord] = None

    def __post_init__(self) -> None:
        for label in ("chunk_id", "source_id", "locator", "text", "subject", "stage", "campus_id"):
            _require(getattr(self, label), label)
        if self.version < 1:
            raise CurriculumModelError("version must be 1 or greater.")
        if self.verbatim:
            if self.rights_status != RightsStatus.public_domain_verified:
                raise CurriculumModelError(
                    "Verbatim text requires public_domain_verified rights."
                )
            _require(self.source_edition, "source_edition (required for verbatim text)")
        if self.status == ItemStatus.approved:
            require_approvable(
                item_id=self.chunk_id,
                version=self.version,
                rights=(self.rights_status,),
                review=self.review,
            )


@dataclass(frozen=True)
class Lesson:
    lesson_id: str
    title: str
    objective_ids: Tuple[str, ...]
    skill_ids: Tuple[str, ...]
    subject: str
    stage: str
    campus_id: str
    visibility: Visibility
    status: ItemStatus
    version: int
    source_ids: Tuple[str, ...]
    source_rights: Tuple[RightsStatus, ...]
    generated: bool = False
    review: Optional[ReviewRecord] = None

    def __post_init__(self) -> None:
        for label in ("lesson_id", "title", "subject", "stage", "campus_id"):
            _require(getattr(self, label), label)
        if self.version < 1:
            raise CurriculumModelError("version must be 1 or greater.")
        if self.status == ItemStatus.approved:
            require_approvable(
                item_id=self.lesson_id,
                version=self.version,
                rights=self.source_rights,
                review=self.review,
            )


@dataclass(frozen=True)
class LessonVariant:
    """A learner-scoped adaptation of an approved lesson version.

    It never replaces the parent lesson. It expires at refresh_after so it is
    regenerated from current mastery evidence instead of going stale.
    """

    variant_id: str
    parent_lesson_id: str
    parent_version: int
    campus_id: str
    learner_ref: str
    adaptation_basis: Tuple[str, ...]
    created_at: datetime
    refresh_after: datetime
    status: ItemStatus = ItemStatus.staged
    generated: bool = True

    def __post_init__(self) -> None:
        for label in ("variant_id", "parent_lesson_id", "campus_id"):
            _require(getattr(self, label), label)
        if self.parent_version < 1:
            raise CurriculumModelError("parent_version must be 1 or greater.")
        if not _OPAQUE_REF.match(self.learner_ref or ""):
            raise CurriculumModelError(
                "learner_ref must be an opaque identifier of at least 8 letters, digits, '_' or '-'."
            )
        if not self.adaptation_basis or not all(
            ref.startswith("evidence:") for ref in self.adaptation_basis
        ):
            raise CurriculumModelError(
                "adaptation_basis must cite evidence references (prefix 'evidence:'), not raw scores."
            )
        if self.refresh_after <= self.created_at:
            raise CurriculumModelError("refresh_after must be later than created_at.")

    def is_stale(self, now: datetime) -> bool:
        return now >= self.refresh_after


def validate_variant_parent(variant: LessonVariant, parent: Lesson) -> None:
    """A variant must derive from an approved parent version in the same campus."""
    if parent.status != ItemStatus.approved:
        raise CurriculumModelError("A variant must derive from an approved lesson.")
    if parent.lesson_id != variant.parent_lesson_id or parent.version != variant.parent_version:
        raise CurriculumModelError("The variant does not match this parent lesson version.")
    if parent.campus_id != variant.campus_id:
        raise CurriculumModelError("A variant must stay in its parent lesson's campus.")


def validate_skill_ids(skill_ids: Tuple[str, ...]) -> None:
    """Declared skills must already exist in the diagnostic engine."""
    from services.content_curation import known_skill_ids

    unknown: Set[str] = {skill for skill in skill_ids if skill not in known_skill_ids()}
    if unknown:
        raise CurriculumModelError(
            f"Unknown skill ids: {', '.join(sorted(unknown))}. Growing a skill map is a separate reviewed change."
        )
