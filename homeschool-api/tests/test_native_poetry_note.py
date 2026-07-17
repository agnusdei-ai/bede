"""
Real check for the non-English poetry co-study substitute — a live Spanish
session showed poetry_catalog.py's English poem quoted verbatim mid-Spanish
reply (a "Spanglish" kink), since that catalog is unconditionally English
regardless of locale. Rather than build/maintain a verified-translation
library per locale, non-English sessions get Bede composing a short
original reflection instead — see _native_poetry_note's own docstring for
the full reasoning. Confirms the note fires only for the right locale,
never claims a real poet's attribution, and is actually wired into
_build_subject_prompt in place of (not alongside) the English catalog quote.
"""
import pytest

from models.schemas import GradeStage, SessionConfig, Subject
from services.ai_service import _build_subject_prompt, _native_poetry_note


def test_english_locale_produces_no_note():
    assert _native_poetry_note("en") == ""


def test_spanish_locale_produces_a_note():
    note = _native_poetry_note("es")
    assert note != ""
    assert "<poetry_co_study>" in note
    assert "Spanish (Español)" in note


def test_spanish_note_forbids_false_attribution():
    note = _native_poetry_note("es")
    assert "never attributed to a real poet" in note
    assert "never presented as an existing published work" in note


def _config() -> SessionConfig:
    return SessionConfig(student_name="Sofía", grade="4", grade_stage=GradeStage.core_mastery, sex="female")


@pytest.mark.asyncio
async def test_build_subject_prompt_uses_native_composition_for_spanish_morning_time():
    prompt = await _build_subject_prompt(_config(), Subject.morning_time, locale="es")
    assert "<poetry_co_study>" in prompt
    assert "There is no verified" in prompt
    # Must NOT also contain the English catalog's own poem attribution —
    # this is a replacement, not an addition. ("given VERBATIM" alone isn't
    # a safe check here: prayer_catalog.py's own, correctly locale-aware
    # prayer-recitation note legitimately uses that same phrase for Morning
    # Time too.)
    assert "This week's poem is" not in prompt


@pytest.mark.asyncio
async def test_build_subject_prompt_uses_native_composition_for_spanish_living_books():
    prompt = await _build_subject_prompt(_config(), Subject.living_books, locale="es")
    assert "<poetry_co_study>" in prompt


@pytest.mark.asyncio
async def test_build_subject_prompt_keeps_the_english_catalog_for_english_sessions():
    prompt = await _build_subject_prompt(_config(), Subject.morning_time, locale="en")
    assert "There is no verified" not in prompt


@pytest.mark.asyncio
async def test_build_subject_prompt_omits_poetry_note_for_unrelated_spanish_subject():
    prompt = await _build_subject_prompt(_config(), Subject.mathematics, locale="es")
    assert "<poetry_co_study>" not in prompt
