"""
Greek & New Testament Foundations (Subject.greek, services/greek_catalog.py).

Sibling to tests/test_latin_catalog.py — the same two things are being
pinned (the mechanics, and the guarantees that live in prompt text a
future edit could soften), so read that module's docstring for the
reasoning rather than repeating it here.

Three things are specific to Greek and are the real reason this file
exists separately:

1. **The manuscript question is sidestepped, not answered.** Every anchor
   was chosen because the Textus Receptus and the critical text read
   identically at the phrase quoted. That is what keeps a K-8 subject out
   of the KJV-only debate, and it is asserted rather than trusted.
2. **Transliteration is mandatory.** A child who cannot yet read the
   alphabet must never be handed bare Greek. Latin has no equivalent
   requirement — its script is already the child's own.
3. **Orthodox and Greek-heritage families must not be corrected.**
   Erasmian is a teaching convention, not how Greek sounded; a child whose
   parish actually uses these words says them differently and is not
   wrong.
"""

import pytest

from models.schemas import (
    SUBJECT_DURATIONS,
    SUBJECT_LABELS,
    GradeStage,
    Subject,
)
from services import greek_catalog
from services.greek_catalog import (
    ALPHA_OMEGA,
    ALPHABET,
    GREAT_COMMANDMENT,
    greek_note,
    term_for_week,
)


ALL_STAGES = [GradeStage.foundations, GradeStage.core_mastery, GradeStage.independent]


# ── Wiring ───────────────────────────────────────────────────────────────

def test_subject_is_fully_registered():
    assert Subject.greek in SUBJECT_DURATIONS
    assert Subject.greek in SUBJECT_LABELS
    assert SUBJECT_LABELS[Subject.greek] == "Greek & New Testament Foundations"


def test_subject_has_a_context_blurb():
    from services.ai_service import _SUBJECT_CONTEXT

    assert Subject.greek in _SUBJECT_CONTEXT


def test_subject_is_registered_as_a_classical_language():
    """
    The mapping that replaced per-language special cases in three separate
    functions (_build_subject_prompt, _bible_translation_note,
    _record_language_evidence). A subject missing from it silently loses
    its catalog block, so this is worth pinning directly.
    """
    from services.ai_service import _CATALOG_NOTE_SUBJECTS, _CLASSICAL_LANGUAGE_SUBJECTS

    # Two mappings, deliberately: "renders a weekly catalog block" and "is a
    # classical language" are different questions (Subject.logic is the
    # first and not the second). See test_logic_catalog.py.
    for subject in (Subject.latin, Subject.greek):
        assert subject in _CATALOG_NOTE_SUBJECTS
        assert subject in _CLASSICAL_LANGUAGE_SUBJECTS
    assert _CLASSICAL_LANGUAGE_SUBJECTS[Subject.greek] == "greek"
    assert _CLASSICAL_LANGUAGE_SUBJECTS[Subject.latin] == "latin"


@pytest.mark.parametrize("stage", ALL_STAGES)
def test_note_renders_for_every_stage(stage):
    note = greek_note(None, stage)
    assert "<greek_foundations>" in note
    assert "</greek_foundations>" in note


# ── The Great Commandment spine, in the original ─────────────────────────

@pytest.mark.parametrize("stage", ALL_STAGES)
def test_great_commandment_is_present_at_every_stage(stage):
    note = greek_note(None, stage)
    assert "Ἀγαπήσεις κύριον τὸν θεόν σου" in note
    assert "Ἀγαπήσεις τὸν πλησίον σου ὡς σεαυτόν" in note


def test_great_commandment_greek_matches_the_new_testament():
    """
    Matthew 22:37, 39 — verified at authoring time, and identical in the
    Textus Receptus and the critical text. Pinned for the same reason its
    Latin counterpart is: it appears in every session of the subject, and
    it is the text most likely to be 'improved' from memory.
    """
    assert GREAT_COMMANDMENT["first_greek"] == (
        "Ἀγαπήσεις κύριον τὸν θεόν σου ἐν ὅλῃ τῇ καρδίᾳ σου "
        "καὶ ἐν ὅλῃ τῇ ψυχῇ σου καὶ ἐν ὅλῃ τῇ διανοίᾳ σου."
    )
    assert GREAT_COMMANDMENT["second_greek"] == "Ἀγαπήσεις τὸν πλησίον σου ὡς σεαυτόν."


