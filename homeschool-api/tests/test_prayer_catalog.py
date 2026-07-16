"""
Regression tests for the weekly Catholic prayer rotation
(services/prayer_catalog.py) — mirrors test_poetry_catalog.py's coverage
of the identical weekly-rotation architecture (see that file's own docstring
for the fuller "why" behind each check), plus the locale-based text
selection this catalog adds on top (English/Spanish, per settings.locale).
"""
from datetime import date

import pytest

from core.config import settings
from models.schemas import GradeStage, SessionConfig, Subject, VALID_GRADES
from services.ai_service import _build_subject_prompt
from services.prayer_catalog import _COLLECTION, current_week, prayer_for_week, prayer_note

pytestmark = pytest.mark.asyncio


async def test_every_grade_stage_has_at_least_one_prayer():
    for stage in (GradeStage.foundations, GradeStage.core_mastery, GradeStage.independent):
        assert any(stage in e["stages"] for e in _COLLECTION), stage


async def test_every_individual_grade_has_at_least_one_prayer():
    for grade in VALID_GRADES:
        assert any(grade in e["grades"] for e in _COLLECTION), grade


async def test_every_entry_has_nonempty_bilingual_text_grades_and_stages():
    for entry in _COLLECTION:
        assert entry["text_en"].strip()
        assert entry["text_es"].strip()
        assert entry["grades"]
        assert entry["stages"]
        assert entry["title"]
        assert entry["attribution"]


async def test_stages_are_derived_from_grades_not_hand_maintained():
    from models.schemas import grade_to_stage
    for entry in _COLLECTION:
        assert entry["stages"] == {grade_to_stage(g) for g in entry["grades"]}


async def test_current_week_is_the_iso_week_number():
    assert current_week(date(2026, 7, 15)) == date(2026, 7, 15).isocalendar()[1]


async def test_prayer_for_week_with_a_grade_only_returns_entries_tagged_for_that_grade():
    for grade in VALID_GRADES:
        for week in range(1, 53):
            entry = prayer_for_week(grade, GradeStage.foundations, today=date.fromisocalendar(2026, week, 1))
            assert grade in entry["grades"]


async def test_prayer_for_week_falls_back_to_stage_when_grade_is_none():
    for stage in (GradeStage.foundations, GradeStage.core_mastery, GradeStage.independent):
        for week in range(1, 53):
            entry = prayer_for_week(None, stage, today=date.fromisocalendar(2026, week, 1))
            assert stage in entry["stages"]


async def test_prayer_for_week_falls_back_to_stage_for_an_unrecognized_grade():
    entry = prayer_for_week("13", GradeStage.independent, today=date(2026, 7, 15))
    assert GradeStage.independent in entry["stages"]


async def test_prayer_for_week_changes_across_the_calendar_year():
    for grade in VALID_GRADES:
        titles = {
            prayer_for_week(grade, GradeStage.foundations, today=date.fromisocalendar(2026, week, 1))["title"]
            for week in range(1, 53)
        }
        assert len(titles) > 1


async def test_prayer_for_week_is_stable_within_the_same_calendar_week():
    same_week_a = prayer_for_week("7", GradeStage.independent, today=date(2026, 7, 13))  # Monday
    same_week_b = prayer_for_week("7", GradeStage.independent, today=date(2026, 7, 19))  # Sunday, same ISO week
    assert same_week_a["title"] == same_week_b["title"]


async def test_week_salt_can_change_which_prayer_is_picked():
    fixed_date = date(2026, 7, 15)
    titles = {
        prayer_for_week("3", GradeStage.core_mastery, week_salt=salt, today=fixed_date)["title"]
        for salt in range(9)
    }
    assert len(titles) > 1


async def test_prayer_note_includes_the_verbatim_english_text_by_default():
    note = prayer_note("8", GradeStage.independent, today=date(2026, 7, 15))
    entry = prayer_for_week("8", GradeStage.independent, today=date(2026, 7, 15))
    assert entry["text_en"] in note
    assert entry["text_es"] not in note
    assert entry["title"] in note
    assert "VERBATIM" in note
    assert "never recite it from memory" in note


async def test_prayer_note_uses_spanish_text_when_locale_is_es():
    note = prayer_note("8", GradeStage.independent, locale="es", today=date(2026, 7, 15))
    entry = prayer_for_week("8", GradeStage.independent, today=date(2026, 7, 15))
    assert entry["text_es"] in note
    assert entry["text_en"] not in note


async def test_prayer_note_falls_back_to_english_for_an_untranslated_locale():
    note = prayer_note("8", GradeStage.independent, locale="pl", today=date(2026, 7, 15))
    entry = prayer_for_week("8", GradeStage.independent, today=date(2026, 7, 15))
    assert entry["text_en"] in note


async def test_prayer_note_returns_empty_string_when_nothing_matches():
    assert prayer_note(None, None, today=date(2026, 7, 15)) == ""


async def test_prayer_note_never_frames_recitation_as_scored_or_measured():
    """Bede's constitution (CLAUDE.md) forbids quantifying a child's faith
    engagement — this prompt block must actively steer away from that, not
    just happen not to mention it."""
    note = prayer_note("3", GradeStage.foundations, today=date(2026, 7, 15))
    assert "never a quiz" in note
    assert "never something you score or measure" in note


# ── Wiring into _build_subject_prompt ───────────────────────────────────────

def _config() -> SessionConfig:
    return SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery)


@pytest.fixture(autouse=True)
def _reset_locale():
    saved = settings.locale
    yield
    settings.locale = saved


async def test_prayer_recitation_is_included_for_morning_time():
    prompt = await _build_subject_prompt(_config(), Subject.morning_time)
    assert "<prayer_recitation>" in prompt


async def test_prayer_recitation_is_omitted_for_other_subjects():
    prompt = await _build_subject_prompt(_config(), Subject.mathematics)
    assert "<prayer_recitation>" not in prompt

    # living_books gets the poetry catalog but not the prayer catalog —
    # prayer recitation is Morning Time's own territory, not literature time.
    prompt = await _build_subject_prompt(_config(), Subject.living_books)
    assert "<prayer_recitation>" not in prompt


async def test_prayer_recitation_follows_the_deployment_locale():
    settings.locale = "es"
    entry = prayer_for_week("4", GradeStage.core_mastery, week_salt=_config().current_term)
    prompt = await _build_subject_prompt(_config(), Subject.morning_time)
    assert entry["text_es"] in prompt
    assert entry["text_en"] not in prompt
