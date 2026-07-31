"""
Tests for the Bible-translation framing note — see services/ai_service.py's
_bible_translation_note and models/schemas.py's
PUBLIC_DOMAIN_BIBLE_TRANSLATIONS. Confirms the public-domain/copyrighted
split: Bede may freely favor a public-domain translation's wording, but a
copyrighted translation gets a paraphrase-by-default instruction and an
explicit ban on presenting uncertain wording as an exact quotation — never
fabricating certainty about text Bede has no verified, licensed copy of.
"""
from models.schemas import GradeStage, SessionConfig, Subject
from services.ai_service import _bible_translation_note


def _config(bible_translation: str | None) -> SessionConfig:
    return SessionConfig(
        student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery,
        bible_translation=bible_translation,
    )


def test_no_translation_set_produces_no_note():
    assert _bible_translation_note(_config(None), Subject.scripture) == ""


def test_wrong_subject_produces_no_note_even_with_translation_set():
    assert _bible_translation_note(_config("ESV"), Subject.mathematics) == ""


def test_public_domain_translation_favors_wording_freely():
    for translation in ("KJV", "Douay-Rheims"):
        note = _bible_translation_note(_config(translation), Subject.scripture)
        assert "public domain" in note
        assert f"favor {translation}'s wording" in note
        # The copyrighted-translation caution language must NOT appear here.
        assert "paraphrase" not in note.lower()


def test_copyrighted_translation_defaults_to_paraphrase():
    for translation in ("ESV", "NIV", "NASB", "NLT", "CSB", "NKJV", "RSV-CE", "NABRE", "NRSV-CE"):
        note = _bible_translation_note(_config(translation), Subject.scripture)
        assert "copyrighted translation" in note
        assert "paraphrase" in note.lower()
        assert "never given a verified, licensed copy" in note


def test_copyrighted_translation_forbids_presenting_uncertain_wording_as_exact():
    note = _bible_translation_note(_config("NABRE"), Subject.saints)
    assert "never present" in note
    assert "false certainty" in note


def test_copyrighted_translation_still_requires_citing_the_reference():
    note = _bible_translation_note(_config("NIV"), Subject.morning_time)
    assert "cite the book, chapter, and verse" in note


def test_applies_across_all_three_gated_subjects():
    for subject in (Subject.scripture, Subject.saints, Subject.morning_time):
        assert _bible_translation_note(_config("ESV"), subject) != ""
        assert _bible_translation_note(_config("KJV"), subject) != ""
