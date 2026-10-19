"""Only educator decisions can authorize teacher-use artifacts.

This is not a student-delivery, roster-mutation, or autonomous agent API.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .official_assessment import StrictRecord

ActionType = Literal[
    "generate_teacher_prep_brief",
    "generate_printable_practice",
    "generate_grouping_cards",
    "generate_observation_sheet",
    "create_review_packet",
    "update_draft_grouping_only",
]
ActionStatus = Literal["proposed", "approved_for_execution", "executed", "rejected"]
DecisionStatus = Literal[
    "draft", "pending_teacher_review", "teacher_approved",
    "teacher_edited_and_approved", "teacher_rejected", "superseded",
]
APPROVED = frozenset({"teacher_approved", "teacher_edited_and_approved"})


class ProposedAction(StrictRecord):
    action_id: UUID
    action_type: ActionType
    # Inputs are proposals, not executable model-generated instructions.
    parameters: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict, max_length=30
    )
    approval_required: Literal[True] = True
    status: ActionStatus = "proposed"


class TeacherDecision(StrictRecord):
    decision_id: UUID
    decision_status: DecisionStatus
    teacher_override_notes: str | None = Field(default=None, max_length=1200)
    teacher_selected_actions: list[UUID] = Field(default_factory=list, max_length=30)
    teacher_selected_next_steps: list[str] = Field(default_factory=list, max_length=30)
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    # Signed off against the exact campus/learner/assessment/plan/version
    # canonical digest, so editing a proposal cannot reuse an old approval.
    approved_record_version: int | None = Field(default=None, ge=1)
    approval_basis_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def require_actual_review(self):
        if len(set(self.teacher_selected_actions)) != len(self.teacher_selected_actions):
            raise ValueError("Duplicate selected actions")
        if self.decision_status in APPROVED:
            if not self.reviewed_by or not self.reviewed_at:
                raise ValueError("Teacher approval requires reviewer identity and timestamp")
            if self.approved_record_version is None or not self.approval_basis_sha256:
                raise ValueError("Teacher approval must bind exact record version and content hash")
        else:
            if self.teacher_selected_actions:
                raise ValueError("Unapproved/rejected decisions cannot select actions")
            if self.approved_record_version is not None or self.approval_basis_sha256 is not None:
                raise ValueError("Unapproved/rejected decisions cannot retain an approval")
        return self
