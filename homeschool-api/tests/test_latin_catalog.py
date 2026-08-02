"""
Latin & Christian Foundations (Subject.latin, services/latin_catalog.py).

Two things are being pinned here, and only one of them is ordinary
plumbing:

1. The mechanics — the subject is wired end to end, the weekly rotation
   respects the stage, and the block only appears for its own subject.

2. The guarantees that are the whole reason this subject exists separately
   from Saints & Catechism. It must be teachable in full by a family that
   holds none of the distinctively Catholic doctrines (the intercession of
   the saints, the sacraments, transubstantiation, purgatory, the Marian
   dogmas), and its Latin must be QUOTED rather than recalled. Neither
   property survives on good intentions: both live in prompt text a future
   edit could quietly soften, so both are asserted against the rendered
   block itself.

No test here can verify what the live model actually does with the prompt
— same honest limit as tests/test_continue_sentinel_no_affirmation.py.
What they verify is that the guardrail text is present to be followed.
"""

import pytest

from models.schemas import (
    SUBJECT_DURATIONS,
    SUBJECT_LABELS,
    GradeStage,
    Subject,
)
from services import latin_catalog
from services.latin_catalog import GREAT_COMMANDMENT, latin_note, term_for_week


ALL_STAGES = [GradeStage.foundations, GradeStage.core_mastery, GradeStage.independent]


# ── Wiring ───────────────────────────────────────────────────────────────

def test_subject_is_fully_registered():
    """The three-step 'Adding a New Subject' contract in CLAUDE.md."""
    assert Subject.latin in SUBJECT_DURATIONS
    assert Subject.latin in SUBJECT_LABELS
    assert SUBJECT_LABELS[Subject.latin] == "Latin & Christian Foundations"


def test_subject_has_a_context_blurb():
    from services.ai_service import _SUBJECT_CONTEXT

    assert Subject.latin in _SUBJECT_CONTEXT, "Subject.latin missing from _SUBJECT_CONTEXT"


@pytest.mark.parametrize("stage", ALL_STAGES)
def test_note_renders_for_every_stage(stage):
    note = latin_note(None, stage)
    assert "<latin_foundations>" in note
    assert "</latin_foundations>" in note


@pytest.mark.parametrize("stage", ALL_STAGES)
def test_every_stage_has_vocabulary(stage):
    """A stage with no words would render an empty list and read as a bug."""
    assert latin_catalog.vocabulary_for(stage), f"{stage} has no vocabulary"


# ── The Great Commandment spine ──────────────────────────────────────────

@pytest.mark.parametrize("stage", ALL_STAGES)
def test_great_commandment_is_present_at_every_stage(stage):
    """
    The sentence the whole subject hangs on, per the design: both halves,
    in Latin, in every stage's block — a K-2 child meets it by ear and an
    8th grader parses it, but neither is ever without it.
    """
    note = latin_note(None, stage)
    assert "Diliges Dominum Deum tuum ex toto corde tuo" in note
    assert "Diliges proximum tuum sicut teipsum" in note


def test_great_commandment_latin_matches_the_vulgate():
    """
    Verified against published Clementine Vulgate editions at authoring
    time (Matthew 22:37, 39). Pinned because it is the one text in this
    app most likely to be 'improved' by someone editing from memory — and
    a wrong ending here is a wrong lesson in every session of the subject.
    """
    assert GREAT_COMMANDMENT["first_latin"] == (
        "Diliges Dominum Deum tuum ex toto corde tuo, et in tota anima tua, et in tota mente tua."
    )
    assert GREAT_COMMANDMENT["second_latin"] == "Diliges proximum tuum sicut teipsum."


# ── Faith-scope guarantee: inclusive, not Catholic-specific ──────────────

# The doctrines a Baptist, Reformed, or non-denominational family does not
# hold. None may be taught in this subject — that is its whole premise.
TRADITION_SPECIFIC = [
    "purgatory",
    "transubstantiation",
    "rosary",
    "ave maria",
    "salve regina",
    "immaculate conception",
    "assumption of mary",
    "indulgence",
    "confession",
    "eucharist",
]


@pytest.mark.parametrize("stage", ALL_STAGES)
@pytest.mark.parametrize("doctrine", TRADITION_SPECIFIC)
def test_no_tradition_specific_content_is_taught(stage, doctrine):
    """
    Nothing distinctive to one Christian tradition may appear as CONTENT.
    Checked against the rendered block rather than the source data so a
    future addition anywhere in the pipeline is caught.
    """
    note = latin_note(None, stage).lower()
    # The block legitimately names some of these in its own prohibition
    # ("do NOT introduce ... the sacraments"), so a bare substring check
    # would be self-defeating. Assert instead that each appears only in
    # the faith-scope section, never in the taught vocabulary above it.
    taught, _, _scope = note.partition("faith scope")
    assert doctrine not in taught, (
        f"{doctrine!r} appears in the taught content of the {stage} Latin block — "
        f"this subject must be teachable in full by a family that does not hold it."
    )


