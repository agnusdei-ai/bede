"""R1 pure policy negative tests; no pilot authorization enabled by these tests."""
import pytest

from services.r1_session_policy import (
    TransitionDenied, permitted_ladder_step, transition, PERMITTED_INTERACTIONS,
)


@pytest.mark.parametrize("domain,state,event", [
    ("approval", "DRAFT", "approve"),
    ("approval", "REVOKED", "approve"),
    ("assignment", "ASSIGNED", "open"),
    ("assignment", "REVOKED", "open"),
    ("assignment", "COMPLETED", "authorize_launch"),
    ("session", "CREATED", "complete"),
    ("session", "PAUSED", "complete"),
    ("session", "REVOKED", "resume"),
    ("session", "COMPLETED", "resume"),
    ("session", "APPROVAL_VERSION_SUPERSEDED", "open"),
    ("session", "ACTIVE", "unrestricted_chat"),
    ("unknown", "ACTIVE", "resume"),
])
def test_forbidden_transitions(domain, state, event):
    with pytest.raises(TransitionDenied):
        transition(domain, state, event)


def test_explicit_teacher_launch_before_open():
    assert transition("approval", "DRAFT", "submit") == "PENDING_TEACHER_REVIEW"
    assert transition("approval", "PENDING_TEACHER_REVIEW", "approve") == "APPROVED"
    assert transition("assignment", "ASSIGNED", "authorize_launch") == "LAUNCH_AUTHORIZED"
    assert transition("assignment", "LAUNCH_AUTHORIZED", "open") == "ACTIVE"


def test_session_pause_resume_and_revocation_terminal():
    assert transition("session", "ACTIVE", "pause") == "PAUSED"
    assert transition("session", "PAUSED", "resume") == "ACTIVE"
    assert transition("session", "ACTIVE", "revoke") == "REVOKED"
    with pytest.raises(TransitionDenied):
        transition("session", "REVOKED", "resume")


def test_ladder_is_bounded():
    assert permitted_ladder_step(None, "OBSERVE", PERMITTED_INTERACTIONS)
    assert not permitted_ladder_step(None, "SUMMARIZE", PERMITTED_INTERACTIONS)
    assert permitted_ladder_step("OBSERVE", "RECALL", PERMITTED_INTERACTIONS)
    assert not permitted_ladder_step("OBSERVE", "COMPARE", PERMITTED_INTERACTIONS)
    assert not permitted_ladder_step("RECALL", "GENERAL_CHAT", PERMITTED_INTERACTIONS)
    assert not permitted_ladder_step("RECALL", "NARRATE", frozenset({"OBSERVE"}))
