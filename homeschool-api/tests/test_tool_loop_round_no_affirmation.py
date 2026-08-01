"""
Regression guard for a reported bug close kin to the one
test_continue_sentinel_no_affirmation.py already guards, but a different
trigger: "Bede also says 'Great thinking...' when there is no response to
evaluate in between pauses in response."

Rule 11 (see that other test file) only covers the [CONTINUE] sentinel path
— the silence timer firing after the CHILD goes quiet. It says nothing
about the bounded tool_result loop (_MAX_TOOL_LOOP_ROUNDS,
stream_tutor_response), where show_visual_aid/assess_narration can trigger
a second or third model round-trip WITHIN one turn, each one continuing
Bede's own reply after a tool_result — not after anything new from the
child. Nothing previously told the model that gap is a pause of its OWN
making, not the child's; a round-2+ continuation opening as though praising
a fresh answer ("Great thinking!") would misattribute credit to a response
that never happened, the exact same failure shape rule 11 was written to
prevent for the other trigger.

This only guards the static prompt text itself against never having this
guardrail, or a silent revert of it — it doesn't verify live model behavior
(that needs a real session, not this suite; see the sibling test file's own
identical caveat).
"""
from models.schemas import GradeStage, SessionConfig
from services.ai_service import _build_static_prompt


def _config() -> SessionConfig:
    return SessionConfig(student_name="Norah", grade="4", grade_stage=GradeStage.core_mastery)


def test_rule_fourteen_forbids_reacting_to_a_tool_result_as_a_new_answer():
    prompt = _build_static_prompt(_config())
    assert "never a new greeting" in prompt
    assert "never praise or react as though they just answered something" in prompt


def test_rule_fourteen_names_the_tool_result_as_its_own_pause_not_the_childs():
    """The instruction has to actually explain WHY — that this is Bede's own
    tool call resolving, not the child speaking again — or a model has no
    reason to treat it differently from an ordinary reply. A bare "don't do
    this" without the "because" a rule like #11 already models is weaker
    guidance for the same reasoning that made #11 need the explicit
    said-NOTHING framing in the first place."""
    prompt = _build_static_prompt(_config())
    assert "OUTCOME of your OWN tool call" in prompt
    assert "they have not spoken again since this turn began" in prompt


def test_rule_fourteen_cross_references_rule_eleven_rather_than_duplicating_it():
    """Rule 11 stays scoped to [CONTINUE] and untouched — confirmed by the
    sibling test file's own two assertions still passing unchanged. Rule 14
    should read as the same principle applied to a second trigger, not a
    competing or overlapping rule a future edit might drift out of sync
    with."""
    prompt = _build_static_prompt(_config())
    assert "Rule 11" in prompt
    # Rule 11 itself must still be present and intact alongside the new rule.
    assert "said NOTHING" in prompt
    assert "never open as though they just answered" in prompt
