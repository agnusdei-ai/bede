"""Valor pilot G2 tables: evidence -> recommendation -> educator decision.

Kept in its own module (registered on the shared ``Base``) so the G2
journey can land independently of G1's ``core/database.py`` edits. Every
row is scoped by the immutable campus and learner UUIDs G1 introduced;
nothing here is keyed by a display name.

Three deliberate properties:

* **Evidence and recommendation text are AES-256-GCM ciphertext** bound by
  AAD to ``campus:learner:row`` so a blob copied into another learner's row
  fails to decrypt rather than silently attaching to the wrong child.
* **A recommendation changes state only through a version-checked
  compare-and-swap** (``status='pending' AND version=:expected``), so a
  replayed or concurrent second decision is refused, never applied twice.
* **``PilotDecision`` is an append-only, hash-chained ledger.** Each entry
  commits to the previous entry's hash for the same learner, so a
  deleted or reordered decision is detectable. No teacher route updates or
  deletes it, and ``tests/test_valor_pilot_g2_journey.py`` asserts that.
  The single exception is the owner's whole-learner erasure
  (``routers/pilot_owner.py``), which removes a learner's entire chain at
  once and leaves a content-free ``PilotDeletionReceipt`` in its place.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint, DateTime, Integer, LargeBinary, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


# Owner Decision 7: delivering a recorded instructional plan into a learner's
# tutoring session is unavailable until #585. Every recommendation therefore
# carries an explicit delivery state whose ONLY permitted value is this one,
# enforced by a database CHECK constraint as well as by code, so no route,
# service or hand-written UPDATE can move it. Adding a second state is a
# schema change that must accompany the full delivery flow documented in
# docs/EDUCATOR_CLASSROOM_PILOT.md; tests/test_valor_pilot_delivery_disabled.py
# fails until it does.
DELIVERY_NOT_REQUESTED = "NOT_REQUESTED"
DELIVERY_STATES = (DELIVERY_NOT_REQUESTED,)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PilotEvidence(Base):
    """Educator-entered assessment evidence for one pilot learner."""
    __tablename__ = "pilot_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campus_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(36), nullable=False)
    detail_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False,
    )


class PilotRecommendation(Base):
    """A source-linked instructional recommendation awaiting a teacher."""
    __tablename__ = "pilot_recommendations"
    __table_args__ = (
        CheckConstraint(f"delivery_state = '{DELIVERY_NOT_REQUESTED}'",
                        name="ck_pilot_recommendation_delivery_not_requested"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campus_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(36), nullable=False)
    # pending -> approved | edited | rejected. Never back to pending.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    # JSON list of PilotEvidence ids. Ids only; never evidence content.
    source_evidence_ids: Mapped[str] = mapped_column(Text, nullable=False)
    proposal_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Set only on approve/edit: the instruction the teacher authorized.
    authorized_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # See DELIVERY_NOT_REQUESTED above. Never written after insert.
    delivery_state: Mapped[str] = mapped_column(
        String(24), nullable=False, default=DELIVERY_NOT_REQUESTED,
        server_default=DELIVERY_NOT_REQUESTED,
    )
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class PilotDecision(Base):
    """Append-only, hash-chained record of every educator decision."""
    __tablename__ = "pilot_decisions"
    # One chain per learner: seq is that learner's 1-based decision number,
    # and the unique pair makes two concurrent appends collide instead of
    # forking the chain.
    __table_args__ = (UniqueConstraint("learner_id", "seq", name="uq_pilot_decision_seq"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    recommendation_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    campus_id: Mapped[str] = mapped_column(String(36), nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    educator_id: Mapped[str] = mapped_column(String(36), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    from_version: Mapped[int] = mapped_column(Integer, nullable=False)
    to_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # SHA-256 of the exact instruction text authorized ("" on reject).
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    note_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False,
    )


class PilotDeletionReceipt(Base):
    """Content-free record of an owner-led deletion of one pilot learner.

    Holds no learner content and no display name: only the random UUIDs,
    the per-table counts removed, the re-check of what remained afterwards
    (all zeros, or the deletion is rolled back), who performed it and when,
    and a SHA-256 over those fields so a copy the owner kept can be checked
    against the server's. ``routers/pilot_owner.py`` writes it.
    """
    __tablename__ = "pilot_deletion_receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campus_id: Mapped[str] = mapped_column(String(36), nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    deleted_counts: Mapped[str] = mapped_column(Text, nullable=False)
    remaining_counts: Mapped[str] = mapped_column(Text, nullable=False)
    receipt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False,
    )


QUIZ_RESULT_CURRENT = "current"
QUIZ_RESULT_SUPERSEDED = "superseded"


class PilotQuizResult(Base):
    """A teacher-confirmed classroom quiz result for one pilot learner.

    Classroom evidence, deliberately NOT a canonical assessment record and
    never copied into one (``routers/pilot_assessments.py`` holds those).
    ``submission_id`` is the client's id for one save, so a retry returns the
    original row instead of a second result. A correction is a new row that
    names the row it replaces; the replaced row becomes ``superseded`` and no
    longer counts anywhere. Only ``current`` rows feed the mastery estimate,
    which is computed when read and never stored
    (``services/teacher_quiz_records.py``). The detail (quiz snapshot and the
    teacher's settled points) is ciphertext bound to ``campus:learner:row``.
    """
    __tablename__ = "pilot_quiz_results"
    __table_args__ = (
        UniqueConstraint("campus_id", "learner_id", "submission_id",
                         name="uq_pilot_quiz_result_submission"),
        CheckConstraint(f"status IN ('{QUIZ_RESULT_CURRENT}', '{QUIZ_RESULT_SUPERSEDED}')",
                        name="ck_pilot_quiz_result_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campus_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    submission_id: Mapped[str] = mapped_column(String(64), nullable=False)
    body_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=QUIZ_RESULT_CURRENT, nullable=False)
    supersedes: Mapped[str | None] = mapped_column(String(36), nullable=True)
    superseded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    detail_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False,
    )
