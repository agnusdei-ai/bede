"""
Regression guard for a real reported bug: after the frontend's silence
timer sends the [CONTINUE] sentinel (SocraticChat.tsx's sendContinue /
demo/src/App.tsx's equivalent, both after real, extended inactivity — see
ai_service.py's rule 11), Bede's reply opened as though the child had just
answered ("That's a thoughtful start, Norah...") even though nothing was
ever sent. The old rule 11 only forbade mentioning the pause — it never
said the opposite failure mode (opening as if reacting to a nonexistent
answer) was also off-limits. This only guards the static prompt text
itself against a silent revert of the added guardrail — it doesn't verify
live model behavior (that needs a real session, not this suite).
"""
from models.schemas import GradeStage, SessionConfig
from services.ai_service import _build_static_prompt


def _config() -> SessionConfig:
    return SessionConfig(student_name="Norah", grade="4", grade_stage=GradeStage.core_mastery)


def test_rule_eleven_forbids_reacting_as_though_the_child_answered():
    prompt = _build_static_prompt(_config())
    assert "said NOTHING" in prompt
    assert "never open as though they just answered" in prompt
    assert "not responding to them" in prompt


def test_rule_eleven_still_forbids_mentioning_the_pause():
    """The original guardrail must survive alongside the new one."""
    prompt = _build_static_prompt(_config())
    assert 'never mention' in prompt
    assert 'are you still there?' in prompt
