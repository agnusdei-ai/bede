"""Picture problems: diagrams Bede draws, checks and varies (services/practice/diagrams.py)."""
from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from models.practice import Diagram, GenerateQuizRequest, GradedAssessment
from services.practice import diagrams, extract, generate
from services.practice.packs import math as math_pack

D = TypeAdapter(Diagram)


def d(**kw):
    return D.validate_python(kw)


# ── The vocabulary is closed ──────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    {"kind": "svg", "markup": "<svg onload=alert(1)>"},
    {"kind": "fraction_bar", "parts": 4, "shaded": 5},
    {"kind": "clock", "hour": 13, "minute": 0},
    {"kind": "number_line", "start": 10, "end": 2},
    {"kind": "array", "rows": 3, "cols": 4, "html": "<b>x</b>"},
    {"kind": "bar_graph", "bars": [{"label": "x" * 40, "value": 3}]},
])
def test_anything_outside_the_vocabulary_is_refused(raw):
    with pytest.raises(ValidationError):
        D.validate_python(raw)
    assert diagrams.parse(raw) is None


# ── Answers are worked out from the picture ───────────────────────────────────

@pytest.mark.parametrize("diagram, prompt, right", [
    ({"kind": "fraction_bar", "parts": 4, "shaded": 3}, "What fraction is shaded?", "3/4"),
    ({"kind": "fraction_circle", "parts": 8, "shaded": 3}, "What fraction is not shaded?", "5/8"),
    ({"kind": "array", "rows": 3, "cols": 4}, "How many dots?", "12"),
    ({"kind": "base_ten", "hundreds": 2, "tens": 3, "ones": 4}, "What number?", "234"),
    ({"kind": "clock", "hour": 3, "minute": 15}, "What time is it?", "3:15"),
    ({"kind": "rectangle", "width": 5, "height": 3}, "Find the area.", "15"),
    ({"kind": "rectangle", "width": 5, "height": 3}, "Find the perimeter.", "16"),
    ({"kind": "right_triangle", "base": 6, "height": 4}, "What is the area of the triangle?", "12"),
    ({"kind": "number_line", "start": 0, "end": 10, "step": 2, "marks": [4, 8], "mark_labels": ["A", "B"]},
     "What number is at B?", "8"),
    ({"kind": "coordinate_plane", "points": [{"label": "A", "x": 3, "y": 2}]}, "Where is A?", "(3, 2)"),
])
def test_the_answer_is_counted_off_the_picture(diagram, prompt, right):
    picture = d(**diagram)
    assert diagrams.answer(picture, prompt) == right
    assert diagrams.same(picture, right, right)


def test_a_question_the_picture_cannot_settle_has_no_answer():
    graph = d(kind="bar_graph", bars=[{"label": "cats", "value": 4}, {"label": "dogs", "value": 6}])
    assert diagrams.answer(graph, "How many more dogs than cats?") is None
    assert diagrams.answer(d(kind="rectangle", width=4, height=2), "Draw it bigger.") is None


def test_equivalent_answers_match():
    assert diagrams.same(d(kind="fraction_bar", parts=4, shaded=2), "1/2", "2/4")
    assert diagrams.same(d(kind="clock", hour=3, minute=0), "3 o'clock", "3:00")
    assert diagrams.same(d(kind="clock", hour=3, minute=0), "15:00", "3:00")
    assert not diagrams.same(d(kind="coordinate_plane", points=[{"label": "A", "x": 3, "y": 2}]), "(2, 3)", "(3, 2)")


# ── Slips a parent can check against the picture ─────────────────────────────

@pytest.mark.parametrize("diagram, prompt, given, phrase", [
    ({"kind": "fraction_bar", "parts": 4, "shaded": 3}, "What fraction is shaded?", "3/1", "unshaded"),
    ({"kind": "fraction_bar", "parts": 4, "shaded": 3}, "What fraction is shaded?", "1/4", "not shaded"),
    ({"kind": "fraction_bar", "parts": 4, "shaded": 3}, "What fraction is shaded?", "4/3", "upside down"),
    ({"kind": "clock", "hour": 3, "minute": 0}, "What time?", "12:15", "other way round"),
    ({"kind": "clock", "hour": 2, "minute": 45}, "What time?", "3:45", "next hour"),
    ({"kind": "array", "rows": 3, "cols": 4}, "How many?", "7", "added the rows"),
    ({"kind": "base_ten", "hundreds": 2, "tens": 3, "ones": 4}, "What number?", "9", "counted the blocks"),
    ({"kind": "base_ten", "hundreds": 2, "tens": 3, "ones": 4}, "What number?", "243", "wrong place"),
    ({"kind": "rectangle", "width": 5, "height": 3}, "Find the area.", "16", "perimeter"),
    ({"kind": "rectangle", "width": 5, "height": 3}, "Find the perimeter.", "15", "area instead"),
    ({"kind": "right_triangle", "base": 6, "height": 4}, "Area?", "24", "halve"),
    ({"kind": "number_line", "start": 0, "end": 10, "step": 2, "marks": [6], "mark_labels": ["A"]}, "A?", "4", "one step"),
    ({"kind": "coordinate_plane", "points": [{"label": "A", "x": 3, "y": 2}]}, "A?", "(2, 3)", "x (across) comes first"),
])
def test_known_slips_are_named(diagram, prompt, given, phrase):
    assert phrase in diagrams.explain(d(**diagram), prompt, given)


