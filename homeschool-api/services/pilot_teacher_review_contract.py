"""Strict, advisory-only teacher review envelope for the Valor pilot.

Pure validation boundary; API authorization still belongs to the scoped
canonical assessment/decision/artifact routers. No model output is trusted
to grant itself approval or mutate a learner roster.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TenantScope(Strict):
    campus_id: UUID
    educator_id: UUID
    learner_ids: list[UUID] = Field(min_length=1, max_length=90)
    subject_area: str = Field(min_length=1, max_length=80)
    class_section_id: str | None = None

    @model_validator(mode="after")
    def unique_learners(self):
        if len(set(self.learner_ids)) != len(self.learner_ids):
            raise ValueError("Learners must not be duplicated")
        return self


class OfficialAssessment(Strict):
    record_id: UUID
    campus_id: UUID
    learner_id: UUID
    instrument: Literal["DIBELS_8", "TEACHER_OBSERVATION", "CURRICULUM_BASED_MEASURE", "OTHER"]
    measure: str = Field(min_length=1, max_length=36)
    purpose: Literal["benchmark", "progress_monitoring", "instructional_check", "teacher_observation"]
    benchmark_window: Literal["BOY", "MOY", "EOY", "not_applicable"]
    administration_status: Literal["draft", "in_progress", "completed_pending_review", "finalized", "interrupted", "invalid", "voided", "superseded"]
    snapshot_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    official_score_fields: dict = Field(default_factory=dict)
    finalized_by: UUID | None = None
    finalized_at: datetime | None = None

    @model_validator(mode="after")
    def official_record_is_distinct(self):
        if self.purpose == "benchmark" and self.benchmark_window == "not_applicable":
            raise ValueError("Benchmark requires its official window")
        if self.purpose != "benchmark" and self.benchmark_window != "not_applicable":
            raise ValueError("Progress monitoring and observations are not benchmarks")
        if self.instrument == "TEACHER_OBSERVATION" and self.official_score_fields:
            raise ValueError("Teacher observations cannot create official DIBELS scores")
        if self.administration_status == "finalized" and not (
            self.snapshot_sha256 and self.finalized_by and self.finalized_at
        ):
            raise ValueError("Finalized assessment requires snapshot and teacher attestation")
        return self


class EvidenceReview(Strict):
    evidence_ids: list[UUID] = Field(default_factory=list)
    candidate_patterns: list[str] = Field(default_factory=list)
    candidate_misconceptions: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    advisory_only: Literal[True] = True


class ProposedAction(Strict):
    action_id: UUID
    action_type: Literal[
        "generate_teacher_prep_brief", "generate_printable_practice",
        "generate_grouping_cards", "generate_observation_sheet",
        "create_review_packet", "update_draft_grouping_only",
    ]
    approval_required: Literal[True] = True
    status: Literal["proposed", "approved_for_execution", "executed", "rejected"]


class TeacherDecision(Strict):
    decision_id: UUID
    decision_status: Literal[
        "draft", "pending_teacher_review", "teacher_approved",
        "teacher_edited_and_approved", "teacher_rejected", "superseded",
    ]
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    selected_action_ids: list[UUID] = Field(default_factory=list)
    approved_record_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def approval_attested(self):
        if self.decision_status in ("teacher_approved", "teacher_edited_and_approved"):
            if not (self.reviewed_by and self.reviewed_at and self.approved_record_version):
                raise ValueError("Teacher approval requires reviewer, time and version")
        return self


class GeneratedArtifact(Strict):
    artifact_id: UUID
    action_id: UUID
    decision_id: UUID
    artifact_type: Literal[
        "teacher_prep_brief", "socratic_warmup_pdf", "tiered_practice_pack",
        "answer_key", "grouping_cards", "observation_sheet", "data_day_review_packet",
    ]
    paper_format: Literal["US_LETTER_BW", "US_LETTER_COLOR", "A4_BW", "A4_COLOR"]
    local_file_path: str = Field(min_length=1, max_length=1024)
    approval_version: int = Field(ge=1)


class AuthorizationContext(Strict):
    subject_id: UUID
    tenant_id: UUID
    resource_ids: list[UUID] = Field(min_length=1)
    action: Literal["review", "approve", "prepare_teacher_artifact", "record_follow_up"]


class TeacherReviewCycle(Strict):
    schema_version: Literal["1.1.0"]
    cycle_id: UUID
    record_version: int = Field(ge=1)
    tenant_scope: TenantScope
    official_assessment_record: OfficialAssessment
    evidence_review: EvidenceReview
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    teacher_decision: TeacherDecision
    generated_artifacts: list[GeneratedArtifact] = Field(default_factory=list)
    authorization_context: AuthorizationContext
    delivery_state: Literal["NOT_REQUESTED"] = "NOT_REQUESTED"

    @model_validator(mode="after")
    def enforce_teacher_authority(self):
        scope = self.tenant_scope
        official = self.official_assessment_record
        decision = self.teacher_decision
        auth = self.authorization_context
        if official.campus_id != scope.campus_id or official.learner_id not in scope.learner_ids:
            raise ValueError("Official record is outside the assigned tenant/learner scope")
        if auth.subject_id != scope.educator_id or auth.tenant_id != scope.campus_id:
            raise ValueError("Authorization actor or campus does not match this cycle")
        if official.learner_id not in auth.resource_ids:
            raise ValueError("Authorization must name the exact learner")
        if self.proposed_actions and official.instrument == "DIBELS_8" and official.administration_status != "finalized":
            raise ValueError("Final DIBELS-based recommendations require a finalized official record")
        actions = {a.action_id: a for a in self.proposed_actions}
        if len(actions) != len(self.proposed_actions):
            raise ValueError("Duplicate proposed action identifiers")
        approved = decision.decision_status in ("teacher_approved", "teacher_edited_and_approved")
        if self.generated_artifacts and not approved:
            raise ValueError("Artifacts require an explicit teacher approval")
        if approved and (decision.reviewed_by != scope.educator_id or decision.approved_record_version != self.record_version):
            raise ValueError("Approval must be signed by this educator for the current record version")
        if not set(decision.selected_action_ids).issubset(actions):
            raise ValueError("Teacher selected an unknown action")
        for artifact in self.generated_artifacts:
            action = actions.get(artifact.action_id)
            if (action is None or action.status not in ("approved_for_execution", "executed")
                    or artifact.action_id not in decision.selected_action_ids
                    or artifact.decision_id != decision.decision_id
                    or artifact.approval_version != self.record_version):
                raise ValueError("Artifact has no matching approved, current-version teacher action")
        return self
