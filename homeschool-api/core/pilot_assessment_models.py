"""Canonical DIBELS / assessment tables, UUID-keyed, in their own module.

Registered on the shared ``Base`` (startup only runs ``CREATE TABLE IF NOT
EXISTS``; there is no ``ALTER TABLE`` path), and kept out of
``core/database.py`` so this lane lands without editing G1's models. Every
learner-scoped row carries G1's immutable campus UUID and learner UUID;
nothing here is keyed by a display name.

The record kinds are deliberately SEPARATE (docs/CANONICAL_ASSESSMENT_MODEL.md):

* ``PilotAssessmentAdministration`` -- one sitting or one transcribed vendor
  report: what was given, to whom, by whom, why, and when.
* ``PilotAssessmentScore`` -- one row per measure (and one for a composite),
  with its own administration status. A measure that was not administered
  has NO score, never a zero.
* ``PilotAssessmentResponse`` -- optional item-level marks.
* ``PilotAssessmentTransition`` -- the append-only, hash-chained lifecycle
  audit; the current state is the head of this chain, so a finalized
  administration row never has to change for its lifecycle to continue.
* ``PilotAssessmentEvidence`` -- a pointer to the immutable finalized
  snapshot (by SHA-256), never a copy that could drift from it.
* ``PilotAssessmentProposal`` -- Bede's proposed next step. Always a proposal.
* ``PilotAssessmentDecision`` -- the teacher's decision, an append-only
  hash chain per learner. Teacher interpretation lives here and in the
  proposal, never in the score rows.
* ``PilotAssessmentPlan`` / ``PilotProgressMonitoringSchedule`` --
  teacher-authored, recorded only; delivery is NOT_REQUESTED.

Campus-scoped configuration (no learner content):
``PilotCampusCycle`` (the configurable instructional-review calendar) and
``PilotBenchmarkAuthorization``.

Immutability is enforced in the DATABASE as well as in route code: triggers
refuse UPDATE of a finalized administration, UPDATE of any append-only row,
and any INSERT of a score/response under a finalized administration, on
SQLite and Postgres. DELETE is deliberately not blocked: learner erasure
(the deletion lane) must be able to remove every row listed in
``LEARNER_SCOPED_TABLES``.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    DDL, Boolean, Date, DateTime, Integer, LargeBinary, String, Text,
    UniqueConstraint, event,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Campus configuration ────────────────────────────────────────────────────

class PilotCampusCycle(Base):
    """One instructional-review cycle in a campus's own calendar.

    Configurable per campus. The Valor default is four quarterly Data Days
    (``valor_q1``..``valor_q4``) roughly nine weeks apart, applied by
    ``services/assessment_calendar.py``. It is NEVER an official DIBELS
    benchmark window and nothing derives one from the other.
    """
    __tablename__ = "pilot_campus_cycles"

    campus_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    cycle_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    data_day_on: Mapped[date | None] = mapped_column(Date, nullable=True)


class PilotBenchmarkAuthorization(Base):
    """A campus's recorded statement that benchmark administration is permitted.

    References only: the licensed program, the approved form identifiers
    and the local policy. Never form content, directions, norms or cut points.
    """
    __tablename__ = "pilot_benchmark_authorizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campus_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    instrument: Mapped[str] = mapped_column(String(32), nullable=False)
    licensed_program_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    approved_forms: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    local_policy_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(80), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


# ── Learner-scoped canonical records ────────────────────────────────────────

class PilotAssessmentAdministration(Base):
    """AssessmentAdministration. Metadata plaintext (filterable), content encrypted.

    ``measure`` is the single measure administered, or ``"multiple"`` when
    the record transcribes a multi-measure report; per-measure detail lives
    in ``PilotAssessmentScore``. ``report_source``,
    ``official_benchmark_window`` and ``vendor_next_assessment_date`` are
    transcribed as given and never derived from ``instructional_cycle``.
    """
    __tablename__ = "pilot_assessment_administrations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campus_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    administrator_id: Mapped[str] = mapped_column(String(36), nullable=False)
    instrument: Mapped[str] = mapped_column(String(32), nullable=False)
    edition: Mapped[str] = mapped_column(String(32), nullable=False)
    measure: Mapped[str] = mapped_column(String(32), nullable=False)
    grade: Mapped[str] = mapped_column(String(4), nullable=False)
    form_id: Mapped[str] = mapped_column(String(64), nullable=False)
    administration_purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    instructional_cycle: Mapped[str] = mapped_column(String(32), nullable=False)
    administered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    report_source: Mapped[str] = mapped_column(String(32), nullable=False)
    official_benchmark_window: Mapped[str] = mapped_column(String(8), nullable=False)
    vendor_next_assessment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    benchmark_authorization_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    fidelity_state: Mapped[str] = mapped_column(String(32), nullable=False, default="standard")
    supersedes_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # Accommodations, notes, vendor guidance: learner content, AES-256-GCM.
    content_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    snapshot_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    finalized_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class PilotAssessmentScore(Base):
    """AssessmentScore: one measure (or the composite) of one administration.

    ``administration_status`` is ``scored``, ``not_administered_by_rule``,
    ``not_administered_other`` or ``invalid``. Only ``scored`` rows carry a
    raw score; the others carry the transcribed reason and nothing numeric.
    Score values, printed labels, printed cut points and the reason are
    encrypted in ``detail_enc``.
    """
    __tablename__ = "pilot_assessment_scores"
    __table_args__ = (UniqueConstraint("administration_id", "measure", name="uq_pilot_score_measure"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    administration_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    campus_id: Mapped[str] = mapped_column(String(36), nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    measure: Mapped[str] = mapped_column(String(32), nullable=False)
    is_composite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    administration_status: Mapped[str] = mapped_column(String(32), nullable=False)
    calculation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    detail_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class PilotAssessmentResponse(Base):
    """AssessmentResponse: item-level marks for one measure, encrypted."""
    __tablename__ = "pilot_assessment_responses"
    __table_args__ = (UniqueConstraint("administration_id", "measure", "item_index",
                                       name="uq_pilot_response_item"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    administration_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    campus_id: Mapped[str] = mapped_column(String(36), nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    measure: Mapped[str] = mapped_column(String(32), nullable=False)
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    marks_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class PilotAssessmentTransition(Base):
    """AuditEvent: append-only, hash-chained lifecycle ledger per administration.

    ``seq`` is unique per administration, so two concurrent transitions
    from the same head collide (one wins, the other is a 409) instead of
    forking the chain.
    """
    __tablename__ = "pilot_assessment_transitions"
    __table_args__ = (UniqueConstraint("administration_id", "seq", name="uq_pilot_assess_transition_seq"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    administration_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    campus_id: Mapped[str] = mapped_column(String(36), nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    from_state: Mapped[str] = mapped_column(String(40), nullable=False)
    to_state: Mapped[str] = mapped_column(String(40), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False, default="applied")
    link_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    note_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class PilotAssessmentEvidence(Base):
    """EvidenceRecord: references an immutable finalized snapshot by hash."""
    __tablename__ = "pilot_assessment_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    administration_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False, unique=True)
    campus_id: Mapped[str] = mapped_column(String(36), nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    score_ids: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list of score row ids
    summary_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class PilotAssessmentProposal(Base):
    """Bede's proposed next step and proposed review date. Never an approval.

    ``proposed_review_on`` is a suggestion; nothing is scheduled until a
    teacher confirms a date in a recorded decision.
    """
    __tablename__ = "pilot_assessment_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    administration_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    evidence_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campus_id: Mapped[str] = mapped_column(String(36), nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    proposed_review_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    proposal_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class PilotAssessmentDecision(Base):
    """TeacherDecision: append-only, hash-chained, one chain per learner."""
    __tablename__ = "pilot_assessment_decisions"
    __table_args__ = (UniqueConstraint("learner_id", "seq", name="uq_pilot_assess_decision_seq"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(36), nullable=False)
    proposal_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    administration_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campus_id: Mapped[str] = mapped_column(String(36), nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    teacher_id: Mapped[str] = mapped_column(String(36), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmed_review_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    rationale_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class PilotAssessmentPlan(Base):
    """Teacher-authored instructional plan. Recorded only; never delivered."""
    __tablename__ = "pilot_assessment_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    administration_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    decision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campus_id: Mapped[str] = mapped_column(String(36), nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    delivery_state: Mapped[str] = mapped_column(String(16), nullable=False, default="NOT_REQUESTED")
    plan_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class PilotAssessmentFollowUp(Base):
    """An append-only, teacher-authored account of offline instruction.

    References a teacher-approved plan, NOT an official reassessment.
    It cannot change official scores, placement, grants, or lesson assignments.
    """
    __tablename__ = "pilot_assessment_follow_ups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    administration_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    plan_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    decision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campus_id: Mapped[str] = mapped_column(String(36), nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    teacher_id: Mapped[str] = mapped_column(String(36), nullable=False)
    observed_on: Mapped[date] = mapped_column(Date, nullable=False)
    observation_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class PilotProgressMonitoringSchedule(Base):
    """Teacher-confirmed progress-monitoring dates for one plan."""
    __tablename__ = "pilot_progress_monitoring_schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    administration_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    plan_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campus_id: Mapped[str] = mapped_column(String(36), nullable=False)
    learner_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    measure: Mapped[str] = mapped_column(String(32), nullable=False)
    planned_dates: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list of ISO dates
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


#: Every table holding a learner's assessment content. The deletion lane
#: must cascade every one of these by (campus_id, learner_id); a test
#: asserts this list covers every model in this module with a learner_id.
LEARNER_SCOPED_TABLES = (
    PilotAssessmentAdministration.__table__,
    PilotAssessmentScore.__table__,
    PilotAssessmentResponse.__table__,
    PilotAssessmentTransition.__table__,
    PilotAssessmentEvidence.__table__,
    PilotAssessmentProposal.__table__,
    PilotAssessmentDecision.__table__,
    PilotAssessmentPlan.__table__,
    PilotAssessmentFollowUp.__table__,
    PilotProgressMonitoringSchedule.__table__,
)


# ── Database-enforced immutability ──────────────────────────────────────────

IMMUTABLE_MESSAGE = "canonical assessment record is immutable"

APPEND_ONLY_TABLES = (
    PilotAssessmentTransition.__table__,
    PilotAssessmentEvidence.__table__,
    PilotAssessmentDecision.__table__,
    PilotAssessmentPlan.__table__,
    PilotAssessmentFollowUp.__table__,
    PilotProgressMonitoringSchedule.__table__,
    # Score and response rows are replaced (delete + insert) during entry,
    # never updated in place.
    PilotAssessmentScore.__table__,
    PilotAssessmentResponse.__table__,
)


def _trigger(table, timing: str, sqlite_when: str, pg_condition: str, suffix: str) -> None:
    name = f"trg_{table.name}_{suffix}"
    event.listen(table, "after_create", DDL(
        f"CREATE TRIGGER IF NOT EXISTS {name} BEFORE {timing} ON {table.name} "
        f"FOR EACH ROW {sqlite_when} BEGIN SELECT RAISE(ABORT, '{IMMUTABLE_MESSAGE}'); END"
    ).execute_if(dialect="sqlite"))
    event.listen(table, "after_create", DDL(
        f"CREATE OR REPLACE FUNCTION {name}_fn() RETURNS trigger AS $$ BEGIN "
        f"IF {pg_condition} THEN RAISE EXCEPTION '{IMMUTABLE_MESSAGE}'; END IF; "
        f"RETURN NEW; END; $$ LANGUAGE plpgsql"
    ).execute_if(dialect="postgresql"))
    event.listen(table, "after_create", DDL(
        f"DROP TRIGGER IF EXISTS {name} ON {table.name}"
    ).execute_if(dialect="postgresql"))
    event.listen(table, "after_create", DDL(
        f"CREATE TRIGGER {name} BEFORE {timing} ON {table.name} "
        f"FOR EACH ROW EXECUTE FUNCTION {name}_fn()"
    ).execute_if(dialect="postgresql"))


for _table in APPEND_ONLY_TABLES:
    _trigger(_table, "UPDATE", "", "TRUE", "no_update")

# A finalized administration may never change; before finalization the
# transcription can be corrected in place (ordinary data entry).
_trigger(PilotAssessmentAdministration.__table__, "UPDATE",
         "WHEN OLD.finalized_at IS NOT NULL", "OLD.finalized_at IS NOT NULL", "finalized")

# Nothing may be added under a finalized administration.
for _table in (PilotAssessmentScore.__table__, PilotAssessmentResponse.__table__):
    _trigger(
        _table, "INSERT",
        "WHEN EXISTS (SELECT 1 FROM pilot_assessment_administrations a "
        "WHERE a.id = NEW.administration_id AND a.finalized_at IS NOT NULL)",
        "EXISTS (SELECT 1 FROM pilot_assessment_administrations a "
        "WHERE a.id = NEW.administration_id AND a.finalized_at IS NOT NULL)",
        "after_final",
    )
