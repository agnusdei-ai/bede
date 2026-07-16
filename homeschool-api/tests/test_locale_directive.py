"""
Tests for locale support (Phase 0 of localization — see docs/LOCALIZATION.md):
core/config.py's LOCALE setting and services/ai_service.py's
_locale_directive, which makes Bede converse natively in the target
language rather than translating a finished English reply after the fact.
"""
import pytest
from pydantic import ValidationError

from models.schemas import GradeStage, SessionConfig
from services.ai_service import _build_static_prompt, _locale_directive


def _config(grade: str = "4", grade_stage: GradeStage = GradeStage.core_mastery) -> SessionConfig:
    return SessionConfig(student_name="Sam", grade=grade, grade_stage=grade_stage)


def test_english_default_produces_no_language_directive(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "locale", "en")
    assert _locale_directive(_config()) == ""


def test_english_default_leaves_static_prompt_byte_for_byte_unchanged(monkeypatch):
    """The core backward-compatibility guarantee: LOCALE=en (the default)
    must not alter today's prompt at all, since _locale_directive returns ""
    and is concatenated with no added whitespace."""
    from core.config import settings

    monkeypatch.setattr(settings, "locale", "en")
    prompt_with_en = _build_static_prompt(_config())
    assert "<language>" not in prompt_with_en


def test_spanish_locale_produces_a_language_directive(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "locale", "es")
    text = _locale_directive(_config(grade="4"))
    assert "<language>" in text
    assert "Spanish" in text
    assert "Sam" in text


def test_spanish_locale_is_reflected_in_the_full_static_prompt(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "locale", "es")
    prompt = _build_static_prompt(_config())
    assert "<language>" in prompt
    assert "Spanish" in prompt


def test_language_directive_preserves_tool_names_in_english(monkeypatch):
    """Only Bede's own spoken/written words change language — tool names
    and structured data must stay in English regardless of locale, since
    the frontend matches on the literal tool name string."""
    from core.config import settings

    monkeypatch.setattr(settings, "locale", "es")
    text = _locale_directive(_config())
    assert "in English" in text


def test_settings_rejects_an_unsupported_locale_value():
    from core.config import Settings

    with pytest.raises(ValidationError, match="LOCALE"):
        Settings(locale="fr")


def test_settings_rejects_a_case_mismatched_locale_value():
    from core.config import Settings

    with pytest.raises(ValidationError, match="LOCALE"):
        Settings(locale="ES")


def test_settings_accepts_english_and_every_supported_locale():
    from core.config import Settings, SUPPORTED_LOCALES

    assert Settings(locale="en").locale == "en"
    for code in SUPPORTED_LOCALES:
        assert Settings(locale=code).locale == code
