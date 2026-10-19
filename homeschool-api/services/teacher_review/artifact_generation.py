"""Metadata for verified, teacher-approved, local-use-only materials.

No model-proposed path is trusted as filesystem authority. A server-side
artifact renderer must supply the final path and revalidate grants first.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from .official_assessment import StrictRecord

ArtifactType = Literal[
    "teacher_prep_brief", "socratic_warmup_pdf", "tiered_practice_pack",
    "answer_key", "grouping_cards", "observation_sheet",
    "data_day_review_packet",
]
ARTIFACT_ACTIONS = {
    "teacher_prep_brief": "generate_teacher_prep_brief",
    "socratic_warmup_pdf": "generate_printable_practice",
    "tiered_practice_pack": "generate_printable_practice",
    "answer_key": "generate_printable_practice",
    "grouping_cards": "generate_grouping_cards",
    "observation_sheet": "generate_observation_sheet",
    "data_day_review_packet": "create_review_packet",
}


class GeneratedArtifact(StrictRecord):
    artifact_id: UUID
    artifact_type: ArtifactType
    paper_format: Literal["US_LETTER_BW", "US_LETTER_COLOR", "A4_BW", "A4_COLOR"]
    local_file_path: str = Field(min_length=1, max_length=400)
    decision_basis_refs: list[UUID] = Field(default_factory=list, max_length=100)
    generated_from_teacher_approval_id: UUID
    approved_action_id: UUID
    artifact_style_profile: Literal[
        "valor_bw", "toner_saver", "family_take_home", "teacher_markup",
    ] = "valor_bw"

    @field_validator("local_file_path")
    @classmethod
    def relative_artifact_path(cls, path: str) -> str:
        # Manifest paths stay relative; local API chooses a safe scoped root.
        # Absolute paths, Windows drive/UNC paths, URL schemes and traversal
        # are not trusted even if they came from an approved model response.
        if (path.startswith(("/", "\\")) or "\\" in path or ":" in path):
            raise ValueError("Artifact path must be a safe relative path")
        parts = PurePosixPath(path).parts
        if (not parts or parts[0] != "teacher-artifacts"
                or any(part in (".", "..") for part in path.split("/"))
                or path.endswith("/")):
            raise ValueError("Artifact path must be inside teacher-artifacts")
        return path


class SecurityAudit(StrictRecord):
    zero_cloud_egress: bool
    pii_sanitized: bool
    tenant_scope_rechecked: bool
    teacher_approval_rechecked: bool


class Verification(StrictRecord):
    math_key_verified: bool
    layout_integrity_passed: bool
    print_readability_passed: bool
    security_audit: SecurityAudit


class FollowUpObservation(StrictRecord):
    observation_due_window: str = Field(min_length=1, max_length=160)
    observation_prompt: str = Field(min_length=1, max_length=1000)
    recorded_observation_summary: str | None = Field(default=None, max_length=4000)
    recorded_at: datetime | None = None

    @field_validator("recorded_observation_summary")
    @classmethod
    def nonempty_if_recorded(cls, text: str | None) -> str | None:
        if text is not None and not text.strip():
            raise ValueError("Recorded observation cannot be blank")
        return text
