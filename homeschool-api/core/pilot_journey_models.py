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
  deleted or reordered decision is detectable. No route updates or deletes
  it, and ``tests/test_valor_pilot_g2_journey.py`` asserts that.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


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


class PilotSessionPlan(Base):
    """Owner-set tutoring plan for one pilot learner (grade + subjects).

    A pilot learner has no name-keyed ``StudentConfig``, so this is the only
    authority for what a live session may teach. Set by the owner with an
    administrator passkey; validated by constructing a real ``SessionConfig``.
    """
    __tablename__ = "pilot_session_plans"

    learner_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campus_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    plan_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False,
    )


class PilotSessionLaunch(Base):
    """One live tutoring session an educator started for a pilot learner.

    Pins the exact authorized instruction (by recommendation id and SHA-256)
    at launch, so what reaches the learner is what the teacher approved even
    if a newer decision lands mid-session. Turn count and timestamps make the
    row a session receipt the owner can attach as evidence.
    """
    __tablename__ = "pilot_session_launches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campus_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    educator_id: Mapped[str] = mapped_column(String(36), nullable=False)
    recommendation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    instruction_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    instruction_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False,
    )
    turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_turn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PilotDeletionReceipt(Base):
    """Tombstone proving an owner-led deletion of one pilot learner.

    Holds no learner content: only the random UUIDs, per-table counts deleted,
    the post-delete re-check (which must be all zeros), who did it and when,
    and a SHA-256 over those fields so a receipt the owner exported can be
    checked against the server's copy.
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