def test_the_spine_links_greek_to_latin():
    """
    The pedagogical payoff of running both subjects: the same sentence in
    two languages, and `caritas` visibly translating ἀγάπη. If this link
    is dropped the two subjects become unrelated vocabulary lists.
    """
    assert "caritas" in GREAT_COMMANDMENT["link_to_latin"]
    assert "ἀγάπη" in GREAT_COMMANDMENT["link_to_latin"]


# ── Greek-specific: transliteration is never optional ────────────────────

@pytest.mark.parametrize("stage", ALL_STAGES)
def test_every_term_carries_a_transliteration(stage):
    for term in greek_catalog._terms_for(stage):
        assert term["transliteration"], f"{term['term_id']} has no transliteration"
        assert term["pronunciation"], f"{term['term_id']} has no pronunciation"


@pytest.mark.parametrize("stage", ALL_STAGES)
def test_every_vocabulary_word_carries_a_transliteration(stage):
    for entry in greek_catalog.vocabulary_for(stage):
        greek, translit, english, pron = entry
        assert translit and english and pron, f"{greek} is missing a transliteration/gloss/pronunciation"


@pytest.mark.parametrize("stage", ALL_STAGES)
def test_block_requires_transliteration_alongside_any_greek(stage):
    note = greek_note(None, stage).lower()
    assert "transliteration" in note, (
        "the block must tell Bede to always show transliteration — a child who cannot read the "
        "alphabet yet must never be handed bare Greek"
    )


# ── Greek-specific: the manuscript question stays out of it ──────────────

@pytest.mark.parametrize("stage", ALL_STAGES)
def test_block_refuses_to_adjudicate_the_manuscript_tradition(stage):
    """
    Greek has a live, denominationally charged textual divide that Latin
    does not (Textus Receptus vs. the critical text). A K-8 tutoring
    subject must not pick a side.
    """
    note = greek_note(None, stage).lower()
    assert "manuscript tradition" in note
    assert "do not take a position" in note


# ── Greek-specific: Orthodox and heritage families ───────────────────────

@pytest.mark.parametrize("stage", ALL_STAGES)
def test_block_names_orthodox_families_in_scope(stage):
    """
    Greek is the one classical language that serves Orthodox families,
    who are served by neither `saints` (Catholic scope) nor Latin.
    Omitting them from the scope statement would be conspicuous.
    """
    note = greek_note(None, stage).lower()
    assert "orthodox" in note


@pytest.mark.parametrize("stage", ALL_STAGES)
def test_block_forbids_correcting_a_childs_own_pronunciation(stage):
    note = greek_note(None, stage).lower()
    assert "erasmian" in note
    # Wrapped across a line in the block, so match on the phrase alone.
    assert "not correct them" in note


# ── Shared guarantees, same as Latin's ───────────────────────────────────

TRADITION_SPECIFIC = [
    "purgatory",
    "transubstantiation",
    "rosary",
    "ave maria",
    "immaculate conception",
    "indulgence",
]


@pytest.mark.parametrize("stage", ALL_STAGES)
@pytest.mark.parametrize("doctrine", TRADITION_SPECIFIC)
def test_no_tradition_specific_content_is_taught(stage, doctrine):
    note = greek_note(None, stage).lower()
    taught, _, _scope = note.partition("faith scope")
    assert doctrine not in taught, (
        f"{doctrine!r} appears in the taught content of the {stage} Greek block"
    )


@pytest.mark.parametrize("stage", ALL_STAGES)
def test_block_states_the_inclusivity_guarantee(stage):
    note = greek_note(None, stage).lower()
    assert "shared inheritance" in note
    assert any(w in note for w in ("pastor", "priest", "minister"))


@pytest.mark.parametrize("stage", ALL_STAGES)
def test_block_forbids_improvised_greek(stage):
    note = greek_note(None, stage).lower()
    assert "never recite" in note
    assert "never compose" in note


# ── The alphabet — Greek's K-2 curriculum ────────────────────────────────

def test_alphabet_is_complete_and_ordered():
    assert len(ALPHABET) == 24, "the Greek alphabet has 24 letters"
    assert ALPHABET[0][2] == "alpha"
    assert ALPHABET[-1][2] == "omega"


def test_k2_gets_a_small_slice_of_the_alphabet_not_all_of_it():
    """
    Handing a 5-year-old all 24 letters in one session is the failure mode
    this guards. Later stages get the whole thing as a reference, because
    by then they are reading it rather than learning it.
    """
    slice_ = greek_catalog.letters_for_week(GradeStage.foundations)
    assert 0 < len(slice_) < len(ALPHABET)
    assert greek_catalog.letters_for_week(GradeStage.independent) == ALPHABET


