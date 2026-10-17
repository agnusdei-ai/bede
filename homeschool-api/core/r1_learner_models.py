"""R1 supervised lesson-delivery state and scope primitives.

These records deliberately do not alter the existing educator-only pilot
recommendation delivery CHECK constraint. No learner route is enabled by
importing this module. Launch capability exchange and authorization gates
must be implemented before these records can authorize delivery.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LessonApproval(Base):
    __tablename__ = "r1_lesson_approvals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    lesson_id: Mapped[str] = mapped_column(String(36), nullable=False)
    lesson_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    teacher_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campus_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    scope_json: Mapped[str] = mapped_column(Text, nullable=False)
    interaction_policy_json: Mapped[str] = mapped_column(Text, nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    __table_args__ = (UniqueConstraint("lesson_id", "lesson_version", name="uq_r1_lesson_version"),)


class LearnerAssignment(Base):
    __tablename__ = "r1_learner_assignments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    approval_id: Mapped[str] = mapped_column(String(36), ForeignKey("r1_lesson_approvals.id"), nullable=False)
    approval_version: Mapped[int] = mapped_column(Integer, nullable=False)
    campus_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    assigned_by: Mapped[str] = mapped_column(String(36), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    launch_policy_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ASSIGNED")


class LearnerLaunchGrant(Base):
    __tablename__ = "r1_learner_launch_grants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    assignment_id: Mapped[str] = mapped_column(String(36), ForeignKey("r1_learner_assignments.id"), nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campus_id: Mapped[str] = mapped_column(String(36), nullable=False)
    approval_id: Mapped[str] = mapped_column(String(36), nullable=False)
    approval_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    permitted_actions_json: Mapped[str] = mapped_column(Text, nullable=False)
    issued_by: Mapped[str] = mapped_column(String(36), nullable=False)
    capability_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grant_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ISSUED")


class LearnerSession(Base):
    __tablename__ = "r1_learner_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    assignment_id: Mapped[str] = mapped_column(String(36), ForeignKey("r1_learner_assignments.id"), nullable=False)
    launch_grant_id: Mapped[str] = mapped_column(String(36), ForeignKey("r1_learner_launch_grants.id"), nullable=False)
    credential_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campus_id: Mapped[str] = mapped_column(String(36), nullable=False)
    approval_id: Mapped[str] = mapped_column(String(36), nullable=False)
    approval_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    interaction_policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    authorization_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="CREATED")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LessonInteraction(Base):
    __tablename__ = "r1_lesson_interactions"
    __table_args__ = (UniqueConstraint("session_id", "sequence", name="uq_r1_session_sequence"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("r1_learner_sessions.id"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    interaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    learner_input_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    assistant_output_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    approved_lesson_reference: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    authorization_version: Mapped[int] = mapped_column(Integer, nullable=False)
    persistence_status: Mapped[str] = mapped_column(String(24), nullable=False)


class ProgressEvent(Base):
    __tablename__ = "r1_progress_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("r1_learner_sessions.id"), nullable=False)
    assignment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    authorization_version: Mapped[int] = mapped_column(Integer, nullable=False)


class DeliveryReceipt(Base):
    __tablename__ = "r1_delivery_receipts"
    __table_args__ = (UniqueConstraint("session_id", "outcome", name="uq_r1_receipt_outcome"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    assignment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("r1_learner_sessions.id"), nullable=False)
    approval_id: Mapped[str] = mapped_column(String(36), nullable=False)
    approval_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campus_id: Mapped[str] = mapped_column(String(36), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    last_persisted_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    integrity_value: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
