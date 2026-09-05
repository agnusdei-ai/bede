"""
No English in a Spanish child's lesson.

Reported from a live Spanish session: the subject picker read "Tiempo
Matutino" and Bede opened with *"Hoy en **Morning Time** vamos a comenzar
juntos"*. `_locale_directive` already tells the model to write every word in
the family's language, and it cannot fix what it was handed in English —
`_build_subject_prompt` passed `CURRENT SUBJECT: Morning Time`, so the model
read that as the subject's name and echoed it.

The same defect had three further homes, all of them **server-composed text
with no model in the loop at all**, which no amount of native-language
generation can reach:

  * `_process_tool_use`'s card wording. A Spanish session rendered
    "🔍 Let me ask it this way: ¿Qué crees que pasaría…?" and
    "✨ ¡Muy bien! I noticed you saw that el agua sube." — an English frame
    bolted onto Spanish text, on every turn that produced a card.
  * The empty-turn refusal fallbacks in the tutor and the sandbox.
  * The frontend's own subject names, which were English everywhere in the
    product app (only the demo had translations at all).

These guards are deliberately about SERVER-COMPOSED strings and the labels
handed to the model. What the model itself writes is `_locale_directive`'s
job and cannot be asserted here.
"""
import json
import re
from pathlib import Path

import pytest

from models.schemas import (
    SUBJECT_LABELS,
    SUBJECT_LABELS_BY_LOCALE,
    Subject,
    subject_label,
)
from services.ai_service import (
    _CARD_PHRASES,
    _process_tool_use,
    card_phrases,
    empty_turn_response,
    empty_turn_sandbox_response,
    handwriting_card_titles,
    safeguarding_response,
    moderation_redirect_response,
    demo_quota_response,
)

_ROOT = Path(__file__).resolve().parents[2]
_APP_LOCALES = _ROOT / "homeschool-tutor" / "src" / "i18n" / "locales"
_DEMO_LOCALES = _ROOT / "demo" / "src" / "i18n" / "locales"

# Locales the product actually offers beyond English. Derived rather than
# hardcoded so adding one fails these guards until it is filled in, which is
# the point — a half-translated locale is what produced the report.
NON_ENGLISH = sorted(SUBJECT_LABELS_BY_LOCALE)


# ── The subject's name reaches the model in the session's language ───────


@pytest.mark.parametrize("locale", NON_ENGLISH)
@pytest.mark.parametrize("subject", list(Subject))
def test_every_subject_has_a_name_in_every_locale(locale, subject):
    """A subject missing from a locale falls back to English, which is
    exactly the mixed-language output being fixed — so the fallback is a
    safety net, never the plan."""
    assert subject in SUBJECT_LABELS_BY_LOCALE[locale], (
        f"{subject.value} has no {locale} name, so a {locale} session would "
        f"be told its subject is called {SUBJECT_LABELS[subject]!r}."
    )


@pytest.mark.parametrize("locale", NON_ENGLISH)
def test_no_locales_subject_name_is_just_the_english_one(locale):
    """Catches a placeholder copy-paste. A genuinely identical name is
    possible in principle; none of the current fourteen is, and one that
    is can be exempted here deliberately."""
    same = [
        s.value for s in Subject
        if SUBJECT_LABELS_BY_LOCALE[locale].get(s) == SUBJECT_LABELS[s]
    ]
    assert not same, f"{locale} left these as the English name: {same}"


def test_the_prompt_names_the_subject_in_the_sessions_own_language():
    """The reported defect, at its source. Reads the real f-string in
    _build_subject_prompt rather than calling it (that needs a config, a db
    and a network), because what matters is that it interpolates the
    locale-aware accessor and not the English dict."""
    source = (_ROOT / "homeschool-api" / "services" / "ai_service.py").read_text()
    assert "CURRENT SUBJECT: {subject_label(subject, locale)}" in source, (
        "The subject block no longer names the subject via subject_label(), so "
        "a non-English session is being handed an English name to echo — the "
        "exact defect reported from a live Spanish session."
    )
    assert "CURRENT SUBJECT: {SUBJECT_LABELS[subject]}" not in source


# ── Server-composed card wording ─────────────────────────────────────────


@pytest.mark.parametrize("locale", NON_ENGLISH)
def test_every_card_phrase_exists_in_every_locale(locale):
    missing = set(_CARD_PHRASES["en"]) - set(_CARD_PHRASES[locale])
    assert not missing, (
        f"{locale} is missing card wording {sorted(missing)}, so those cards "
        "would render English text around the model's own Spanish."
    )


@pytest.mark.parametrize("locale", NON_ENGLISH)
def test_no_card_phrase_is_left_in_english(locale):
    same = [k for k, v in _CARD_PHRASES["en"].items() if _CARD_PHRASES[locale].get(k) == v]
    assert not same, f"{locale} left these card phrases in English: {same}"


