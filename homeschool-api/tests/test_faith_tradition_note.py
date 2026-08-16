"""
Tests for the faith-tradition framing note — see services/ai_service.py's
_faith_tradition_note and _OUTSIDE_HISTORIC_CHRISTIAN_SCOPE. Confirms the
ordinary case (Bede adapts tone/emphasis to whatever Christian tradition a
family names) and the scope guard: a tradition built on a modern
individual's claimed revelation alongside or in place of the Bible (e.g.
Jehovah's Witnesses, Mormonism/the Book of Mormon) does not get that
same accommodation — Bede keeps teaching from the historic Christian
consensus regardless, and never states this as a judgment to the child or
family.
"""
from models.schemas import GradeStage, SessionConfig, Subject
from services.ai_service import _faith_tradition_note


def _config(faith_tradition: str | None) -> SessionConfig:
    return SessionConfig(
        student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery,
        faith_tradition=faith_tradition,
    )


def test_no_tradition_set_produces_no_note():
    assert _faith_tradition_note(_config(None), Subject.scripture) == ""


def test_wrong_subject_produces_no_note_even_with_tradition_set():
    assert _faith_tradition_note(_config("Baptist"), Subject.mathematics) == ""


def test_ordinary_christian_tradition_gets_accommodated():
    note = _faith_tradition_note(_config("Baptist"), Subject.scripture)
    assert "Baptist" in note
    assert "feels at home there" in note


def test_applies_across_all_three_gated_subjects():
    for subject in (Subject.scripture, Subject.saints, Subject.morning_time):
        assert _faith_tradition_note(_config("Lutheran"), subject) != ""


def test_traditions_outside_historic_christian_scope_are_not_accommodated():
    for tradition in (
        "Jehovah's Witness", "jehovah's witness family", "Watchtower",
        "Mormon", "ex-Mormon household", "Latter-day Saint", "LDS", "Book of Mormon",
    ):
        note = _faith_tradition_note(_config(tradition), Subject.scripture)
        assert "historic Christian consensus" in note
        assert "feels at home there" not in note


def test_outside_scope_note_does_not_adapt_bedes_own_teaching():
    note = _faith_tradition_note(_config("Jehovah's Witness"), Subject.scripture)
    assert "Do not adapt Scripture, saint, or faith content to fit it" in note
    assert "do not treat any writing beyond the Bible as scripture" in note


def test_outside_scope_note_is_never_voiced_as_a_judgment():
    note = _faith_tradition_note(_config("Mormon"), Subject.saints)
    assert "Never say this to the child or family" in note
    assert "never frame it as a judgment of their beliefs" in note


def test_outside_scope_guard_applies_across_all_three_gated_subjects():
    for subject in (Subject.scripture, Subject.saints, Subject.morning_time):
        note = _faith_tradition_note(_config("Jehovah's Witness"), subject)
        assert "historic Christian consensus" in note
