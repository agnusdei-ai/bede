"""
Regression guard for a reported requirement, close kin to the two sibling
guards already in this suite (test_continue_sentinel_no_affirmation.py for
the [CONTINUE] sentinel, test_tool_loop_round_no_affirmation.py for a
tool_result round-trip pause) but a THIRD trigger neither of them covers:
a turn that is not empty — a real message reached the model — but still
carries no genuine answer, insight, or comment from the child. The
clearest real case is voice input garbled by background noise: the
microphone picks up a stray sound or a filler ("um"), useHybridVoiceInput.ts
still delivers a non-empty transcript (a fully empty one is already caught
client-side and never reaches Bede as a turn — see that hook's own
MIN_HOLD_MS_FOR_NO_SPEECH_FEEDBACK path), and nothing previously told the
model this was any different from a real answer worth praising.

Rules 11 and 14 both establish the same underlying principle — never praise
or affirm as though the child just answered when there's nothing to react
to — for two triggers where no message (or no NEW message) arrived at all.
Rule 15 extends that principle to a third trigger where a message did
arrive but carries no real content, and also states the broader calibration
this codebase was asked for: praise should be earned per turn, not automatic
every turn, without ever excusing coldness or withheld ordinary warmth.

This only guards the static prompt text itself against never having this
guardrail, or a silent revert of it — it doesn't verify live model behavior
(that needs a real session, not this suite; see the sibling test files'
own identical caveat).
"""
from models.schemas import GradeStage, SessionConfig
from services.ai_service import _build_static_prompt


def _config() -> SessionConfig:
    return SessionConfig(student_name="Norah", grade="4", grade_stage=GradeStage.core_mastery)


def test_rule_fifteen_forbids_praising_content_free_input():
    prompt = _build_static_prompt(_config())
    assert "Praise only what's actually there" in prompt
    assert "still nothing there to react to" in prompt


def test_rule_fifteen_names_the_background_noise_case_explicitly():
    """The rule has to name the actual reported failure — a transcript that
    isn't empty but isn't real content either — or a model has no reason to
    treat "um" or a stray noise-transcription any differently from a real
    answer worth celebrating."""
    prompt = _build_static_prompt(_config())
    assert "microphone picked up and mistook for speech" in prompt
    assert '"um" or "hmm"' in prompt


def test_rule_fifteen_cross_references_rule_eleven_rather_than_duplicating_it():
    """Same convention rule 14 already established: extend the principle by
    naming rule 11 explicitly, don't restate it as a competing rule that
    could drift out of sync."""
    prompt = _build_static_prompt(_config())
    assert "Rule 11" in prompt
    # Rule 11 itself must still be present and intact alongside the new rule.
    assert "said NOTHING" in prompt
    assert "never open as though they just answered" in prompt


def test_rule_fifteen_also_states_the_broader_no_reflex_praise_principle():
    """The user's own requirement had two halves: never praise a non-answer,
    AND more generally don't overtly praise on everything. Both must be
    present, not just the narrower trigger-specific half."""
    prompt = _build_static_prompt(_config())
    assert "do not praise by reflex on every single turn" in prompt
    assert "proportionate to what they did" in prompt


def test_rule_fifteen_does_not_license_coldness():
    """The requirement was explicit: fair and justified, without being
    strict, punitive, or mean. The rule must say so, not just cut praise."""
    prompt = _build_static_prompt(_config())
    assert "never license to go cold or withhold" in prompt
