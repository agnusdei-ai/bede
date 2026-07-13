"""
Regression tests for _get_catalog_context()'s saints-specific wiring to
Faith and Life (see services/catalog_service.py's get_catechism_note) —
previously the `saints` subject only ever got the general Mater Amabilis
church-history book list, with no Catholic-catechism-specific awareness at
all.
"""
from models.schemas import GradeStage, SessionConfig, Subject
from services.ai_service import _get_catalog_context


def _config(grade: str, current_unit: str | None = None) -> SessionConfig:
    return SessionConfig(
        student_name="Guest",
        grade=grade,
        grade_stage=GradeStage.core_mastery,
        current_unit=current_unit,
    )


def test_saints_context_includes_faith_and_life_note_for_a_series_grade():
    context = _get_catalog_context(_config("5"), Subject.saints)
    assert "Faith and Life Grade 5" in context
    assert "Credo: I Believe" in context


def test_saints_context_omits_faith_and_life_note_for_kindergarten():
    """Grade K has no Faith and Life entry — the saints subject should
    still work fine, just without that particular note."""
    context = _get_catalog_context(_config("K"), Subject.saints)
    assert "Faith and Life" not in context


def test_saints_context_skipped_entirely_once_parent_sets_current_unit():
    """Matches every other subject's existing behavior — an explicit
    current_unit means the catalog/catechism note would be redundant."""
    context = _get_catalog_context(_config("5", current_unit="Confirmation prep"), Subject.saints)
    assert context == ""


def test_other_subjects_never_get_the_faith_and_life_note():
    """The catechism note is saints-specific — history, for instance,
    already gets its own Mater Amabilis book note and shouldn't also
    pick up Faith and Life content."""
    context = _get_catalog_context(_config("5"), Subject.history)
    assert "Faith and Life" not in context
