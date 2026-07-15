"""
Regression tests for the weekly Catholic poetry rotation
(services/poetry_catalog.py) — replaces the old term-based rotation whose
current_term dependency was the actual root cause of the demo (and,
quietly, real sessions that never advanced their term) always landing on
the same poet. See routers/tutor.py's _demo_current_term for the related
picture-study fix, which this module's week_salt parameter reuses.

Also covers grade-specific curation (K-8, not just the 3 broad
GradeStage bands) added on top of the weekly rotation.
"""
from datetime import date

import pytest

from models.schemas import GradeStage, VALID_GRADES
from services.poetry_catalog import _COLLECTION, current_week, poem_for_week, poetry_note

pytestmark = pytest.mark.asyncio


async def test_every_grade_stage_has_at_least_one_poem():
    for stage in (GradeStage.foundations, GradeStage.core_mastery, GradeStage.independent):
        assert any(stage in e["stages"] for e in _COLLECTION), stage


async def test_every_individual_grade_has_at_least_one_poem():
    for grade in VALID_GRADES:
        assert any(grade in e["grades"] for e in _COLLECTION), grade


async def test_every_entry_has_nonempty_text_grades_and_stages():
    for entry in _COLLECTION:
        assert entry["text"].strip()
        assert entry["grades"]
        assert entry["stages"]
        assert entry["title"]
        assert entry["poet"]


async def test_stages_are_derived_from_grades_not_hand_maintained():
    """Guards against the two ever drifting apart — stages must always be
    exactly grade_to_stage() applied to each entry's own grade set."""
    from models.schemas import grade_to_stage
    for entry in _COLLECTION:
        assert entry["stages"] == {grade_to_stage(g) for g in entry["grades"]}


async def test_current_week_is_the_iso_week_number():
    assert current_week(date(2026, 7, 15)) == date(2026, 7, 15).isocalendar()[1]


async def test_poem_for_week_with_a_grade_only_returns_entries_tagged_for_that_grade():
    for grade in VALID_GRADES:
        for week in range(1, 53):
            entry = poem_for_week(grade, GradeStage.foundations, today=date.fromisocalendar(2026, week, 1))
            assert grade in entry["grades"]


async def test_poem_for_week_falls_back_to_stage_when_grade_is_none():
    for stage in (GradeStage.foundations, GradeStage.core_mastery, GradeStage.independent):
        for week in range(1, 53):
            entry = poem_for_week(None, stage, today=date.fromisocalendar(2026, week, 1))
            assert stage in entry["stages"]


async def test_poem_for_week_falls_back_to_stage_for_an_unrecognized_grade():
    entry = poem_for_week("13", GradeStage.independent, today=date(2026, 7, 15))
    assert GradeStage.independent in entry["stages"]


async def test_poem_for_week_changes_across_the_calendar_year():
    """The whole point of the fix — confirms the rotation actually reaches
    more than one poem across a school year, unlike the old current_term
    default that silently pinned every session to the same poet forever."""
    for grade in VALID_GRADES:
        titles = {
            poem_for_week(grade, GradeStage.foundations, today=date.fromisocalendar(2026, week, 1))["title"]
            for week in range(1, 53)
        }
        assert len(titles) > 1


async def test_poem_for_week_is_stable_within_the_same_calendar_week():
    same_week_a = poem_for_week("7", GradeStage.independent, today=date(2026, 7, 13))  # Monday
    same_week_b = poem_for_week("7", GradeStage.independent, today=date(2026, 7, 19))  # Sunday, same ISO week
    assert same_week_a["title"] == same_week_b["title"]


async def test_week_salt_can_change_which_poem_is_picked():
    fixed_date = date(2026, 7, 15)
    titles = {
        poem_for_week("3", GradeStage.core_mastery, week_salt=salt, today=fixed_date)["title"]
        for salt in range(6)
    }
    assert len(titles) > 1


async def test_poetry_note_includes_the_verbatim_text_and_instruction():
    note = poetry_note("8", GradeStage.independent, today=date(2026, 7, 15))
    entry = poem_for_week("8", GradeStage.independent, today=date(2026, 7, 15))
    assert entry["text"] in note
    assert entry["title"] in note
    assert "VERBATIM" in note
    assert "never recite it from memory" in note


async def test_poetry_note_returns_empty_string_when_nothing_matches():
    assert poetry_note(None, None, today=date(2026, 7, 15)) == ""
