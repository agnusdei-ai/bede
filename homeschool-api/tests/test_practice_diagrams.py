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


# ── Pictures in every subject ─────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    {"kind": "pictures", "groups": [{"icon": "apple", "count": 3}]},
    {"kind": "scene", "icon": "duck", "action": "swimming"},
    {"kind": "timeline", "events": [{"label": "Rome founded", "year": -753}, {"label": "Magna Carta", "year": 1215}]},
    {"kind": "venn", "left": "Frogs", "right": "Fish", "both_items": ["live in water"]},
    {"kind": "table", "header": ["Planet", "Moons"], "rows": [["Earth", "1"], ["Mars", "2"]]},
    {"kind": "cycle", "steps": ["evaporation", "condensation", "?", "collection"]},
    {"kind": "sequence", "steps": ["seed", "sprout", "plant"]},
])
def test_every_subject_has_pictures(raw):
    assert diagrams.parse(raw) is not None


@pytest.mark.parametrize("raw", [
    {"kind": "pictures", "groups": [{"icon": "unicorn"}]},
    {"kind": "scene", "icon": "duck", "action": "exploding"},
    {"kind": "table", "header": ["a"], "rows": [["1", "2"]]},
    {"kind": "cycle", "steps": ["x" * 30, "y"]},
    {"kind": "timeline", "events": [{"label": "only one", "year": 1}]},
])
def test_pictures_outside_the_lists_are_refused(raw):
    assert diagrams.parse(raw) is None


def test_counting_pictures_is_worked_out_and_other_questions_go_to_the_adult():
    apples = d(kind="pictures", groups=[{"icon": "apple", "count": 4, "label": "A"}, {"icon": "banana", "count": 2, "label": "B"}])
    assert diagrams.answer(apples, "How many are in group A?") == "4"
    assert diagrams.answer(apples, "Which group is fruit?") is None
    assert diagrams.answer(d(kind="timeline", events=[{"label": "a", "year": 1}, {"label": "b", "year": 2}]), "Which came first?") is None


def test_a_re_asked_recall_question_keeps_its_picture():
    from models.practice import Diagnosis
    from services.practice.packs import recall

    cycle = {"kind": "cycle", "steps": ["evaporation", "?", "precipitation"]}
    quiz = GradedAssessment.model_validate({"subject": "recall", "sections": [{"label": "Water", "items": [
        {"number": 1, "prompt": "What goes in the blank?", "diagram": cycle, "student_response": "rain",
         "teacher_mark": "incorrect", "teacher_correction": "condensation", "confidence": 1},
        {"number": 2, "prompt": "Name the step after evaporation in the picture.", "diagram": cycle,
         "student_response": "condensation", "teacher_mark": "correct", "confidence": 1},
    ]}]})
    practice = recall.generate_practice(Diagnosis(errors=recall.classify_errors(quiz)), quiz)
    assert practice is not None
    assert all(item.diagram is not None and item.diagram.kind == "cycle" for item in practice.items)


def test_latin_practice_scenes_are_drawn():
    import json as _json
    from pathlib import Path
    from models.practice import Diagnosis
    from services.practice.packs import latin

    golden = _json.loads(Path("services/practice/packs/latin/golden/latin_quiz_1.expected.json").read_text())
    quiz = GradedAssessment.model_validate(golden["assessment"])
    for section in quiz.sections:
        for item in section.items:
            item.ask_parent, item.confidence = None, 1.0
    practice = latin.generate_practice(Diagnosis(errors=latin.classify_errors(quiz)), quiz)
    scenes = [i for i in practice.items if i.diagram is not None]
    assert scenes, "Latin scenes should be drawn"
    for item in scenes:
        assert item.diagram.kind == "scene"
        assert item.diagram.icon in item.prompt  # the picture matches the words beside it


def test_the_reader_and_drafter_share_one_picture_list_for_every_subject():
    for text in (extract._RULES, generate._rules()):
        assert diagrams.PROMPT_SCHEMA in text
    for kind in ("pictures", "scene", "timeline", "venn", "table", "cycle", "sequence"):
        assert kind in diagrams.PROMPT_SCHEMA
    from models.practice import ACTIONS, ICONS
    assert all(name in diagrams.PROMPT_SCHEMA for name in ICONS + ACTIONS)
    assert "any subject" in generate._rules()


# ── Measuring pictures: ruler, money, thermometer ─────────────────────────────

CRAYON_AND_CUBE = {"kind": "ruler", "length": 15, "objects": [
    {"label": "crayon", "start": 0, "end": 9, "icon": "crayon"}, {"label": "linking cube", "start": 9, "end": 11}]}
