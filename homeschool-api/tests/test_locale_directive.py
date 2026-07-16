"""
Tests for locale support (see docs/LOCALIZATION.md): core/config.py's
LOCALE setting (which single non-English locale a deployment OFFERS as a
login-time toggle) and services/ai_service.py's _locale_directive, which
makes Bede converse natively in whichever language was picked at login
rather than translating a finished English reply after the fact.

_locale_directive/_build_static_prompt take `locale` as a plain parameter
now (the per-login JWT claim — see routers/auth.py's login()), not read
from settings.locale globally — these tests pass it directly rather than
monkeypatching settings, matching how routers/tutor.py actually calls them.
"""
import pytest
from pydantic import ValidationError

from models.schemas import GradeStage, SessionConfig
from services.ai_service import _build_static_prompt, _locale_directive


def _config(
    grade: str = "4",
    grade_stage: GradeStage = GradeStage.core_mastery,
    sex: "str | None" = None,
) -> SessionConfig:
    return SessionConfig(student_name="Sam", grade=grade, grade_stage=grade_stage, sex=sex)


def test_english_default_produces_no_language_directive():
    assert _locale_directive(_config(), "en") == ""


def test_omitting_locale_defaults_to_english():
    assert _locale_directive(_config()) == ""


def test_english_default_leaves_static_prompt_byte_for_byte_unchanged():
    """The core backward-compatibility guarantee: an English session must
    not alter today's prompt at all, since _locale_directive returns "" and
    is concatenated with no added whitespace."""
    prompt_with_en = _build_static_prompt(_config(), "en")
    assert "<language>" not in prompt_with_en


def test_spanish_locale_produces_a_language_directive():
    text = _locale_directive(_config(grade="4"), "es")
    assert "<language>" in text
    assert "Spanish" in text
    assert "Sam" in text


def test_spanish_locale_is_reflected_in_the_full_static_prompt():
    prompt = _build_static_prompt(_config(), "es")
    assert "<language>" in prompt
    assert "Spanish" in prompt


def test_language_directive_preserves_tool_names_in_english():
    """Only Bede's own spoken/written words change language — tool names
    and structured data must stay in English regardless of locale, since
    the frontend matches on the literal tool name string."""
    text = _locale_directive(_config(), "es")
    assert "in English" in text


# ── Sex-aware grammatical agreement ──────────────────────────────────────────

def test_male_sex_produces_a_male_agreement_instruction():
    text = _locale_directive(_config(sex="male"), "es")
    assert "Sam is male" in text
    assert "Never hedge into gender-neutral phrasing" in text


def test_female_sex_produces_a_female_agreement_instruction():
    text = _locale_directive(_config(sex="female"), "es")
    assert "Sam is female" in text
    assert "Never hedge into gender-neutral phrasing" in text


def test_no_sex_on_file_falls_back_to_neutral_phrasing_instruction():
    """Covers a config saved before the sex field existed — routers/pod.py
    now requires sex once a deployment offers a non-English login choice at
    all, but this function must still degrade gracefully for old data
    rather than crash or fabricate a sex."""
    text = _locale_directive(_config(sex=None), "es")
    assert "not on file" in text
    assert "gender-neutral phrasing" in text


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
