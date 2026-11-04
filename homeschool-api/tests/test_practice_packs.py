"""Practice Coach subject packs beyond Latin: mathematics, spelling, and
short-answer recall (docs/PRACTICE_COACH.md, "Subject packs").

Each pack has a synthetic golden quiz in its own golden/ folder, written for
this repository. The properties pinned here are the ones a careless pack gets
wrong: a maths answer the pack computed wrongly, a practice problem that is
just the missed one again, a spelling word or a fact the page never gave, and
a reading the parent has not settled being diagnosed anyway.
"""
import copy
import json
import re
from fractions import Fraction
from pathlib import Path

import pytest

from models.practice import GradedAssessment
from routers import practice as practice_router
from services.practice import core_checks, pipeline
from services.practice.packs import _PACKS, available_packs, get_pack

PACKS = Path(__file__).resolve().parents[1] / "services/practice/packs"


def fixture(pack: str, name: str) -> dict:
    return json.loads((PACKS / pack / "golden" / f"{name}.expected.json").read_text(encoding="utf-8"))


GOLDENS = [
    ("math", "math_quiz_1"),
    ("spelling", "spelling_test_1"),
    ("recall", "history_quiz_1"),
    ("reading", "reading_quiz_1"),
]


def assessment(pack: str, name: str) -> GradedAssessment:
    return GradedAssessment.model_validate(copy.deepcopy(fixture(pack, name)["assessment"]))


# ── Every pack ────────────────────────────────────────────────────────────────

def test_the_picker_lists_school_subjects_each_checked_by_a_real_pack():
    subjects = available_packs()
    ids = [s["id"] for s in subjects]
    # The subjects a school or homeschool lists, including the four STAAR
    # tests in grades 3-8: mathematics, reading language arts, science and
    # social studies.
    assert {"mathematics", "reading", "spelling", "grammar", "science",
            "history", "geography", "latin"} <= set(ids)
    assert len(ids) == len(set(ids))
    for s in subjects:
        pack = get_pack(s["id"])
        assert pack is not None and pack.id == s["pack"]
    # Every registered pack is reachable from the picker.
    assert {s["pack"] for s in subjects} == set(_PACKS)
    # A pack id is still accepted, so older requests keep working.
    assert all(get_pack(pid).id == pid for pid in _PACKS)


def test_pages_are_read_under_the_subject_the_parent_chose():
    from services.practice.extract import _prompt

    assert "Subject: Science" in _prompt("science")
    assert "Subject: History and social studies" in _prompt("history")
    assert "Subject: Reading and language arts" in _prompt("reading")


@pytest.mark.parametrize("subject", ["science", "history", "grammar", "reading", "mathematics"])
def test_a_quiz_read_under_a_subject_is_diagnosed_by_that_subjects_pack(subject):
    pack = get_pack(subject)
    golden = {"math": ("math", "math_quiz_1"), "recall": ("recall", "history_quiz_1"),
              "reading": ("reading", "reading_quiz_1")}[pack.id]
    a = assessment(*golden)
    a.subject = subject
    got = {e.item_ref: e.category for e in pipeline.diagnose(a).errors
           if e.category.split(".")[0] == pack.id}
    expected = fixture(*golden)["expected_categories"]
    assert got == {ref: cat for ref, cat in expected.items() if cat.split(".")[0] == pack.id}
    assert got


@pytest.mark.parametrize("pack_id", sorted(_PACKS))
def test_every_category_has_a_remediation_strategy_and_detects_are_real(pack_id):
    pack = get_pack(pack_id)
    cats = pack.taxonomy["categories"]
    assert cats and all(c.get("remediation_strategy") for c in cats.values())
    assert set(pack.manifest["detects"]) <= set(cats)
    assert pack.extract_hints.strip()


@pytest.mark.parametrize("pack_id,name", GOLDENS)
def test_golden_quiz_is_diagnosed_as_expected(pack_id, name):
    expected = fixture(pack_id, name)["expected_categories"]
    diagnosis = pipeline.diagnose(assessment(pack_id, name))
    got = {e.item_ref: e.category for e in diagnosis.errors if e.category.startswith(pack_id + ".")}
    assert got == expected


@pytest.mark.parametrize("pack_id,name", GOLDENS)
def test_every_category_a_pack_emits_is_one_it_declares(pack_id, name):
    """The pipeline silently drops an unknown category; nothing should be dropped."""
    a = assessment(pack_id, name)
    pack = get_pack(pack_id)
    emitted = pack.classify_errors(a, None)
    assert emitted and all(pack.knows(e.category) for e in emitted)
    assert set(e.category for e in emitted) <= set(pack.manifest["detects"])


