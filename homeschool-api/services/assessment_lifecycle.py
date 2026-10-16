"""Canonical assessment lifecycle: one pure transition function.

No I/O, no clock, no database, following ``services/policy_engine.py``'s
precedent, so every legal and illegal move is testable by stating it
(``tests/test_canonical_assessment_lifecycle.py`` walks the whole
state x action product).

The main line::

    DRAFT -> READY_FOR_ADMINISTRATION -> IN_PROGRESS
          -> COMPLETED_PENDING_REVIEW -> FINALIZED -> EVIDENCE_AVAILABLE
          -> TEACHER_DECISION_PENDING -> TEACHER_DECISION_RECORDED
          -> INSTRUCTIONAL_PLAN_READY -> PROGRESS_MONITORING_SCHEDULED

plus four side states: INTERRUPTED, INVALID_ADMINISTRATION,
VOIDED_BY_TEACHER and SUPERSEDED_WITH_AUDIT_LINK.

Rules this module is the single place for:

* An interrupted or invalid administration can never reach FINALIZED
  without a teacher resolution. ``finalize`` is legal only from
  COMPLETED_PENDING_REVIEW, and the only ways back to that line from
  INTERRUPTED or INVALID_ADMINISTRATION (``resume``, ``resolve_invalid``)
  require a non-empty ``resolution``.
* FINALIZED content is immutable. Every state from FINALIZED onward is
  "post-finalization"; the only correction is ``supersede``, which needs
  a link to the replacing administration so the audit trail is joined.
* Voiding needs a reason and is refused once finalized (supersede instead).
* VOIDED_BY_TEACHER and SUPERSEDED_WITH_AUDIT_LINK are terminal.

Every action here is a TEACHER action. Nothing advances a lifecycle on a
timer or as a side effect of a recommendation; see the router.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class State(str, Enum):
    DRAFT = "DRAFT"
    READY_FOR_ADMINISTRATION = "READY_FOR_ADMINISTRATION"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED_PENDING_REVIEW = "COMPLETED_PENDING_REVIEW"
    FINALIZED = "FINALIZED"
    EVIDENCE_AVAILABLE = "EVIDENCE_AVAILABLE"
    TEACHER_DECISION_PENDING = "TEACHER_DECISION_PENDING"
    TEACHER_DECISION_RECORDED = "TEACHER_DECISION_RECORDED"
    INSTRUCTIONAL_PLAN_READY = "INSTRUCTIONAL_PLAN_READY"
    PROGRESS_MONITORING_SCHEDULED = "PROGRESS_MONITORING_SCHEDULED"
    INTERRUPTED = "INTERRUPTED"
    INVALID_ADMINISTRATION = "INVALID_ADMINISTRATION"
    VOIDED_BY_TEACHER = "VOIDED_BY_TEACHER"
    SUPERSEDED_WITH_AUDIT_LINK = "SUPERSEDED_WITH_AUDIT_LINK"


class Action(str, Enum):
    MARK_READY = "mark_ready"
    START = "start"
    INTERRUPT = "interrupt"
    RESUME = "resume"
    INVALIDATE = "invalidate"
    RESOLVE_INVALID = "resolve_invalid"
    SUBMIT = "submit"
    FINALIZE = "finalize"
    RECORD_EVIDENCE = "record_evidence"
    REQUEST_REVIEW = "request_review"
    RECORD_DECISION = "record_decision"
    RECORD_PLAN = "record_plan"
    SCHEDULE_PROGRESS_MONITORING = "schedule_progress_monitoring"
    VOID = "void"
    SUPERSEDE = "supersede"


#: States reached only after finalization. Content is frozen in all of them.
POST_FINALIZATION = frozenset({
    State.FINALIZED, State.EVIDENCE_AVAILABLE, State.TEACHER_DECISION_PENDING,
    State.TEACHER_DECISION_RECORDED, State.INSTRUCTIONAL_PLAN_READY,
    State.PROGRESS_MONITORING_SCHEDULED,
})
TERMINAL = frozenset({State.VOIDED_BY_TEACHER, State.SUPERSEDED_WITH_AUDIT_LINK})
#: States in which response marks and scores may still be entered.
SCORE_ENTRY = frozenset({State.IN_PROGRESS, State.COMPLETED_PENDING_REVIEW})

_VOIDABLE = frozenset({
    State.DRAFT, State.READY_FOR_ADMINISTRATION, State.IN_PROGRESS,
    State.INTERRUPTED, State.INVALID_ADMINISTRATION, State.COMPLETED_PENDING_REVIEW,
})

# (from, action) -> to. Anything absent is illegal.
TRANSITIONS: dict[tuple[State, Action], State] = {
    (State.DRAFT, Action.MARK_READY): State.READY_FOR_ADMINISTRATION,
    (State.READY_FOR_ADMINISTRATION, Action.START): State.IN_PROGRESS,
    (State.IN_PROGRESS, Action.INTERRUPT): State.INTERRUPTED,
    (State.INTERRUPTED, Action.RESUME): State.IN_PROGRESS,
    (State.IN_PROGRESS, Action.INVALIDATE): State.INVALID_ADMINISTRATION,
    (State.COMPLETED_PENDING_REVIEW, Action.INVALIDATE): State.INVALID_ADMINISTRATION,
    (State.INVALID_ADMINISTRATION, Action.RESOLVE_INVALID): State.COMPLETED_PENDING_REVIEW,
    (State.IN_PROGRESS, Action.SUBMIT): State.COMPLETED_PENDING_REVIEW,
    (State.COMPLETED_PENDING_REVIEW, Action.FINALIZE): State.FINALIZED,
    (State.FINALIZED, Action.RECORD_EVIDENCE): State.EVIDENCE_AVAILABLE,
    (State.EVIDENCE_AVAILABLE, Action.REQUEST_REVIEW): State.TEACHER_DECISION_PENDING,
    # A rejected proposal may be followed by a fresh one; the router only
    # permits this when the last recorded decision was a rejection.
    (State.TEACHER_DECISION_RECORDED, Action.REQUEST_REVIEW): State.TEACHER_DECISION_PENDING,
    (State.TEACHER_DECISION_PENDING, Action.RECORD_DECISION): State.TEACHER_DECISION_RECORDED,
    (State.TEACHER_DECISION_RECORDED, Action.RECORD_PLAN): State.INSTRUCTIONAL_PLAN_READY,
    (State.INSTRUCTIONAL_PLAN_READY, Action.SCHEDULE_PROGRESS_MONITORING):
        State.PROGRESS_MONITORING_SCHEDULED,
    **{(s, Action.VOID): State.VOIDED_BY_TEACHER for s in _VOIDABLE},
    **{(s, Action.SUPERSEDE): State.SUPERSEDED_WITH_AUDIT_LINK for s in POST_FINALIZATION},
}

#: Actions whose transition must carry a written teacher resolution/reason.
REQUIRES_RESOLUTION = frozenset({
    Action.RESUME, Action.RESOLVE_INVALID, Action.INVALIDATE, Action.VOID, Action.SUPERSEDE,
})
#: Actions whose transition must carry a link to another record.
REQUIRES_LINK = frozenset({Action.SUPERSEDE})


class IllegalTransition(ValueError):
    """The requested move is not part of the lifecycle."""


@dataclass(frozen=True)
class Transition:
    from_state: State
    action: Action
    to_state: State


def next_state(current: State | str, action: Action | str, *,
               resolution: str | None = None,
               link_id: str | None = None) -> Transition:
    """Return the transition, or raise ``IllegalTransition`` naming why."""
    try:
        cur = State(current)
        act = Action(action)
    except ValueError as exc:
        raise IllegalTransition(f"unknown state or action: {exc}") from None
    if cur in TERMINAL:
        raise IllegalTransition(f"{cur.value} is terminal")
    target = TRANSITIONS.get((cur, act))
    if target is None:
        if act is Action.VOID and cur in POST_FINALIZATION:
            raise IllegalTransition("a finalized administration is corrected by supersede, not void")
        raise IllegalTransition(f"{act.value} is not allowed from {cur.value}")
    if act in REQUIRES_RESOLUTION and not (resolution or "").strip():
        raise IllegalTransition(f"{act.value} requires a written teacher resolution")
    if act in REQUIRES_LINK and not (link_id or "").strip():
        raise IllegalTransition(f"{act.value} requires an audit link to the replacing record")
    return Transition(cur, act, target)
