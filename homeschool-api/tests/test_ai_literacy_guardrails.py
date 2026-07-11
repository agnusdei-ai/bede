"""
Tests for the Catholic AI-literacy guardrails — grounded in Pope Leo XIV's
Magnifica Humanitas (2026) and Pope Francis's 2024 World Day of Peace
message / 2025 Davos remarks. See services/ai_service.py's
_ai_literacy_guardrails and _build_static_prompt.

This app only models grades K-8 (no grade 9-12 "high school" band), so
grade 8 — the oldest grade taught — stands in as the bridge toward the
"ages 14+" hands-on AI-literacy cutoff described in the guidelines that
prompted this feature, rather than this app inventing high-school grade
support it was never asked to add.
"""
from models.schemas import GradeStage, SessionConfig
from services.ai_service import _ai_literacy_guardrails, _build_static_prompt


def _config(grade: str, grade_stage: GradeStage) -> SessionConfig:
    return SessionConfig(student_name="Sam", grade=grade, grade_stage=grade_stage)


def test_foundations_stage_is_strictly_analog():
    text = _ai_literacy_guardrails(_config("1", GradeStage.foundations))
    assert "strictly analog" in text
    assert "decline warmly" in text
    assert "THE ADAPTIVE CONTINUOUS LEARNING LOOP" not in text


def test_core_mastery_stage_is_strictly_analog():
    text = _ai_literacy_guardrails(_config("4", GradeStage.core_mastery))
    assert "strictly analog" in text
    assert "THE ADAPTIVE CONTINUOUS LEARNING LOOP" not in text


def test_grades_6_and_7_get_conceptual_only_guidance_no_loop():
    for grade in ("6", "7"):
        text = _ai_literacy_guardrails(_config(grade, GradeStage.independent))
        assert "conceptually" in text
        assert "no generative AI" in text.lower() or "still no generative ai" in text.lower()
        assert "THE ADAPTIVE CONTINUOUS LEARNING LOOP" not in text, f"grade {grade} should not get the loop"


def test_grade_8_gets_the_adaptive_learning_loop():
    text = _ai_literacy_guardrails(_config("8", GradeStage.independent))
    assert "THE ADAPTIVE CONTINUOUS LEARNING LOOP" in text
    assert "1. Analog Grounding" in text
    assert "2. Technological Exposure" in text
    assert "3. Critical Narration" in text
    assert "4. Calibration" in text
    # Never actually invokes a real external AI call — this is a simulated
    # Socratic exercise Bede narrates, not a live tool integration.
    assert "you are not actually invoking any outside AI tool" in text


def test_grade_8_loop_never_frames_ai_as_doing_the_students_work():
    text = _ai_literacy_guardrails(_config("8", GradeStage.independent))
    assert "never as using AI to do Sam's actual work for them" in text


def test_catholic_grounding_present_at_every_stage():
    for grade, stage in (("1", GradeStage.foundations), ("4", GradeStage.core_mastery), ("8", GradeStage.independent)):
        text = _ai_literacy_guardrails(_config(grade, stage))
        assert "never neutral" in text
        assert "digital colonialism" in text
        assert "human dignity" in text


def test_never_a_substitute_for_human_connection_at_every_stage():
    for grade, stage in (("1", GradeStage.foundations), ("4", GradeStage.core_mastery), ("8", GradeStage.independent)):
        text = _ai_literacy_guardrails(_config(grade, stage))
        assert "not a companion replacing family" in text


def test_static_prompt_includes_the_ai_literacy_guardrails_section():
    prompt = _build_static_prompt(_config("8", GradeStage.independent))
    assert "<ai_literacy_guardrails>" in prompt
    assert "</ai_literacy_guardrails>" in prompt
    assert "THE ADAPTIVE CONTINUOUS LEARNING LOOP" in prompt