TWO_PENCILS = {"kind": "ruler", "length": 15, "objects": [
    {"label": "Pencil A", "start": 0, "end": 12}, {"label": "Pencil B", "start": 0, "end": 8}]}


@pytest.mark.parametrize("raw, prompt, right", [
    (CRAYON_AND_CUBE, "What is the total length of the crayon and the linking cube?", "11"),
    (TWO_PENCILS, "Pencil B is ____ cm shorter than Pencil A.", "4"),
    ({"kind": "ruler", "unit": "in", "length": 6, "objects": [{"label": "eraser", "start": 1, "end": 3.5}]},
     "How long is the eraser?", "2.5"),
    ({"kind": "money", "pieces": [{"coin": "quarter", "count": 2}, {"coin": "dime"}]}, "How much money is shown?", "60¢"),
    ({"kind": "money", "pieces": [{"coin": "one_bill"}, {"coin": "quarter"}]}, "How much money in all?", "$1.25"),
    ({"kind": "thermometer", "low": 0, "high": 100, "reading": 60}, "What temperature does it show?", "60°F"),
])
def test_measuring_pictures_are_worked_out(raw, prompt, right):
    picture = d(**raw)
    assert diagrams.answer(picture, prompt) == right


def test_measures_accept_the_ways_children_write_them():
    assert diagrams.same(d(**CRAYON_AND_CUBE), "11 cm", "11")
    assert diagrams.same(d(kind="money", pieces=[{"coin": "quarter", "count": 2}, {"coin": "dime"}]), "$0.60", "60¢")
    assert diagrams.same(d(kind="money", pieces=[{"coin": "one_bill"}]), "100 cents", "$1.00")


@pytest.mark.parametrize("raw, prompt, given, phrase", [
    (CRAYON_AND_CUBE, "What is the total length of the crayon and the linking cube?", "9 cm", "putting the two together"),
    (TWO_PENCILS, "Pencil B is ____ cm shorter than Pencil A.", "8", "how much longer or shorter"),
    ({"kind": "ruler", "length": 10, "objects": [{"label": "crayon", "start": 2, "end": 7}]}, "How long is the crayon?", "7", "count from there"),
    ({"kind": "ruler", "length": 10, "objects": [{"label": "crayon", "start": 0, "end": 5}]}, "How long is the crayon?", "6", "marks instead of the spaces"),
    ({"kind": "money", "pieces": [{"coin": "quarter", "count": 2}, {"coin": "dime"}]}, "How much money?", "3", "counted the coins"),
    ({"kind": "thermometer", "low": 0, "high": 100, "reading": 60}, "What temperature?", "70", "line next to"),
])
def test_measuring_slips_are_named(raw, prompt, given, phrase):
    assert phrase in diagrams.explain(d(**raw), prompt, given)


@pytest.mark.parametrize("raw, prompt", [
    (CRAYON_AND_CUBE, "What is the total length of the crayon and the linking cube?"),
    (TWO_PENCILS, "Pencil B is ____ cm shorter than Pencil A."),
    ({"kind": "money", "pieces": [{"coin": "quarter"}, {"coin": "nickel"}]}, "How much money is shown?"),
    ({"kind": "thermometer", "unit": "C", "low": -10, "high": 40, "step": 5, "reading": 20}, "What temperature?"),
])
def test_fresh_measuring_practice_always_comes_with_its_own_answer(raw, prompt):
    import random

    source = d(**raw)
    for seed in range(100):
        fresh = diagrams.new_like(source, prompt, random.Random(seed))
        assert fresh is not None
        picture, text, right = fresh
        assert diagrams.answer(picture, text) == right


@pytest.mark.parametrize("raw", [
    {"kind": "ruler", "length": 10, "objects": [{"label": "x", "start": 0, "end": 12}]},
    {"kind": "ruler", "length": 10, "objects": [{"label": "x", "start": 5, "end": 3}]},
    {"kind": "ruler", "length": 10, "objects": [{"label": "x", "start": 0, "end": 2.3}]},
    {"kind": "money", "pieces": [{"coin": "doubloon"}]},
    {"kind": "thermometer", "low": 0, "high": 100, "reading": 150},
])
def test_impossible_measuring_pictures_are_refused(raw):
    assert diagrams.parse(raw) is None