def test_alphabet_rotation_reaches_every_letter_across_a_year():
    """A letter no week ever lands on would never be taught."""
    from datetime import date, timedelta

    start = date(2026, 1, 5)
    seen = set()
    for week in range(52):
        for letter in greek_catalog.letters_for_week(
            GradeStage.foundations, week_salt=0, today=start + timedelta(weeks=week)
        ):
            seen.add(letter[2])
    assert len(seen) == 24, f"rotation reaches only {len(seen)} of 24 letters"


def test_k2_block_carries_the_alpha_omega_anchor():
    note = greek_note("K", GradeStage.foundations)
    assert ALPHA_OMEGA["greek"] in note
    assert "Revelation 22:13" in note


def test_alpha_omega_verse_is_verbatim():
    assert ALPHA_OMEGA["greek"] == (
        "ἐγὼ τὸ Ἄλφα καὶ τὸ Ὦ, ὁ πρῶτος καὶ ὁ ἔσχατος, ἡ ἀρχὴ καὶ τὸ τέλος."
    )


def test_older_stages_do_not_get_the_k2_alphabet_framing():
    """The alpha/omega hook is the K-2 motivation for learning letters at
    all; a 7th grader reading John does not need it re-explained."""
    note = greek_note("7", GradeStage.independent)
    assert "THE FIRST LETTER AND THE LAST" not in note


# ── Stage gating and rotation ────────────────────────────────────────────

def test_k2_meets_only_the_three_virtues():
    ids = {t["term_id"] for t in greek_catalog._terms_for(GradeStage.foundations)}
    assert ids == {"pistis", "elpis", "agape"}


def test_all_six_terms_are_available_from_third_grade():
    for stage in (GradeStage.core_mastery, GradeStage.independent):
        assert len(greek_catalog._terms_for(stage)) == 6


def test_k2_block_forbids_grammar_and_reading_sentences():
    note = greek_note("K", GradeStage.foundations)
    assert "NO grammar" in note
    assert "never ask a child this age to read a Greek sentence" in note


def test_rotation_covers_every_term_across_a_cycle():
    from datetime import date, timedelta

    start = date(2026, 1, 5)
    seen = {
        term_for_week(None, GradeStage.independent, week_salt=0, today=start + timedelta(weeks=w))["term_id"]
        for w in range(12)
    }
    assert len(seen) == 6, f"rotation reaches only {sorted(seen)}"


def test_grade_overrides_stage_when_they_disagree():
    term = term_for_week("K", GradeStage.independent)
    assert term["term_id"] in {"pistis", "elpis", "agape"}


def test_greek_terms_mirror_the_latin_ones():
    """
    The six Greek terms are deliberately the six Latin ones (with λόγος in
    Ora et Labora's place). If someone adds a seventh to one catalog and
    not the other, the two subjects stop lining up and the cross-language
    lesson in Year 8 stops working.
    """
    from services import latin_catalog

    assert len(greek_catalog._TERMS) == len(latin_catalog._TERMS) == 6


def test_shared_anchor_verses_really_are_shared_with_latin():
    """
    Four of the six anchors are the SAME verse in both subjects — that is
    the whole basis of the 'same sentence, two languages' lesson.
    """
    from services import latin_catalog

    greek_refs = {t["anchor_ref"] for t in greek_catalog._TERMS}
    latin_refs = {t["anchor_ref"] for t in latin_catalog._TERMS}
    shared = greek_refs & latin_refs
    assert {"1 Corinthians 13:13", "Romans 12:12", "John 14:6"} <= shared, (
        f"expected the shared anchors to survive; found {sorted(shared)}"
    )


def test_k2_never_sees_a_term_caution():
    """
    Every caution in this catalog is analytical 3+ material. The one that
    makes this concrete rather than theoretical: ἀγάπη is taught at every
    stage, and its note distinguishes it from ἔρως — which must never
    render into a five-year-old's prompt block.
    """
    note = greek_note("K", GradeStage.foundations)
    assert "IMPORTANT for this term" not in note
    assert "ἔρως" not in note, "eros must never appear in a K-2 block"


@pytest.mark.parametrize("stage", [GradeStage.core_mastery, GradeStage.independent])
def test_older_stages_still_get_their_cautions(stage):
    """The suppression above must not have silently dropped them everywhere."""
    from datetime import date, timedelta

    start = date(2026, 1, 5)
    rendered = [
        greek_note(None, stage, week_salt=0, today=start + timedelta(weeks=w))
        for w in range(12)
    ]
    assert any("IMPORTANT for this term" in note for note in rendered), (
        f"no caution ever renders at {stage} — the K-2 suppression is too broad"
    )
