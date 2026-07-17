"""
Real check for the Guadalupe/San Juan Diego devotional note — the app's
single Spanish locale is deliberately framed as Mexican, not pan-Hispanic-
neutral (see docs/LOCALIZATION.md), so Saints & Catechism and Morning Time
sessions in that locale get cultural/devotional grounding Bede can draw on.
Confirms _guadalupe_note only fires for the right locale/subject
combination, that its facts are present, and that it's actually wired into
_build_subject_prompt.
"""
import pytest

from models.schemas import GradeStage, SessionConfig, Subject
from services.ai_service import _build_subject_prompt, _guadalupe_note


def test_english_locale_produces_no_note():
    assert _guadalupe_note(Subject.saints, "en") == ""


def test_spanish_locale_saints_subject_produces_a_note():
    note = _guadalupe_note(Subject.saints, "es")
    assert note != ""
    assert "Guadalupe" in note
    assert "Juan Diego" in note


def test_spanish_locale_morning_time_subject_produces_a_note():
    note = _guadalupe_note(Subject.morning_time, "es")
    assert note != ""


def test_spanish_locale_unrelated_subject_produces_no_note():
    assert _guadalupe_note(Subject.mathematics, "es") == ""
    assert _guadalupe_note(Subject.living_books, "es") == ""


def test_note_contains_the_verified_apparition_and_canonization_facts():
    note = _guadalupe_note(Subject.saints, "es")
    assert "December 9, 1531" in note
    assert "December 12, 1531" in note
    assert "Tepeyac" in note
    assert "July 31, 2002" in note
    assert "Indigenous" in note


def _config() -> SessionConfig:
    return SessionConfig(student_name="Sofía", grade="4", grade_stage=GradeStage.core_mastery, sex="female")


@pytest.mark.asyncio
async def test_build_subject_prompt_includes_the_note_for_spanish_saints_session():
    prompt = await _build_subject_prompt(_config(), Subject.saints, locale="es")
    assert "Guadalupe" in prompt


@pytest.mark.asyncio
async def test_build_subject_prompt_omits_the_note_for_english_saints_session():
    prompt = await _build_subject_prompt(_config(), Subject.saints, locale="en")
    assert "Guadalupe" not in prompt


@pytest.mark.asyncio
async def test_build_subject_prompt_omits_the_note_for_spanish_unrelated_subject():
    prompt = await _build_subject_prompt(_config(), Subject.mathematics, locale="es")
    assert "Guadalupe" not in prompt
