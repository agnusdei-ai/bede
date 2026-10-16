"""Exhaustive tests of the pure canonical-assessment state machine.

Every (state, action) pair is checked against an independently written
expectation table, so a transition added to the module without being added
here (or vice versa) fails.
"""
import itertools

import pytest

from services.assessment_lifecycle import (
    POST_FINALIZATION, TERMINAL, Action, IllegalTransition, State, next_state,
)

S, A = State, Action

# Independently restated legal moves (deliberately not imported).
EXPECTED = {
    (S.DRAFT, A.MARK_READY): S.READY_FOR_ADMINISTRATION,
    (S.READY_FOR_ADMINISTRATION, A.START): S.IN_PROGRESS,
    (S.IN_PROGRESS, A.INTERRUPT): S.INTERRUPTED,
    (S.INTERRUPTED, A.RESUME): S.IN_PROGRESS,
    (S.IN_PROGRESS, A.INVALIDATE): S.INVALID_ADMINISTRATION,
    (S.COMPLETED_PENDING_REVIEW, A.INVALIDATE): S.INVALID_ADMINISTRATION,
    (S.INVALID_ADMINISTRATION, A.RESOLVE_INVALID): S.COMPLETED_PENDING_REVIEW,
    (S.IN_PROGRESS, A.SUBMIT): S.COMPLETED_PENDING_REVIEW,
    (S.COMPLETED_PENDING_REVIEW, A.FINALIZE): S.FINALIZED,
    (S.FINALIZED, A.RECORD_EVIDENCE): S.EVIDENCE_AVAILABLE,
    (S.EVIDENCE_AVAILABLE, A.REQUEST_REVIEW): S.TEACHER_DECISION_PENDING,
    (S.TEACHER_DECISION_RECORDED, A.REQUEST_REVIEW): S.TEACHER_DECISION_PENDING,
    (S.TEACHER_DECISION_PENDING, A.RECORD_DECISION): S.TEACHER_DECISION_RECORDED,
    (S.TEACHER_DECISION_RECORDED, A.RECORD_PLAN): S.INSTRUCTIONAL_PLAN_READY,
    (S.INSTRUCTIONAL_PLAN_READY, A.SCHEDULE_PROGRESS_MONITORING): S.PROGRESS_MONITORING_SCHEDULED,
}
for s in (S.DRAFT, S.READY_FOR_ADMINISTRATION, S.IN_PROGRESS, S.INTERRUPTED,
          S.INVALID_ADMINISTRATION, S.COMPLETED_PENDING_REVIEW):
    EXPECTED[(s, A.VOID)] = S.VOIDED_BY_TEACHER
for s in (S.FINALIZED, S.EVIDENCE_AVAILABLE, S.TEACHER_DECISION_PENDING,
          S.TEACHER_DECISION_RECORDED, S.INSTRUCTIONAL_PLAN_READY,
          S.PROGRESS_MONITORING_SCHEDULED):
    EXPECTED[(s, A.SUPERSEDE)] = S.SUPERSEDED_WITH_AUDIT_LINK


@pytest.mark.parametrize("state,action", list(itertools.product(State, Action)))
def test_every_state_action_pair(state, action):
    kwargs = {"resolution": "teacher note", "link_id": "x"}
    if (state, action) in EXPECTED:
        t = next_state(state, action, **kwargs)
        assert t.to_state is EXPECTED[(state, action)]
    else:
        with pytest.raises(IllegalTransition):
            next_state(state, action, **kwargs)


def test_illegal_jumps_named_by_the_brief():
    for frm, act in [
        (S.DRAFT, A.FINALIZE),                    # skip administration
        (S.IN_PROGRESS, A.FINALIZE),              # skip review
        (S.INTERRUPTED, A.FINALIZE),              # interrupted cannot finalize
        (S.INVALID_ADMINISTRATION, A.FINALIZE),   # invalid cannot finalize
        (S.INTERRUPTED, A.SUBMIT),
        (S.FINALIZED, A.REQUEST_REVIEW),          # evidence first
        (S.EVIDENCE_AVAILABLE, A.RECORD_DECISION),  # no decision without proposal
        (S.TEACHER_DECISION_PENDING, A.RECORD_PLAN),
        (S.TEACHER_DECISION_RECORDED, A.SCHEDULE_PROGRESS_MONITORING),
        (S.FINALIZED, A.START),                   # finalized never reopens
        (S.FINALIZED, A.VOID),                    # supersede, not void
        (S.COMPLETED_PENDING_REVIEW, A.SUPERSEDE),  # nothing final to supersede
    ]:
        with pytest.raises(IllegalTransition):
            next_state(frm, act, resolution="r", link_id="l")


def test_interrupted_and_invalid_need_a_teacher_resolution():
    with pytest.raises(IllegalTransition, match="resolution"):
        next_state(S.INTERRUPTED, A.RESUME)
    with pytest.raises(IllegalTransition, match="resolution"):
        next_state(S.INVALID_ADMINISTRATION, A.RESOLVE_INVALID, resolution="   ")
    assert next_state(S.INTERRUPTED, A.RESUME, resolution="resumed same form").to_state is S.IN_PROGRESS


def test_void_and_supersede_need_reason_and_supersede_needs_link():
    with pytest.raises(IllegalTransition):
        next_state(S.DRAFT, A.VOID)
    with pytest.raises(IllegalTransition, match="link"):
        next_state(S.FINALIZED, A.SUPERSEDE, resolution="transcription error")


def test_terminal_states_accept_nothing():
    for state, action in itertools.product(TERMINAL, Action):
        with pytest.raises(IllegalTransition, match="terminal"):
            next_state(state, action, resolution="r", link_id="l")


def test_post_finalization_never_returns_to_score_entry():
    from services.assessment_lifecycle import SCORE_ENTRY, TRANSITIONS
    for (frm, _), to in TRANSITIONS.items():
        if frm in POST_FINALIZATION:
            assert to not in SCORE_ENTRY and to not in (S.DRAFT, S.READY_FOR_ADMINISTRATION)


def test_unknown_values_are_illegal_not_errors():
    with pytest.raises(IllegalTransition):
        next_state("NOT_A_STATE", "start")
    with pytest.raises(IllegalTransition):
        next_state(S.DRAFT, "teleport")
