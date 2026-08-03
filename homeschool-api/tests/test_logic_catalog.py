"""
Logic & Clear Thinking (Subject.logic, services/logic_catalog.py).

Two things are pinned here that no other subject needs:

1. **The K-2 gate**, at every level it exists. Logic is the app's first
   stage-gated SUBJECT (phonics is a stage-gated NOTE inside language_arts,
   which is not the same thing), and it is gated in three independent
   places — the config validator, the catalog renderer, and the UI. Two of
   those are testable here; the third is asserted in
   tests/test_catalog_coverage.py via the absent year-1/2 plans.

2. **The charity guardrails.** This is the one subject where teaching the
   material well and forming the child well can pull against each other: a
   student newly able to name a fallacy has been handed a weapon, and the
   obvious first target is their own parents. Those guardrails live in
   prompt text, so they are asserted against the rendered block.

As always, no test here can verify what the live model does with the
prompt — only that the guardrail text is present to be followed.
"""

import pytest

from models.schemas import (
    SUBJECT_DURATIONS,
    SUBJECT_LABELS,
    GradeStage,
    SessionConfig,
    Subject,
)
from services import logic_catalog
from services.logic_catalog import item_for_week, logic_note


TAUGHT_STAGES = [GradeStage.core_mastery, GradeStage.independent]


def _flat(text: str) -> str:
    """Collapse the prompt block's hard wrapping so a multi-word assertion
    isn't defeated by wherever a line happened to break."""
    return " ".join(text.split()).lower()



# ── Wiring ───────────────────────────────────────────────────────────────

def test_subject_is_fully_registered():
    assert Subject.logic in SUBJECT_DURATIONS
    assert SUBJECT_LABELS[Subject.logic] == "Logic & Clear Thinking"


def test_subject_has_a_context_blurb():
    from services.ai_service import _SUBJECT_CONTEXT

    assert Subject.logic in _SUBJECT_CONTEXT


def test_logic_has_a_catalog_block_but_is_not_a_classical_language():
    """
    The two mappings in services/ai_service.py are deliberately different
    sets. Logic renders a weekly catalog block like Latin and Greek do, but
    it must NOT pick up the Bible-translation note or the language-evidence
    gate, both of which are keyed off _CLASSICAL_LANGUAGE_SUBJECTS. If a
    future edit collapses the two mappings into one, this fails.
    """
    from services.ai_service import _CATALOG_NOTE_SUBJECTS, _CLASSICAL_LANGUAGE_SUBJECTS

    assert Subject.logic in _CATALOG_NOTE_SUBJECTS
    assert Subject.logic not in _CLASSICAL_LANGUAGE_SUBJECTS


def test_bible_translation_note_does_not_reach_logic():
    """The concrete consequence of the mapping split above."""
    from services.ai_service import _bible_translation_note

    config = SessionConfig(
        student_name="Ada", grade="7", grade_stage=GradeStage.independent,
        subjects=[Subject.logic], bible_translation="ESV",
    )
    assert _bible_translation_note(config, Subject.logic) == ""
    # ...and still reaches the subjects it should, so this isn't vacuous.
    assert _bible_translation_note(config, Subject.scripture) != ""


# ── The K-2 gate ─────────────────────────────────────────────────────────

def test_catalog_renders_nothing_for_k2():
    assert logic_note("K", GradeStage.foundations) == ""
    assert logic_note(None, GradeStage.foundations) == ""
    assert item_for_week(None, GradeStage.foundations) is None


def test_config_validator_drops_logic_for_a_k2_student():
    """
    The server-side half of the gate. A hand-rolled request, or a saved
    config from before a student's stage was corrected downward, would sail
    past both the UI and the catalog renderer.
    """
    config = SessionConfig(
        student_name="Wren", grade="1", grade_stage=GradeStage.foundations,
        subjects=[Subject.morning_time, Subject.logic, Subject.mathematics],
    )
    assert Subject.logic not in config.subjects
    # Everything else survives untouched — this drops one subject, not the list.
    assert config.subjects == [Subject.morning_time, Subject.mathematics]


@pytest.mark.parametrize("stage", TAUGHT_STAGES)
def test_config_validator_keeps_logic_for_older_students(stage):
    config = SessionConfig(
        student_name="Ada", grade="6", grade_stage=stage,
        subjects=[Subject.logic],
    )
    assert config.subjects == [Subject.logic]


