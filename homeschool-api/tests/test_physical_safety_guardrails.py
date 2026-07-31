"""
Tests for the physical-safety guardrails — see services/ai_service.py's
_physical_safety_guardrails and _build_static_prompt, and docs/SECURITY.md's
Closed gaps for the audit that surfaced this: Bede's constitution and
moderation categories cover a child's own distress/danger, but nothing
previously governed Bede's OWN suggestions in ordinary hands-on tutoring
(Nature Study, Science, Mathematics) being safe by design.
"""
from models.schemas import GradeStage, SessionConfig
from services.ai_service import _build_static_prompt, _physical_safety_guardrails


def _config(grade: str = "3", grade_stage: GradeStage = GradeStage.core_mastery) -> SessionConfig:
    return SessionConfig(student_name="Sam", grade=grade, grade_stage=grade_stage)


def test_lists_the_categories_of_risk_to_avoid():
    text = _physical_safety_guardrails()
    for risk in ("heights", "fire or heat", "sharp or breakable", "electricity"):
        assert risk in text


def test_redirects_a_childs_own_object_or_environment_risk_rather_than_complying():
    text = _physical_safety_guardrails()
    assert "do not go along with it" in text
    assert "redirect warmly to a safe alternative" in text


def test_flags_when_adult_supervision_is_genuinely_needed():
    text = _physical_safety_guardrails()
    assert "ask a grown-up to help" in text


def test_lists_self_directed_bodily_risk_categories_not_just_object_risk():
    # A follow-up design-verification gap: the original list only named
    # risk to objects/environment, nothing that could catch a self-harm
    # impulse framed as a lesson "experiment" on the child's own body.
    text = _physical_safety_guardrails()
    for risk in ("holding their breath", "restricting food or water", "testing how much pain they can take"):
        assert risk in text


def test_self_directed_bodily_risk_routes_to_the_safeguarding_stop_not_a_swap():
    # The other follow-up gap: a request targeting the child's own body
    # must never just get a "safer alternative" swap-and-continue — it has
    # to hit the same full stop-and-escalate as the safeguarding rule.
    text = _physical_safety_guardrails()
    assert "never a \"safer alternative\" situation" in text
    assert "Please find a parent or trusted adult right now" in text
    assert "stop the lesson" in text


def test_explicit_tiebreaker_favors_stopping_when_ambiguous():
    text = _physical_safety_guardrails()
    assert "When in doubt" in text
    assert "treat it as (b)" in text


def test_universal_across_grades_and_stages():
    # No config parameter at all — unlike _ai_literacy_guardrails, this
    # doesn't vary by grade/stage, so the function takes none.
    text_a = _physical_safety_guardrails()
    text_b = _physical_safety_guardrails()
    assert text_a == text_b


def test_static_prompt_includes_the_physical_safety_guardrails_section():
    prompt = _build_static_prompt(_config())
    assert "<physical_safety_guardrails>" in prompt
    assert "</physical_safety_guardrails>" in prompt
    assert "heights" in prompt


def test_static_prompt_includes_it_for_every_grade_stage():
    for grade, stage in (("1", GradeStage.foundations), ("4", GradeStage.core_mastery), ("8", GradeStage.independent)):
        prompt = _build_static_prompt(_config(grade, stage))
        assert "<physical_safety_guardrails>" in prompt
