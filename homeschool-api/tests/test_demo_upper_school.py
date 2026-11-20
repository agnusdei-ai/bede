"""Exact-grade demo sessions; no high-school curriculum or diagnostic promotion."""
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from core import demo_code_session
from models.schemas import (
    DEMO_UPPER_GRADES, VALID_DEMO_GRADES, VALID_GRADES, DemoCodeRequest,
    DemoParentConfigRequest, GradeStage, Subject, grade_to_stage,
)
from routers.auth import create_demo_code, set_demo_parent_config
from routers.diagnostic import _require_diagnostic_quota
from routers.tutor import _demo_session_config
from services import ai_service
from services.demo_upper_school import GRADE_FOCI, upper_school_guidance

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


@pytest.mark.parametrize("grade", ["8", "9", "10", "11", "12"])
async def test_selection_survives_code_session_setup_and_reload(grade):
    response = await create_demo_code(DemoCodeRequest(student_name="Sample", grade=grade))
    assert await demo_code_session.get_personalization(response.code) == ("Sample", grade)
    config = await _demo_session_config(response.code)
    assert config.grade == grade
    assert config.grade_stage == GradeStage.independent
    await set_demo_parent_config(
        DemoParentConfigRequest(subjects=[Subject.mathematics], current_unit="Compare two models"),
        auth={"code": response.code, "role": "demo_code"},
    )
    restored = await _demo_session_config(response.code)
    assert restored.grade == grade
    assert restored.grade_stage == GradeStage.independent
    assert restored.current_unit == "Compare two models"


@pytest.mark.parametrize("grade", DEMO_UPPER_GRADES)
@pytest.mark.parametrize("locale", ["en", "es"])
async def test_exact_grade_reaches_actual_tutor_prompts_without_k8_catalog(grade, locale):
    response = await create_demo_code(DemoCodeRequest(grade=grade, current_unit="Our own unit"))
    config = await _demo_session_config(response.code)
    static = ai_service._build_static_prompt(config, locale)
    assert f"INTERACTIVE GRADE {grade} DEMO" in static
    assert GRADE_FOCI[grade] in static
    assert "Rhetoric Stage (grades 6-8)" not in static
    assert "Grades 6-7 (Rhetoric stage" not in static
    assert "Do not call diagnostic evidence tools" in static
    if locale == "es":
        assert "Spanish" in static
    for subject in (Subject.mathematics, Subject.living_books, Subject.science, Subject.history):
        prompt = await ai_service._build_subject_prompt(config, subject, demo_code=response.code, locale=locale)
        assert f"INTERACTIVE GRADE {grade} DEMO" in prompt
        assert "Our own unit" in prompt
        assert "Never complete active assignments" in prompt
        assert "probe." not in prompt
        assert "<literacy_checkin>" not in prompt
        assert "CURRENT SUBJECT:" in prompt


@pytest.mark.parametrize("grade", DEMO_UPPER_GRADES)
async def test_k8_diagnostic_evidence_and_preview_are_not_reused(grade):
    response = await create_demo_code(DemoCodeRequest(grade=grade))
    config = await _demo_session_config(response.code)
    assert await ai_service._diagnostic_context(config, Subject.mathematics, response.code) == ""
    for recorder, subject in (
        (ai_service._record_skill_evidence, Subject.mathematics),
        (ai_service._record_literacy_evidence, Subject.living_books),
        (ai_service._record_music_evidence, Subject.art_music),
        (ai_service._record_phonics_evidence, Subject.language_arts),
        (ai_service._record_language_evidence, Subject.latin),
    ):
        assert await recorder(None, response.code, config, subject, {}) is False
    request = Request({"type": "http", "client": ("127.0.0.1", 12345), "headers": []})
    with pytest.raises(HTTPException) as exc:
        await _require_diagnostic_quota(request, auth={"code": response.code, "role": "demo_code"})
    assert exc.value.status_code == 422
    assert "not yet supported" in exc.value.detail


async def test_existing_curriculum_scope_and_grade8_guidance_stay_distinct():
    # Owner ruling 2026-11-19: Bede is K-12, so the server accepts every grade
    # K-12 and files grades 9-12 under the independent stage. Grade-specific
    # curation (CURATED_GRADES) and the K-8 instruments are still K-8.
    from models.schemas import CURATED_GRADES
    assert CURATED_GRADES == ["K", "1", "2", "3", "4", "5", "6", "7", "8"]
    assert VALID_GRADES == [*CURATED_GRADES, "9", "10", "11", "12"]
    assert VALID_DEMO_GRADES == VALID_GRADES
    for grade in ("9", "10", "11", "12"):
        assert grade_to_stage(grade) == GradeStage.independent
    response = await create_demo_code(DemoCodeRequest(grade="8"))
    config = await _demo_session_config(response.code)
    assert upper_school_guidance(config) == ""
    assert "Rhetoric Stage (grades 6-8)" in ai_service._build_static_prompt(config)


@pytest.mark.parametrize("grade", ["13", "-1", "X"])
async def test_invalid_grade_retains_existing_default_behavior(grade):
    response = await create_demo_code(DemoCodeRequest(grade=grade))
    _, saved_grade = await demo_code_session.get_personalization(response.code)
    assert saved_grade is None


async def test_grades_9_to_12_are_accepted_by_the_server_and_use_the_independent_stage():
    """Owner ruling 2026-11-19 (standing rule): Bede is K-12. A saved plan for
    any grade K-12 builds a real prompt, files 9-12 under the independent
    stage and falls back to the stage band for catalogs with no year entry."""
    from models.schemas import SessionConfig, Subject
    for grade in ("9", "10", "11", "12"):
        config = SessionConfig(student_name="Sample Learner", grade=grade,
                               grade_stage=GradeStage.independent, subjects=[Subject.living_books])
        assert grade_to_stage(grade) == GradeStage.independent
        assert ai_service._grade_descriptor(grade) in ai_service._build_static_prompt(config)
        assert await ai_service._build_subject_prompt(config, Subject.living_books)