def test_dropping_logic_also_drops_its_orphaned_resume_note():
    """
    _validate_logic_stage runs BEFORE _validate_lesson_resume precisely so
    a resume note attached to the dropped subject is filtered in the same
    pass rather than surviving as an orphan pointing at a subject the
    child isn't doing.
    """
    config = SessionConfig(
        student_name="Wren", grade="K", grade_stage=GradeStage.foundations,
        subjects=[Subject.morning_time, Subject.logic],
        lesson_resume=[{"subject": "logic", "stopped_at": "syllogisms"}],
    )
    assert Subject.logic not in config.subjects
    assert config.lesson_resume == []


# ── Content renders for the stages that do teach it ──────────────────────

@pytest.mark.parametrize("stage", TAUGHT_STAGES)
def test_note_renders_for_taught_stages(stage):
    note = logic_note(None, stage)
    assert "<logic_and_clear_thinking>" in note
    assert "</logic_and_clear_thinking>" in note


def test_3_to_5_is_informal_only():
    """
    No fallacy names and no syllogisms are TAUGHT before 6-8 — the whole
    point of the stage split.

    Asserted on what the block actually teaches (the rendered item), not on
    whether the word "syllogism" appears anywhere: the 3-5 block correctly
    mentions syllogisms twice, both times to forbid them ("no syllogisms",
    "do not invent new syllogisms"). A bare substring check fails on the
    prohibition that makes the rule work, which is the opposite of what
    this test is for.
    """
    from datetime import date, timedelta

    start = date(2026, 1, 5)
    for week in range(12):
        day = start + timedelta(weeks=week)
        item = item_for_week(None, GradeStage.core_mastery, today=day)
        assert "move_id" in item, f"week {week} taught a formal item at 3-5: {item}"
        note = logic_note(None, GradeStage.core_mastery, today=day)
        assert "THIS WEEK'S MOVE" in note
        assert "THIS WEEK'S FALLACY" not in note
        assert "THIS WEEK'S ARGUMENT" not in note


def test_6_to_8_reaches_both_fallacies_and_syllogisms():
    from datetime import date, timedelta

    start = date(2026, 1, 5)
    rendered = [
        logic_note(None, GradeStage.independent, today=start + timedelta(weeks=w))
        for w in range(20)
    ]
    assert any("THIS WEEK'S FALLACY" in n for n in rendered)
    assert any("THIS WEEK'S ARGUMENT" in n for n in rendered)


def test_rotation_reaches_every_item():
    """An item no week lands on would never be taught."""
    from datetime import date, timedelta

    start = date(2026, 1, 5)
    for stage in TAUGHT_STAGES:
        expected = len(logic_catalog._items_for(stage))
        seen = set()
        for week in range(expected * 2):
            item = item_for_week(None, stage, today=start + timedelta(weeks=week))
            seen.add(item.get("move_id") or item.get("fallacy_id") or item.get("syllogism_id"))
        assert len(seen) == expected, f"{stage} rotation reaches {len(seen)} of {expected}"


# ── The charity guardrails ───────────────────────────────────────────────

@pytest.mark.parametrize("stage", TAUGHT_STAGES)
def test_block_says_logic_is_not_for_winning(stage):
    note = logic_note(None, stage).lower()
    assert "never for winning" in note or "never for winning against" in note


@pytest.mark.parametrize("stage", TAUGHT_STAGES)
def test_block_protects_the_parents_own_authority(stage):
    """
    The specific failure this subject invites: a child using new tools to
    litigate their parents' instructions. Bede must redirect, never coach.
    """
    note = logic_note(None, stage).lower()
    assert "never coach" in note
    assert "parents" in note


@pytest.mark.parametrize("stage", TAUGHT_STAGES)
def test_block_refuses_to_rule_on_contested_disputes(stage):
    """
    A logic subject is an invitation to ask Bede to adjudicate live
    political and religious arguments. Same boundary the faith modules keep.
    """
    note = _flat(logic_note(None, stage))
    assert "do not rule on political, moral, or religious questions" in note
    assert any(w in note for w in ("pastor", "priest", "minister"))


@pytest.mark.parametrize("stage", TAUGHT_STAGES)
def test_block_forbids_improvised_arguments(stage):
    """
    The same verbatim discipline as the language catalogs, and for a
    sharper reason: a model asked to invent a syllogism will sometimes
    produce an invalid one and label it valid, which is precisely the error
    the student is not yet able to catch.
    """
    note = logic_note(None, stage).lower()
    assert "do not invent" in note


