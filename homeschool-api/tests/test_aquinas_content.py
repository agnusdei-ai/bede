"""
St. Thomas Aquinas in Saints & Catechism and Logic (docs/DECISIONS.md entry 47).

What is pinned here:
- the Saints block reaches a real Saints prompt, and only that subject's;
- each stage gets its own picture, and K-2 is never told it is a proof;
- his feast week promotes the story, and a parent's note still wins;
- nothing claims to be Aquinas's own words, and every block names the source;
- the Logic Summa item teaches form with no verdict, and the 3-5 move stays dull.

As with every prompt test here, none of this verifies what the live model does
with the text, only that the text is there to be followed.
"""
from datetime import date

import pytest

from models.schemas import GradeStage, SessionConfig, Subject
from services import aquinas_catalog, logic_catalog
from services.ai_service import _CATALOG_NOTE_SUBJECTS, _CLASSICAL_LANGUAGE_SUBJECTS, _build_subject_prompt

FEAST_WEEK_DAY = date(2027, 1, 27)   # the Wednesday of the week holding 28 January 2027
ORDINARY_DAY = date(2027, 3, 10)


def _flat(text: str) -> str:
    return " ".join(text.split()).lower()


def _config(grade="4", stage=GradeStage.core_mastery, **changes):
    base = dict(student_name="Ada", grade=grade, grade_stage=stage, subjects=[Subject.saints, Subject.logic])
    base.update(changes)
    return SessionConfig(**base)


# ── Wiring ───────────────────────────────────────────────────────────────

def test_saints_has_the_aquinas_block_and_is_not_a_language():
    assert _CATALOG_NOTE_SUBJECTS[Subject.saints] is aquinas_catalog.saints_note
    assert Subject.saints not in _CLASSICAL_LANGUAGE_SUBJECTS


@pytest.mark.asyncio
async def test_a_real_saints_prompt_carries_the_block():
    prompt = await _build_subject_prompt(_config(), Subject.saints, local_date=ORDINARY_DAY)
    assert "<saint_thomas_aquinas>" in prompt
    assert "Roccasecca" in prompt


@pytest.mark.asyncio
async def test_other_subjects_do_not_get_it():
    prompt = await _build_subject_prompt(_config(), Subject.scripture, local_date=FEAST_WEEK_DAY)
    assert "<saint_thomas_aquinas>" not in prompt


# ── Stages ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("stage,marker", [
    (GradeStage.foundations, "WONDER, NOT PROOF"),
    (GradeStage.core_mastery, "THE DOMINO CHAIN"),
    (GradeStage.independent, "THE FIVE WAYS"),
])
def test_each_stage_gets_its_own_picture(stage, marker):
    note = aquinas_catalog.saints_note(None, stage, today=ORDINARY_DAY)
    assert marker in note
    for other in {"WONDER, NOT PROOF", "THE DOMINO CHAIN", "THE FIVE WAYS"} - {marker}:
        assert other not in note


def test_k2_is_never_told_it_is_a_proof():
    note = _flat(aquinas_catalog.saints_note(None, GradeStage.foundations, today=ORDINARY_DAY))
    assert "never call this a proof to a child this age" in note
    assert "never quiz them" in note


def test_the_common_misreading_is_corrected_at_6_to_8():
    note = _flat(aquinas_catalog.saints_note(None, GradeStage.independent, today=ORDINARY_DAY))
    assert "not \"everything has a cause\"" in note


@pytest.mark.parametrize("grade", ["9", "12"])
def test_upper_grades_get_the_independent_picture(grade):
    assert "THE FIVE WAYS" in aquinas_catalog.saints_note(grade, GradeStage.independent, today=ORDINARY_DAY)


# ── Feast week ───────────────────────────────────────────────────────────

def test_feast_week_opens_with_his_story_and_the_parent_still_wins():
    note = _flat(aquinas_catalog.saints_note(None, GradeStage.core_mastery, today=FEAST_WEEK_DAY))
    assert "this week is his feast" in note
    assert "parent's own lesson note for today points somewhere else, which always wins" in note


def test_outside_feast_week_bede_does_not_steer_to_him():
    note = _flat(aquinas_catalog.saints_note(None, GradeStage.core_mastery, today=ORDINARY_DAY))
    assert "this week is his feast" not in note
    assert "do not steer a lesson to him on your own" in note


@pytest.mark.parametrize("day,expected", [
    (date(2027, 1, 25), True),   # Monday of the feast week
    (date(2027, 1, 31), True),   # Sunday of the feast week
    (date(2027, 1, 24), False),  # the Sunday before
    (date(2027, 2, 1), False),   # the Monday after
])
def test_feast_week_bounds(day, expected):
    assert aquinas_catalog._in_feast_week(day) is expected


# ── Honesty about the source ─────────────────────────────────────────────

@pytest.mark.parametrize("stage", list(GradeStage))
def test_the_saints_block_never_claims_to_quote_the_summa(stage):
    note = _flat(aquinas_catalog.saints_note(None, stage, today=ORDINARY_DAY))
    assert "not aquinas's own words" in note
    assert "never quote the summa from memory" in note
    assert aquinas_catalog.REFERENCE.lower() in note


def test_life_facts_say_less_where_sources_disagree():
    life = aquinas_catalog.LIFE
    assert "about 1225" in life
    assert "a long time" in life
    assert "28 January" in life
    assert len(aquinas_catalog.SOURCES) >= 3


# ── Logic ────────────────────────────────────────────────────────────────

def _summa_note():
    item = logic_catalog._SUMMA_ARTICLES[0]
    return _flat(logic_catalog._render_item(item))


def test_summa_item_is_6_to_8_only():
    assert logic_catalog._SUMMA_ARTICLES[0] in logic_catalog._items_for(GradeStage.independent)
    assert logic_catalog._SUMMA_ARTICLES[0] not in logic_catalog._items_for(GradeStage.core_mastery)
    assert logic_catalog._items_for(GradeStage.foundations) == []


def test_summa_item_has_all_five_parts_in_order():
    names = [name for name, _ in logic_catalog._SUMMA_ARTICLES[0]["parts"]]
    assert names == ["The question", "Objections", "On the contrary", "I answer that", "Replies to the objections"]


def test_summa_item_teaches_form_and_gives_no_verdict():
    note = _summa_note()
    assert "the lesson is the form" in note
    assert "do not give a verdict of your own" in note
    assert "do not set the student to hunt for its flaws" in note
    assert "do not present the question as open" in note
    assert "pastor, priest, or minister" in note
    assert "verdict: " not in note


def test_summa_item_never_claims_to_quote():
    note = _summa_note()
    assert "not aquinas's own words" in note
    assert "never quote the summa from memory" in note


def test_summa_item_is_reached_by_the_6_to_8_rotation():
    from datetime import timedelta

    start = date(2026, 1, 5)
    weeks = len(logic_catalog._items_for(GradeStage.independent))
    rendered = [
        logic_catalog.logic_note(None, GradeStage.independent, today=start + timedelta(weeks=w))
        for w in range(weeks)
    ]
    assert any("THIS WEEK'S SUMMA ARTICLE" in n for n in rendered)


def test_the_3_to_5_move_is_the_habit_with_a_dull_example():
    move = next(m for m in logic_catalog._MOVES if m["move_id"] == "best_reason_against")
    assert "Aquinas" in move["why"]
    example = move["example"].lower()
    for charged in ("god", "church", "pray", "bible", "mom", "dad"):
        assert charged not in example
