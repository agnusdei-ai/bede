"""
_language_checkin_note (services/ai_service.py) — the prompt-level gate that
nudges Bede to weave in a light foreign-language teach-then-recall moment.
Mirrors tests/test_phonics_checkin_note.py's structure, adapted for this
note's three-subject gate (History, Saints, Art & Music) with NO grade-stage
restriction — the opposite gating shape from phonics' single-subject,
K-2-only gate.
"""
from models.schemas import GradeStage, SessionConfig, Subject
from services.ai_service import _language_checkin_note
from services.diagnostic.language_exposure import LANGUAGES


def _config(**overrides):
    defaults = dict(student_name="Wren", grade="1", grade_stage=GradeStage.foundations)
    defaults.update(overrides)
    return SessionConfig(**defaults)


def test_renders_for_history():
    note = _language_checkin_note(_config(), Subject.history)
    assert "<language_checkin>" in note
    assert "record_language_evidence" in note


def test_renders_for_saints_and_art_music_too():
    for subject in (Subject.saints, Subject.art_music):
        note = _language_checkin_note(_config(), subject)
        assert "<language_checkin>" in note


def test_lists_every_language():
    note = _language_checkin_note(_config(), Subject.history)
    for language in LANGUAGES:
        assert language in note


def test_empty_for_ungated_subjects():
    for subject in (Subject.mathematics, Subject.language_arts, Subject.morning_time, Subject.nature_study):
        assert _language_checkin_note(_config(), subject) == ""


def test_renders_at_every_grade_stage():
    """Unlike phonics (K-2 only), language exposure applies at every grade
    stage — confirming no stage-based gate accidentally crept in here."""
    for stage in (GradeStage.foundations, GradeStage.core_mastery, GradeStage.independent):
        note = _language_checkin_note(
            _config(grade="5", grade_stage=stage), Subject.history,
        )
        assert "<language_checkin>" in note