@pytest.mark.parametrize("stage", TAUGHT_STAGES)
def test_block_makes_the_student_judge_first(stage):
    note = logic_note(None, stage).lower()
    assert "judge" in note


# ── The fixed arguments are actually correct ─────────────────────────────

def test_every_syllogism_carries_an_explicit_verdict():
    for s in logic_catalog._SYLLOGISMS:
        assert s["verdict"] in {"valid", "invalid", "valid form, false premise"}, (
            f"{s['syllogism_id']} has an unrecognized verdict {s['verdict']!r}"
        )
        assert s["why"], f"{s['syllogism_id']} has no explanation"


def test_the_two_classic_invalid_forms_are_labelled_invalid():
    """
    Affirming the consequent and denying the antecedent are the two
    mistakes the subject exists to inoculate against. Mislabelling either
    would teach the exact error being taught against.
    """
    by_id = {s["syllogism_id"]: s for s in logic_catalog._SYLLOGISMS}
    assert by_id["affirming_consequent"]["verdict"] == "invalid"
    assert by_id["denying_antecedent"]["verdict"] == "invalid"


def test_the_valid_but_false_case_exists_and_is_labelled_honestly():
    """
    The single most important example in the subject: valid form, false
    premise, false conclusion. A student who never meets it will think
    'valid' and 'true' are the same word.
    """
    by_id = {s["syllogism_id"]: s for s in logic_catalog._SYLLOGISMS}
    entry = by_id["valid_but_false"]
    assert entry["verdict"] == "valid form, false premise"
    assert "valid does not mean true" in entry["why"].lower()


def test_every_fallacy_has_a_neutral_worked_example():
    """
    Examples are deliberately dull — weather, animals, chores, homework.
    An example with real stakes teaches the stakes rather than the form,
    and a family-shaped example teaches a child to audit their parents.
    """
    charged = ("politic", "vote", "election", "abortion", "church teaches", "denomination", "my mom", "my dad")
    for f in logic_catalog._FALLACIES:
        assert f["example"], f"{f['fallacy_id']} has no example"
        assert f["why_it_fails"], f"{f['fallacy_id']} has no explanation"
        lowered = f["example"].lower()
        for word in charged:
            assert word not in lowered, (
                f"{f['fallacy_id']}'s example reaches for charged material ({word!r}) — "
                f"examples in this subject are deliberately dull"
            )


# ── Declining to rule is not the same as calling a matter unsettled ──────

@pytest.mark.parametrize("stage", TAUGHT_STAGES)
def test_block_does_not_present_settled_moral_questions_as_open(stage):
    """
    A defect caught after this subject first shipped. The block used to
    lump *moral* in with political and religious and tell Bede to say
    "thoughtful people disagree" — so a student bringing a question their
    own church considers settled would have been told the landscape was
    open. That is not neutrality; it is a substantive claim, and one this
    app has no standing to make on a family's behalf. Declining to
    adjudicate is right. Characterizing the moral landscape is not the
    same thing, and the two had been conflated.
    """
    note = _flat(logic_note(None, stage))
    assert "declining to rule is not the same as saying the matter is unsettled" in note
    assert "they teach something definite about it" in note
    # The old INSTRUCTION must be gone. Asserted on the instruction rather
    # than on the bare phrase, because the block now quotes "thoughtful
    # people disagree, so it's open" precisely in order to forbid it — a
    # substring check would fail on the fix itself, the same trap
    # test_3_to_5_is_informal_only documents for the word "syllogism".
    assert "say honestly that thoughtful people disagree and that the question belongs" not in note


@pytest.mark.parametrize("stage", TAUGHT_STAGES)
def test_political_and_moral_questions_are_treated_differently(stage):
    """
    Reasonable people genuinely do differ on political questions, and Bede
    may say so. A moral or religious conviction of the family's is not the
    same kind of object, and Bede must not describe that landscape at all.
    """
    note = _flat(logic_note(None, stage))
    assert "on a political question, reasonable" in note
    assert "do not characterize the landscape" in note


@pytest.mark.parametrize("stage", TAUGHT_STAGES)
def test_a_bad_argument_for_a_true_claim_is_still_addressed(stage):
    """The lesson that keeps fallacy-spotting from becoming nihilism."""
    note = _flat(logic_note(None, stage))
    assert "a bad argument for a true claim is still a bad argument" in note
