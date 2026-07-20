"""
Regression tests for a parent-requested pacing change: Bede's Socratic
follow-ups were chaining indefinitely deep on a single idea with no
built-in cue to simplify or move on, and a single question could bundle
more than one thing at once — both easy to lose a young child in. See
services/ai_service.py's persona paragraph (general cap: two consecutive
follow-ups on the same idea, then simplify/hint/move on; follow one thread
of a multi-part answer, not all of them) and _STAGE_GUIDANCE[foundations]
(K-2 gets the stricter version: one simple, single-idea question at a
time, and usually just one follow-up round before simplifying).
"""
from models.schemas import GradeStage, SessionConfig
from services.ai_service import _build_static_prompt, _STAGE_GUIDANCE


def test_static_prompt_caps_consecutive_follow_ups_on_the_same_idea():
    prompt = _build_static_prompt(
        SessionConfig(student_name="Guest", grade="4", grade_stage=GradeStage.core_mastery)
    )
    assert "two consecutive follow-up questions probing the very same idea as your outer limit" in prompt
    assert "follow just one of them" in prompt


def test_foundations_stage_keeps_each_question_to_one_simple_idea():
    guidance = _STAGE_GUIDANCE[GradeStage.foundations]
    assert "one simple, concrete idea" in guidance
    assert "never stack two things into a single" in guidance


def test_foundations_stage_limits_probing_depth_more_than_older_stages():
    foundations = _STAGE_GUIDANCE[GradeStage.foundations]
    assert "one follow-up question on a given idea is usually enough" in foundations
    assert "pick the one thread from their answer" in foundations

    # The stricter one-round limit is specific to K-2 — older stages rely on
    # the general two-round cap in the shared persona paragraph instead of
    # repeating a stage-specific number.
    for stage in (GradeStage.core_mastery, GradeStage.independent):
        guidance = _STAGE_GUIDANCE[stage]
        assert "one follow-up question on a given idea is usually enough" not in guidance