@pytest.mark.parametrize("pack_id,name", GOLDENS)
def test_an_unsettled_reading_is_never_diagnosed(pack_id, name):
    data = fixture(pack_id, name)["assessment"]
    for section in data["sections"]:
        for item in section["items"]:
            item["ask_parent"] = "unclear"
    a = GradedAssessment.model_validate(data)
    assert get_pack(pack_id).classify_errors(a, None) == []
    with pytest.raises(ValueError):
        pipeline.plan(pipeline.diagnose(a), a)


@pytest.mark.parametrize("pack_id,name", GOLDENS)
def test_only_patterns_the_child_can_act_on_reach_them(pack_id, name):
    """A miss the pack cannot explain is for the parent, never the child."""
    diagnosis = pipeline.diagnose(assessment(pack_id, name))
    for error in diagnosis.errors:
        if error.category.endswith((".unclassified", ".needs_answer")) or error.category.startswith("core."):
            assert error.audience == "parent_only", error


@pytest.mark.parametrize("pack_id,name", GOLDENS)
def test_every_pattern_found_gets_practice_within_the_limits(pack_id, name):
    a = assessment(pack_id, name)
    diagnosis = pipeline.diagnose(a)
    practice = pipeline.plan(diagnosis, a)
    assert practice is not None
    assert 1 <= len(practice.items) <= 12 and 1 <= practice.est_minutes <= 10
    actionable = {e.category for e in diagnosis.errors
                  if e.audience == "parent_and_child" and e.category.startswith(pack_id + ".")}
    assert actionable <= {i.target for i in practice.items}
    assert practice.recheck_schedule == ["+3d", "+7d"]


@pytest.mark.parametrize("pack_id,name", GOLDENS)
def test_the_demo_plans_every_new_pack_without_storing_anything(pack_id, name):
    import asyncio
    from models.practice import ConfirmAssessmentRequest

    demo = {"role": "demo_code", "code": "test"}
    planned = asyncio.run(practice_router.demo_plan_practice(
        ConfirmAssessmentRequest(assessment=assessment(pack_id, name)), auth=demo))
    assert planned["practice_set"]["items"]
    assert "by the teacher's marks" in planned["summary"]


# ── Mathematics ───────────────────────────────────────────────────────────────

def independent_value(prompt: str) -> Fraction:
    """Work a practice prompt out without the pack's own parser."""
    expr = prompt
    match = re.match(r"Write (\d+)/(\d+) in lowest terms\.", expr)
    if match:
        return Fraction(int(match.group(1)), int(match.group(2)))
    expr = expr.rstrip("= ").replace("−", "-").replace("×", "*").replace("÷", "/")
    expr = re.sub(r"(\d+)/(\d+)", r"Fraction(\1, \2)", expr)
    expr = re.sub(r"(\d+\.\d+)", r"Fraction('\1')", expr)
    return eval(expr, {"Fraction": Fraction, "__builtins__": {}})  # noqa: S307 - test-only, fixed grammar


def value_of(answer: str) -> Fraction:
    answer = answer.split(" (=")[0]
    return Fraction(answer)


def test_every_maths_practice_answer_is_arithmetically_right():
    a = assessment("math", "math_quiz_1")
    practice = pipeline.plan(pipeline.diagnose(a), a)
    for item in practice.items:
        assert value_of(item.expected_answer) == independent_value(item.prompt), item


def test_maths_practice_never_repeats_a_problem_from_the_page():
    a = assessment("math", "math_quiz_1")
    on_page = {re.sub(r"\s", "", i.prompt) for s in a.sections for i in s.items}
    practice = pipeline.plan(pipeline.diagnose(a), a)
    assert not on_page & {re.sub(r"\s", "", i.prompt) for i in practice.items}


def test_a_problem_already_on_the_page_is_never_generated_as_practice():
    """Force the collision: put the problems a plan generates onto the page,
    plan again with the same seeds, and none of them may come back."""
    data = fixture("math", "math_quiz_1")["assessment"]
    first = pipeline.plan(pipeline.diagnose(GradedAssessment.model_validate(data)), GradedAssessment.model_validate(data))
    data["sections"].append({"label": "Extra", "items": [
        {"number": n, "prompt": item.prompt, "student_response": item.expected_answer.split(" (=")[0], "teacher_mark": "correct"}
        for n, item in enumerate(first.items, 1)
    ]})
    a = GradedAssessment.model_validate(data)
    second = pipeline.plan(pipeline.diagnose(a), a)
    assert not {i.prompt for i in first.items} & {i.prompt for i in second.items}