def test_an_unexplained_miss_is_not_guessed_at():
    assert diagrams.explain(d(kind="array", rows=3, cols=4), "How many?", "40") == ""


# ── The maths pack: diagnosis and drawn practice ──────────────────────────────

def _quiz(*items):
    return GradedAssessment.model_validate({"subject": "math", "sections": [{"label": "Pictures", "items": [
        {"number": n, "confidence": 1, **item} for n, item in enumerate(items, 1)]}]})


def test_a_picture_miss_is_diagnosed_and_practised_with_new_pictures():
    bar = {"kind": "fraction_bar", "parts": 4, "shaded": 3}
    quiz = _quiz(
        {"prompt": "What fraction is shaded?", "diagram": bar, "student_response": "3/1",
         "teacher_mark": "incorrect", "teacher_correction": "3/4"},
        {"prompt": "What time is it?", "diagram": {"kind": "clock", "hour": 3, "minute": 0},
         "student_response": "12:15", "teacher_mark": "incorrect"},
    )
    errors = math_pack.classify_errors(quiz)
    assert [e.category for e in errors] == ["math.diagram.fraction_model", "math.diagram.clock"]
    assert all(e.audience == "parent_and_child" for e in errors)
    from models.practice import Diagnosis

    practice = math_pack.generate_practice(Diagnosis(errors=errors), quiz)
    assert practice is not None
    pictured = [i for i in practice.items if i.diagram is not None]
    assert len(pictured) == len(practice.items) >= 2
    for item in practice.items:
        # Every expected answer is counted off the picture the child will see.
        assert diagrams.answer(item.diagram, item.prompt) == item.expected_answer
        assert item.diagram.model_dump() != bar  # never the missed picture again
    kinds = {i.diagram.kind for i in practice.items}
    assert kinds == {"fraction_bar", "clock"}


def test_a_picture_the_teacher_disagrees_with_goes_to_the_parent():
    quiz = _quiz({"prompt": "What fraction is shaded?", "diagram": {"kind": "fraction_bar", "parts": 4, "shaded": 3},
                  "student_response": "1/4", "teacher_mark": "incorrect", "teacher_correction": "2/4"})
    (error,) = math_pack.classify_errors(quiz)
    assert error.audience == "parent_only" and "picture was read correctly" in error.evidence


def test_picture_strengths_are_reported():
    clock = {"kind": "clock", "hour": 4, "minute": 30}
    quiz = _quiz({"prompt": "Time?", "diagram": clock, "student_response": "4:30", "teacher_mark": "correct"},
                 {"prompt": "Time?", "diagram": {**clock, "hour": 7}, "student_response": "7:30", "teacher_mark": "correct"})
    assert [s.category for s in math_pack.find_strengths(quiz)] == ["math.clock"]


def test_the_reader_keeps_a_diagram():
    text = ('{"subject": "math", "sections": [{"label": "A", "items": [{"number": 1, "prompt": "What fraction is shaded?",'
            ' "diagram": {"kind": "fraction_circle", "parts": 6, "shaded": 2}, "student_response": "2/6",'
            ' "teacher_mark": "correct", "confidence": 0.9}]}]}')
    reading = extract.parse_reading(text, "math")
    assert reading.sections[0].items[0].diagram.kind == "fraction_circle"
    assert '"diagram"' in extract._RULES and "fraction_bar" in extract._RULES


# ── Drafted quizzes: the picture decides the answer ───────────────────────────

def _req(**kw):
    return GenerateQuizRequest(subject="mathematics", grade="3", focus="fractions", question_count=10, **kw)


def test_a_drafted_picture_question_is_answered_from_the_picture():
    data = {"title": "Fractions", "questions": [
        {"type": "short_answer", "prompt": "What fraction of the bar is shaded?", "answer": "2/5",
         "diagram": {"kind": "fraction_bar", "parts": 5, "shaded": 3}},
        # Same words, different picture: a different question, kept.
        {"type": "short_answer", "prompt": "What fraction of the bar is shaded?", "answer": "1/4",
         "diagram": {"kind": "fraction_bar", "parts": 4, "shaded": 1}},
        # Multiple choice with no option matching the picture: dropped.
        {"type": "multiple_choice", "prompt": "What time is it?", "options": ["1:00", "2:00", "4:00"], "answer": "1:00",
         "diagram": {"kind": "clock", "hour": 3, "minute": 0}},
        # A picture Bede cannot draw: dropped, never shown as words.
        {"type": "short_answer", "prompt": "Look at the picture.", "answer": "x",
         "diagram": {"kind": "svg", "markup": "<script>"}},
    ]}
    quiz, report = generate.finish(data, _req(), generate.check_request(_req()))
    assert [q.answer for q in quiz.questions] == ["3/5", "1/4"]
    assert all(q.answer_check == "computed" and q.diagram is not None for q in quiz.questions)
    assert report["answers_recomputed"] == 1 and report["dropped"] == 2


def test_the_drafting_rules_name_the_diagram_vocabulary():
    rules = generate._rules()
    assert '"diagram"' in rules and "never describe it in words instead" in rules
    for kind in ("fraction_bar", "clock", "array", "base_ten", "rectangle", "number_line", "coordinate_plane"):
        assert kind in rules
