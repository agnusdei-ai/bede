"""
Regression tests for services/catalog_service.py's get_catechism_note() —
grade-level orientation for Ignatius Press's Faith and Life catechetical
series, used by the `saints` subject alongside the existing Ambleside
Online book-list catalog. See data/catechism/faith_and_life.json's own
_comment for why this is thematic orientation, not a claimed-exhaustive
chapter list or the books' actual copyrighted text.
"""
from services.catalog_service import get_catechism_note


def test_get_catechism_note_returns_a_note_for_every_series_grade():
    for grade in ("1", "2", "3", "4", "5", "6", "7", "8"):
        note = get_catechism_note(grade)
        assert note is not None, f"expected a note for grade {grade}"
        assert f"Grade {grade}" in note


def test_get_catechism_note_includes_the_real_book_title_and_theme():
    note = get_catechism_note("5")
    assert "Credo: I Believe" in note
    assert "Creed" in note


def test_get_catechism_note_returns_none_for_kindergarten():
    """The series starts at grade 1 — "K" is a real SessionConfig.grade
    value elsewhere in the app, but has no entry here."""
    assert get_catechism_note("K") is None


def test_get_catechism_note_returns_none_for_unknown_grade():
    assert get_catechism_note("99") is None


def test_get_catechism_note_returns_none_for_empty_or_none():
    assert get_catechism_note(None) is None
    assert get_catechism_note("") is None


def test_get_catechism_note_strips_whitespace():
    assert get_catechism_note(" 3 ") == get_catechism_note("3")
