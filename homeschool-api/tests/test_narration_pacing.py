"""
Regression tests for the dialogue -> applied-practice gap: Bede had no tool
that could open the tablet's writing/drawing canvas, and 8 of 10 subjects
had no narration/writing/drawing guidance at all, so real sessions could
run indefinitely as pure back-and-forth Socratic dialogue with no
Mater Amabilis-style narration/writing/drawing checkpoint ever occurring.
See services/ai_service.py's invite_handwriting tool and _STAGE_GUIDANCE /
_SUBJECT_CONTEXT updates.
"""
from models.schemas import GradeStage, Subject, SessionConfig
from services.ai_service import (
    _build_static_prompt,
    _STAGE_GUIDANCE,
    _SUBJECT_CONTEXT,
    TUTOR_TOOLS,
    _process_tool_use,
)


def test_invite_handwriting_tool_exists_with_a_prompt_field():
    tool = next((t for t in TUTOR_TOOLS if t["name"] == "invite_handwriting"), None)
    assert tool is not None, "invite_handwriting tool is missing from TUTOR_TOOLS"
    assert tool["input_schema"]["required"] == ["prompt"]


def test_process_tool_use_formats_invite_handwriting():
    result = _process_tool_use("invite_handwriting", {"prompt": "Sketch what you just described"})
    assert "Sketch what you just described" in result
    assert "Write or Draw" in result


def test_invite_handwriting_tool_knows_about_the_notebook_upload_option():
    """Regression for the inq (https://inq.shop) integration — a family
    that already writes narration by hand with a smart pen should have Bede
    mention that option occasionally, phrased as a free choice, not a
    requirement or an every-time ad. See services/document_extraction.py
    and the frontend's narration-upload button next to the drawing canvas."""
    tool = next(t for t in TUTOR_TOOLS if t["name"] == "invite_handwriting")
    description = tool["description"]
    assert "upload" in description.lower()
    assert "smart pen" in description.lower()
    assert "occasionally" in description.lower() or "not every single time" in description.lower()
    assert "never as a requirement" in description.lower()


def test_celebrate_discovery_specific_insight_requires_second_person_phrasing():
    """Regression for a real live transcript: _process_tool_use appends
    specific_insight after the literal words "I noticed you saw that ",
    but the model wrote it in third person using the child's own name
    ("...that Norah recognized our shared responsibility...") right after
    addressing her as "you" earlier in the same card — reading as Bede
    narrating about the child to someone else rather than speaking to her.
    Nothing in the schema previously said what grammatical person continues
    that sentence."""
    tool = next(t for t in TUTOR_TOOLS if t["name"] == "celebrate_discovery")
    description = tool["input_schema"]["properties"]["specific_insight"]["description"]
    assert "second person" in description.lower()
    assert "never" in description.lower() and "third person" in description.lower()
    assert "child's own name" in description.lower() or "child's name" in description.lower()


def test_foundations_stage_keeps_narration_oral_only():
    guidance = _STAGE_GUIDANCE[GradeStage.foundations]
    assert "oral only" in guidance
    assert "Never require or invite WRITTEN narration" in guidance


def test_older_stages_reference_written_narration_via_invite_handwriting():
    for stage in (GradeStage.core_mastery, GradeStage.independent):
        guidance = _STAGE_GUIDANCE[stage]
        assert "invite_handwriting" in guidance
        assert "written narration" in guidance.lower()


def test_every_subject_context_mentions_narration_or_handwriting():
    # Before this fix, 8 of 10 subjects had zero narration/writing/drawing
    # language, leaving dialogue with no structural path to applied practice.
    for subject, context in _SUBJECT_CONTEXT.items():
        lowered = context.lower()
        assert "narrat" in lowered or "invite_handwriting" in lowered, (
            f"{subject.value} subject context has no narration/handwriting guidance"
        )


def test_nature_study_specifically_invites_a_nature_notebook_sketch():
    context = _SUBJECT_CONTEXT[Subject.nature_study]
    assert "invite_handwriting" in context
    assert "nature notebook" in context
    assert "Never correct the drawing" in context


def test_conversation_never_stalls_on_a_questionless_tool_card():
    """Regression for a real transcript: Bede's turn ended on a
    celebrate_discovery card (no question field in its own schema) with no
    follow-up, and the session just stopped — nothing to respond to."""
    prompt = _build_static_prompt(
        SessionConfig(student_name="Guest", grade="4", grade_stage=GradeStage.core_mastery)
    )
    assert "End EVERY turn with exactly one question" in prompt
    assert "even when you also use a tool" in prompt
    assert "celebrate_discovery" in prompt and "has no question field" in prompt
    assert "Never let one of these be the very last thing in a turn" in prompt


def test_static_prompt_teaches_the_idle_continue_sentinel():
    """Regression for a real transcript: Bede's own turn always ends with a
    question now (see the test above), but if the CHILD goes quiet after
    that, nothing was previously teaching Bede how to pick the thread back
    up — the demo frontend now sends a silent "[CONTINUE]" sentinel after
    an idle period (see demo/src/App.tsx), and this rule is what makes
    Bede respond to it usefully instead of literally discussing the token."""
    prompt = _build_static_prompt(
        SessionConfig(student_name="Guest", grade="4", grade_stage=GradeStage.core_mastery)
    )
    assert '"[CONTINUE]"' in prompt
    assert "never mention the pause" in prompt
    assert "never repeat your last question verbatim" in prompt