def test_maths_practice_has_the_same_shape_as_the_miss():
    from services.practice.packs.math import binary, needs_borrow, needs_carry

    a = assessment("math", "math_quiz_1")
    practice = pipeline.plan(pipeline.diagnose(a), a)
    for item in practice.items:
        problem = binary(item.prompt)
        if item.target == "math.add.no_regroup":
            assert needs_carry(int(problem.av), int(problem.bv)), item.prompt
        if item.target == "math.sub.smaller_from_larger":
            assert needs_borrow(int(problem.av), int(problem.bv)), item.prompt
        if item.target == "math.mult.place_value_shift":
            assert problem.op == "*" and problem.bv >= 10, item.prompt


def test_a_teachers_correction_that_disagrees_is_sent_to_the_parent():
    data = fixture("math", "math_quiz_1")["assessment"]
    data["sections"][0]["items"][0]["teacher_correction"] = "43"  # 27 + 15 is 42
    a = GradedAssessment.model_validate(data)
    errors = [e for e in pipeline.diagnose(a).errors if e.item_ref == "Part A #1"]
    assert [(e.category, e.audience) for e in errors] == [("math.unclassified", "parent_only")]


def test_a_correct_mixed_number_is_not_called_unsimplified():
    data = {"subject": "math", "sections": [{"label": "A", "items": [
        {"number": 1, "prompt": "1 + 1/2 =", "student_response": "1 1/2", "teacher_mark": "incorrect", "teacher_correction": "3/2"},
    ]}]}
    errors = pipeline.diagnose(GradedAssessment.model_validate(data)).errors
    assert [e.category for e in errors] == ["math.unclassified"]


def test_maths_strengths_name_a_family_only_when_all_of_it_was_right():
    data = {"subject": "math", "sections": [{"label": "A", "items": [
        {"number": 1, "prompt": "34 + 12 =", "student_response": "46", "teacher_mark": "correct"},
        {"number": 2, "prompt": "45 + 21 =", "student_response": "66", "teacher_mark": "correct"},
        {"number": 3, "prompt": "7 × 8 =", "student_response": "56", "teacher_mark": "correct"},
        {"number": 4, "prompt": "6 × 7 =", "student_response": "41", "teacher_mark": "incorrect", "teacher_correction": "42"},
    ]}]}
    strengths = {s.category for s in pipeline.diagnose(GradedAssessment.model_validate(data)).strengths}
    assert strengths == {"math.addition"}


# ── Spelling ──────────────────────────────────────────────────────────────────

def test_spelling_practises_the_missed_word_and_same_pattern_words_not_on_the_page():
    data = fixture("spelling", "spelling_test_1")["assessment"]
    data["sections"][0]["items"] = data["sections"][0]["items"][1:4]
    a = GradedAssessment.model_validate(data)
    practice = pipeline.plan(pipeline.diagnose(a), a)
    answers = [i.expected_answer for i in practice.items]
    for missed in ("friend", "receive", "running"):
        assert missed in answers
    bank = json.loads((PACKS / "spelling/item_bank/patterns.json").read_text(encoding="utf-8"))
    extras = [i for i in practice.items if i.prompt.startswith("Same pattern")]
    assert extras
    for item in extras:
        assert item.expected_answer in bank[item.target]
        assert item.expected_answer not in {"firend", "friend", "recieve", "receive", "runing", "running"}


def test_spelling_without_a_correction_on_the_page_goes_to_the_parent():
    data = {"subject": "spelling", "sections": [{"label": "A", "items": [
        {"number": 1, "prompt": "Word 1", "student_response": "becuz", "teacher_mark": "incorrect"},
    ]}]}
    a = GradedAssessment.model_validate(data)
    errors = pipeline.diagnose(a).errors
    assert [(e.category, e.audience) for e in errors] == [("spelling.unclassified", "parent_only")]
    assert pipeline.plan(pipeline.diagnose(a), a) is None


# ── Short-answer recall ───────────────────────────────────────────────────────

def test_recall_practice_never_supplies_an_answer_the_page_did_not():
    a = assessment("recall", "history_quiz_1")
    on_page = {(i.prompt, (i.teacher_correction or i.student_response or "").strip())
               for s in a.sections for i in s.items}
    practice = pipeline.plan(pipeline.diagnose(a), a)
    for item in practice.items:
        assert (item.prompt, item.expected_answer) in on_page, item


def test_recall_without_a_correction_is_not_practised():
    a = assessment("recall", "history_quiz_1")
    practice = pipeline.plan(pipeline.diagnose(a), a)
    assert "What did Egyptians make paper from?" not in {i.prompt for i in practice.items}


# ── Review findings (each reproduced before the fix) ─────────────────────────