def test_the_screenshot_quiz_is_diagnosed_and_practised_with_rulers():
    from models.practice import Diagnosis

    quiz = _quiz(
        {"prompt": "What is the total length of the crayon and the linking cube?", "diagram": CRAYON_AND_CUBE,
         "student_response": "9 cm", "teacher_mark": "incorrect", "teacher_correction": "11 cm"},
        {"prompt": "Pencil B is ____ cm shorter than Pencil A.", "diagram": TWO_PENCILS,
         "student_response": "8", "teacher_mark": "incorrect"},
    )
    errors = math_pack.classify_errors(quiz)
    assert [e.category for e in errors] == ["math.diagram.measuring", "math.diagram.measuring"]
    practice = math_pack.generate_practice(Diagnosis(errors=errors), quiz)
    assert practice and all(i.diagram is not None and i.diagram.kind == "ruler" for i in practice.items)
    assert all(diagrams.answer(i.diagram, i.prompt) == i.expected_answer for i in practice.items)


def test_picture_answer_choices_are_drawn_not_described():
    assert "answer choices are pictures" in extract._RULES


# ── "picture: ..." is drawn, not described ────────────────────────────────────

@pytest.mark.parametrize("words, kind, icons", [
    ("picture: dog running", "scene", ["dog"]),
    ("picture: duck on water", "pictures", ["duck", "water"]),
    ("picture: crayon and linking cube on a ruler", "pictures", ["crayon", "cube", "ruler"]),
    ("3 apples and 2 bananas", "pictures", ["apple", "banana"]),
    ("picture: two pencils with ruler showing lengths", "pictures", ["pencil", "ruler"]),
    ("Picture of a castle on a hill", "pictures", ["castle"]),
])
def test_a_described_picture_is_drawn(words, kind, icons):
    picture = diagrams.from_stimulus(words)
    assert picture is not None and picture.kind == kind
    drawn = [picture.icon] if kind == "scene" else [g.icon for g in picture.groups]
    assert drawn == icons


def test_counts_in_a_description_are_kept():
    picture = diagrams.from_stimulus("picture: 3 apples and two bananas")
    assert [(g.icon, g.count) for g in picture.groups] == [("apple", 3), ("banana", 2)]


def test_a_named_real_thing_is_shown_from_its_wikipedia_article():
    for words, title in [("picture: the Battle of Hastings", "Battle of Hastings"),
                         ("picture: Rocky Mountains", "Rocky Mountains"),
                         ("picture: The Starry Night", "The Starry Night")]:
        picture = diagrams.from_stimulus(words)
        assert picture.kind == "image" and picture.wiki_title == title


def test_an_everyday_description_is_never_sent_off_as_a_title():
    assert diagrams.from_stimulus("Dog Running").kind == "scene"
    for words in ("some children playing outside after lunch", "a boy reading a book", "rain on a window"):
        picture = diagrams.from_stimulus(words)
        assert picture is None or picture.kind != "image"


@pytest.mark.parametrize("title", ["https://evil.example/a.png", "//evil.example", "javascript:alert(1)",
                                   "data:image/png;base64,AAAA", "<img src=x>", "x" * 101])
def test_an_image_names_an_article_never_a_link(title):
    assert diagrams.parse({"kind": "image", "wiki_title": title}) is None


def test_an_image_question_is_left_to_the_adult():
    picture = d(kind="image", wiki_title="Battle of Hastings")
    assert diagrams.answer(picture, "In what year was this battle fought?") is None
    assert "image" in diagrams.PROMPT_SCHEMA and "Never a link" in diagrams.PROMPT_SCHEMA


def test_a_saved_reading_with_a_description_is_drawn_when_read_back():
    from models.practice import AssessmentItem

    item = AssessmentItem.model_validate({"number": 1, "prompt": "Quid agit?", "stimulus": "picture: dog running"})
    assert item.diagram is not None and item.diagram.kind == "scene"
    # A diagram the reader gave is never replaced by the description.
    clock = AssessmentItem.model_validate({"number": 1, "prompt": "Time?", "stimulus": "picture: a clock",
                                           "diagram": {"kind": "clock", "hour": 3, "minute": 0}})
    assert clock.diagram.kind == "clock"


def test_a_written_sum_beside_a_picture_is_still_worked_out():
    quiz = _quiz({"prompt": "27 + 15 =", "stimulus": "picture: 27 apples and 15 apples",
                  "student_response": "32", "teacher_mark": "incorrect"})
    (error,) = math_pack.classify_errors(quiz)
    assert error.category == "math.add.no_regroup"


def test_the_reader_is_not_taught_to_write_picture_descriptions():
    assert '"picture: dog running"' not in extract._RULES