@pytest.mark.parametrize("locale", NON_ENGLISH)
def test_a_card_carries_no_english_around_the_models_own_words(locale):
    """The concrete failure, reproduced. Feeds the model's own (Spanish)
    text through the formatter and asserts none of the English connectives
    survive around it."""
    rendered = " ".join([
        _process_tool_use("request_narration", {"prompt": "Cuéntame la historia"}, locale),
        _process_tool_use("invite_handwriting", {"prompt": "Escribe lo que pensaste"}, locale),
        _process_tool_use(
            "offer_socratic_hint",
            {"hint_question": "¿Qué pasaría?", "analogy": "como una semilla"},
            locale,
        ),
        _process_tool_use("offer_socratic_hint", {"hint_question": "¿Qué pasaría?"}, locale),
        _process_tool_use(
            "celebrate_discovery",
            {"specific_insight": "el agua sube", "encouragement": "¡Muy bien!"},
            locale,
        ),
    ])
    for english in (
        "Narration Time", "Time to Write or Draw",
        "Let me ask it this way", "Here's a thought to try",
        "I noticed you saw that", "so with that in mind",
    ):
        assert english not in rendered, (
            f"A {locale} session's tool card still renders {english!r}. That is "
            "an English frame around the model's own Spanish — the reported "
            "defect in a different place."
        )


def test_the_composition_scan_recognises_every_locales_card():
    """The trap this fix creates if missed. _composition_note decides whether
    this session's one writing invitation has gone out by scanning history
    for the card's rendered title. Localizing that title without widening the
    scan would make a Spanish session re-invite composition every single
    turn, because the English title would never appear."""
    titles = handwriting_card_titles()
    for locale in ["en", *NON_ENGLISH]:
        rendered = _process_tool_use("invite_handwriting", {"prompt": "x"}, locale)
        assert any(title in rendered for title in titles), (
            f"The {locale} handwriting card's title is not in "
            "handwriting_card_titles(), so _composition_note would not see it."
        )


# ── Every server-composed response is written per locale ────────────────


@pytest.mark.parametrize("locale", NON_ENGLISH)
@pytest.mark.parametrize("fn", [
    safeguarding_response,
    moderation_redirect_response,
    demo_quota_response,
    empty_turn_response,
    empty_turn_sandbox_response,
])
def test_no_server_composed_response_falls_back_to_english(locale, fn):
    """Each of these is emitted with no model in the loop, so a missing
    translation is an English sentence dropped into a Spanish lesson."""
    assert fn(locale) != fn("en"), (
        f"{fn.__name__}({locale!r}) returns the English text, so a {locale} "
        "child would read it in English."
    )


def test_an_unknown_locale_still_gets_a_real_answer():
    """The fallback must be English, never a crash or an empty string — a
    deployment that adds a locale before its strings exist should degrade,
    not break."""
    for fn in (safeguarding_response, empty_turn_response, demo_quota_response):
        assert fn("fr").strip()
    assert subject_label(Subject.logic, "fr") == SUBJECT_LABELS[Subject.logic]
    assert card_phrases("fr") == _CARD_PHRASES["en"]


# ── The screen agrees with the prompt ────────────────────────────────────


def _ui_subjects(directory: Path, locale: str) -> dict:
    data = json.loads((directory / f"{locale}.json").read_text())
    assert "subjects" in data, (
        f"{directory.name}/{locale}.json has no 'subjects' section, so the UI "
        "shows English subject names next to a translated lesson."
    )
    return data["subjects"]


@pytest.mark.parametrize("directory", [_APP_LOCALES, _DEMO_LOCALES], ids=["app", "demo"])
@pytest.mark.parametrize("locale", ["en", *NON_ENGLISH])
def test_the_ui_and_the_prompt_use_the_same_subject_names(directory, locale):
    """Two copies of one fact, and the mismatch is what a family actually
    saw: the picker said "Tiempo Matutino" while Bede said "Morning Time".
    Whatever the screen calls a subject is what Bede must call it."""
    ui = _ui_subjects(directory, locale)
    for subject in Subject:
        expected = subject_label(subject, locale)
        assert ui.get(subject.value) == expected, (
            f"{directory.name}/{locale}.json calls {subject.value} "
            f"{ui.get(subject.value)!r}; the prompt calls it {expected!r}."
        )


# ── No new hardcoded English in the controls a child sees ───────────────


CHILD_FACING = [
    "homeschool-tutor/src/components/TextSizeControl.tsx",
    "homeschool-tutor/src/components/ThemePicker.tsx",
    "homeschool-tutor/src/components/SubjectDrawer.tsx",
    "demo/src/TextSizeControl.tsx",
    "demo/src/ThemePicker.tsx",
]


@pytest.mark.parametrize("path", CHILD_FACING)
def test_no_child_facing_control_hardcodes_an_english_label(path):
    """`title` and `aria-label` are read aloud by a screen reader and shown
    on hover, so a literal English one is the same mixed-language output as
    anything else on screen. Scans for a bare string literal rather than a
    t() call."""
    source = (_ROOT / path).read_text()
    literals = re.findall(r'(?:aria-label|title)="([A-Za-z][^"]*)"', source)
    assert not literals, (
        f"{path} hardcodes {literals} instead of translating them."
    )