def _one(subject: str, **item) -> GradedAssessment:
    return GradedAssessment.model_validate({"subject": subject, "sections": [{"label": "A", "items": [
        {"number": 1, "prompt": "Q", **item}]}]})


def test_a_long_answer_never_breaks_diagnosis_or_planning():
    long_answer, long_fix = "x" * 190, "y" * 190
    for subject in ("recall", "spelling"):
        a = _one(subject, student_response=long_answer, teacher_mark="incorrect", teacher_correction=long_fix)
        diagnosis = pipeline.diagnose(a)
        assert all(len(e.evidence) <= 300 for e in diagnosis.errors)
        pipeline.plan(diagnosis, a)
    a = _one("spelling", prompt="We went " + "very " * 55 + "___ yesterday.",
             student_response="there", teacher_mark="incorrect", teacher_correction="their")
    pipeline.plan(pipeline.diagnose(a), a)


def test_an_answer_starting_with_a_is_not_a_multiple_choice_letter():
    a = _one("recall", prompt="What is a whale?", student_response="a fish",
             teacher_mark="incorrect", teacher_correction="a mammal")
    assert [e.category for e in pipeline.diagnose(a).errors] == ["recall.fact"]
    practice = pipeline.plan(pipeline.diagnose(a), a)
    assert "option" not in practice.items[0].hint


def test_spelling_ignores_punctuation_and_finds_the_word_in_a_sentence():
    a = _one("spelling", student_response="there.", teacher_mark="incorrect", teacher_correction="their")
    assert [e.category for e in pipeline.diagnose(a).errors] == ["spelling.homophone"]
    a = _one("spelling", student_response="We went to the libary today.", teacher_mark="incorrect", teacher_correction="library")
    assert [e.category for e in pipeline.diagnose(a).errors] == ["spelling.omitted_letter"]


def test_a_correction_with_context_targets_its_first_word_and_keeps_capitals():
    a = _one("spelling", student_response="there", teacher_mark="incorrect", teacher_correction="their (not there)")
    assert [e.category for e in pipeline.diagnose(a).errors] == ["spelling.homophone"]
    a = _one("spelling", student_response="Febuary", teacher_mark="incorrect", teacher_correction="February")
    practice = pipeline.plan(pipeline.diagnose(a), a)
    assert practice.items[0].expected_answer == "February"


def test_a_division_remainder_is_not_called_a_forgotten_fact():
    a = _one("math", prompt="12 ÷ 5 =", student_response="2", teacher_mark="incorrect", teacher_correction="2 2/5")
    assert [e.category for e in pipeline.diagnose(a).errors] == ["math.unclassified"]


def test_a_sign_slip_with_a_bracketed_negative_is_diagnosed():
    a = _one("math", prompt="−5 × (−3) =", student_response="-15", teacher_mark="incorrect", teacher_correction="15")
    assert [e.category for e in pipeline.diagnose(a).errors] == ["math.integer.sign"]


# ── Reading and language arts ─────────────────────────────────────────────────

def test_a_question_that_asks_for_judgement_never_reaches_the_child():
    a = assessment("reading", "reading_quiz_1")
    diagnosis = pipeline.diagnose(a)
    judged = [e for e in diagnosis.errors if e.category == "reading.needs_judgement"]
    assert judged and all(e.audience == "parent_only" for e in judged)
    from services.practice.packs.reading import generate_practice
    planned = generate_practice(diagnosis, a)
    assert "Why did Father decide to wait until morning?" not in [i.prompt for i in planned.items]


def test_a_long_written_answer_is_never_auto_marked():
    a = _one("reading", prompt="What happened at the river?",
             student_response="they waited by the river all night because Father said the ice was not safe yet",
             teacher_mark="partial", teacher_correction="they waited for morning")
    assert [e.category for e in pipeline.diagnose(a).errors] == ["reading.needs_judgement"]


def test_a_multiple_choice_main_idea_question_is_checked_against_the_marked_answer():
    a = assessment("reading", "reading_quiz_1")
    cats = {e.item_ref: e.category for e in pipeline.diagnose(a).errors}
    assert cats["The Long Winter Road #9"] == "reading.choice"


def test_reading_practice_never_supplies_an_answer_the_page_did_not():
    from services.practice.packs.reading import generate_practice

    a = assessment("reading", "reading_quiz_1")
    planned = generate_practice(pipeline.diagnose(a), a)
    on_page = {i.teacher_correction for s in a.sections for i in s.items if i.teacher_correction}
    on_page |= {i.student_response for s in a.sections for i in s.items
                if i.teacher_mark == "correct" and i.student_response}
    assert planned.items and all(i.expected_answer in on_page for i in planned.items)
