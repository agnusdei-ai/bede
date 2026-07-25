"""
_phonics_checkin_note (services/ai_service.py) — the prompt-level gate that
nudges Bede to weave in a light phonics check-in. Verifies it only ever
renders for K-2 (GradeStage.foundations) Language Arts, matching the same
gate _record_phonics_evidence enforces a second time at the code level (see
tests/test_record_phonics_evidence.py), and that the rendered block actually
names every domain a check-in could target.
"""
from models.schemas import GradeStage, SessionConfig, Subject
from services.ai_service import _phonics_checkin_note
from services.diagnostic.phonics import DOMAINS


def _config(**overrides):
    defaults = dict(student_name="Wren", grade="1", grade_stage=GradeStage.foundations)
    defaults.update(overrides)
    return SessionConfig(**defaults)


def test_renders_for_k2_language_arts():
    note = _phonics_checkin_note(_config(), Subject.language_arts)
    assert "<phonics_checkin>" in note
    assert "record_phonics_evidence" in note


def test_lists_every_domain():
    note = _phonics_checkin_note(_config(), Subject.language_arts)
    for domain in DOMAINS:
        assert domain in note


def test_empty_for_non_language_arts_subject():
    for subject in (Subject.mathematics, Subject.history, Subject.morning_time):
        assert _phonics_checkin_note(_config(), subject) == ""


def test_empty_for_older_grade_stages():
    for stage in (GradeStage.core_mastery, GradeStage.independent):
        note = _phonics_checkin_note(
            _config(grade="5", grade_stage=stage), Subject.language_arts,
        )
        assert note == ""


def test_empty_for_language_arts_at_an_older_stage_even_though_subject_matches():
    """Both halves of the gate are independently required — matching the
    subject alone isn't enough without also matching the grade stage."""
    note = _phonics_checkin_note(
        _config(grade="6", grade_stage=GradeStage.independent), Subject.language_arts,
    )
    assert note == ""