@pytest.mark.parametrize("stage", ALL_STAGES)
def test_block_states_the_inclusivity_guarantee(stage):
    """
    The guarantee travels with the content, exactly as the scripture year
    plans' canon/translation neutrality does (see
    tests/test_catalog_coverage.py) — not as a single shared line
    somewhere else that a future edit could drop.
    """
    note = latin_note(None, stage).lower()
    assert "shared" in note, "block does not state that the content is shared across traditions"
    assert any(w in note for w in ("pastor", "priest", "minister")), (
        "block does not defer doctrinal questions to the family's own clergy"
    )


@pytest.mark.parametrize("stage", ALL_STAGES)
def test_block_forbids_improvised_latin(stage):
    """
    The verbatim rule. An inflected language recited from model memory
    will eventually hand a child a wrong ending they cannot catch — the
    same reasoning behind poetry_catalog.py and prayer_catalog.py.
    """
    note = latin_note(None, stage).lower()
    assert "never recite" in note
    assert "never compose" in note or "never compose latin" in note


# ── Honesty about sourcing ───────────────────────────────────────────────

def test_ora_et_labora_is_not_attributed_to_the_rule():
    """
    The motto is 19th-century (Maurus Wolter, Beuron, 1880), not a phrase
    from St. Benedict's Rule. Bede's first non-negotiable rule forbids
    fabricated certainty, and this is the single most commonly repeated
    false attribution in the whole subject.
    """
    entry = latin_catalog._TERMS_BY_ID["ora_et_labora"]
    caution = entry["caution"].lower()
    assert "nowhere in" in caution
    assert "1880" in caution
    # And the sentence that IS from the Rule is supplied to quote instead.
    assert entry["anchor_latin"] == "Otiositas inimica est animæ."


def test_sapientia_avoids_the_divergent_psalm_numbering():
    """
    'Initium sapientiae timor Domini' is Vulgate Ps 110:10 but Ps 111:10
    in the Hebrew numbering nearly every Protestant Bible follows. Citing
    it would force a numbering tradition on a child in the subject's own
    wisdom lesson. Proverbs 9:10 says the same thing under the same
    reference in every tradition.
    """
    entry = latin_catalog._TERMS_BY_ID["sapientia"]
    assert entry["anchor_ref"] == "Proverbs 9:10"
    assert "Psalm" not in entry["anchor_ref"]


# ── Stage gating and rotation ────────────────────────────────────────────

def test_k2_meets_only_the_three_virtues():
    """
    K-2 is ear-only and gets Fides, Spes, Caritas — concrete enough to
    hold. Sapientia, Veritas, and Ora et Labora are abstractions a
    Grammar-stage child would be handed as noise, so they start at 3-5.
    """
    ids = {t["term_id"] for t in latin_catalog._terms_for(GradeStage.foundations)}
    assert ids == {"fides", "spes", "caritas"}


def test_all_six_terms_are_available_from_third_grade():
    for stage in (GradeStage.core_mastery, GradeStage.independent):
        ids = {t["term_id"] for t in latin_catalog._terms_for(stage)}
        assert len(ids) == 6, f"{stage} should have all six foundational terms, got {ids}"


def test_k2_block_forbids_grammar():
    """
    The pedagogical floor: a Grammar-stage child hears and says Latin, and
    is never asked to parse, spell, or translate it.
    """
    note = latin_note("K", GradeStage.foundations)
    assert "EAR ONLY" in note
    assert "NO grammar" in note


def test_rotation_is_weekly_and_deterministic():
    """Same week + same salt + same stage → same term, always."""
    from datetime import date

    day = date(2026, 3, 4)
    first = term_for_week(None, GradeStage.independent, week_salt=0, today=day)
    second = term_for_week(None, GradeStage.independent, week_salt=0, today=day)
    assert first is not None and first["term_id"] == second["term_id"]


def test_rotation_covers_every_term_across_a_cycle():
    """No term is unreachable — a term nobody ever lands on is dead content."""
    from datetime import date, timedelta

    start = date(2026, 1, 5)
    seen = {
        term_for_week(None, GradeStage.independent, week_salt=0, today=start + timedelta(weeks=w))["term_id"]
        for w in range(12)
    }
    assert len(seen) == 6, f"rotation reaches only {sorted(seen)}"


def test_grade_overrides_stage_when_they_disagree():
    """
    term_for_week resolves the stage from grade when a grade is given —
    a K session must get the K-2 term list even if a stale grade_stage
    says otherwise.
    """
    term = term_for_week("K", GradeStage.independent)
    assert term["term_id"] in {"fides", "spes", "caritas"}
