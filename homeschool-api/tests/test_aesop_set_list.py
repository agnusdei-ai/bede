"""The Year 1 Aesop set list: one fable a week, in order, never its moral.

The list lives on the y1-aesop catalog entry. These pin that it is complete
and unduplicated, that both term schedules cover it exactly once, that the
weekly note reaches the real Living Books prompt for Year 1 only, that a
parent's own unit still wins, and that Bede is told never to state the moral.
"""
from datetime import date, timedelta

import pytest

from models.schemas import GradeStage, SessionConfig, Subject, TermSchedule
from services.ai_service import (
    _FABLE_CHOICE_WEEK,
    _build_subject_prompt,
    _fable_of_the_week_note,
    _fable_term_slots,
)
from services.catalog_service import get_readings

READINGS = get_readings("y1-aesop")


def _config(**changes):
    base = dict(student_name="Ada", grade="1", grade_stage=GradeStage.foundations)
    base.update(changes)
    return SessionConfig(**base)


def test_the_list_is_complete_and_unduplicated():
    titles = [r["title"] for r in READINGS]
    assert len(titles) == 33
    assert len(set(titles)) == 33
    assert all(r["theme"].strip() for r in READINGS)


@pytest.mark.parametrize("schedule,terms", [(TermSchedule.trimester, 3), (TermSchedule.quarterly, 4)])
def test_each_schedule_covers_every_fable_exactly_once(schedule, terms):
    seen = []
    for term in range(1, terms + 1):
        slots = _fable_term_slots(_config(term_schedule=schedule, current_term=term), READINGS)
        assert slots[-1] == _FABLE_CHOICE_WEEK
        seen += [s["title"] for s in slots[:-1]]
    assert seen == [r["title"] for r in READINGS]


def test_trimester_terms_are_the_drafted_elevens():
    first = _fable_term_slots(_config(current_term=1), READINGS)
    assert [s["title"] for s in first[:-1]] == [r["title"] for r in READINGS[:11]]


def test_consecutive_weeks_give_consecutive_fables():
    config = _config()
    slots = _fable_term_slots(config, READINGS)
    start = date(2026, 1, 5)
    labels = []
    for i in range(len(slots)):
        note = _fable_of_the_week_note(config, Subject.living_books, start + timedelta(weeks=i))
        labels.append("choice" if "choice week" in note else note.split('"')[1])
    rotation = ["choice" if s == _FABLE_CHOICE_WEEK else s["title"] for s in slots]
    k = rotation.index(labels[0])
    assert labels == rotation[k:] + rotation[:k]


def test_the_note_never_lets_bede_state_the_moral():
    note = _fable_of_the_week_note(_config(), Subject.living_books, date(2026, 10, 26))
    assert "Never state the theme or the moral to the child" in note
    assert "let them find it" in note
    assert "never claiming a particular edition's exact wording" in note


@pytest.mark.parametrize("changes,subject", [
    ({"grade": "2"}, Subject.living_books),
    ({"grade": "4", "grade_stage": GradeStage.core_mastery}, Subject.living_books),
    ({}, Subject.history),
    ({"current_unit": "Our own Farmer Boy reading"}, Subject.living_books),
])
def test_only_year_one_living_books_without_a_parent_unit(changes, subject):
    assert _fable_of_the_week_note(_config(**changes), subject, date(2026, 10, 26)) == ""


def test_kindergarten_is_year_one_too():
    assert _fable_of_the_week_note(_config(grade="K"), Subject.living_books, date(2026, 10, 26))


@pytest.mark.asyncio
async def test_the_real_living_books_prompt_carries_this_weeks_fable():
    today = date(2026, 10, 26)
    prompt = await _build_subject_prompt(_config(), Subject.living_books, local_date=today)
    expected = _fable_of_the_week_note(_config(), Subject.living_books, today)
    assert expected and expected in prompt
