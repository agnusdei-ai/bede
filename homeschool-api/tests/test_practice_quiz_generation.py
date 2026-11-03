"""Quizzes and exams drafted from an existing quiz (docs/PRACTICE_COACH.md,
"Quizzes and exams"). The model is stubbed; everything Bede does with its
draft runs for real, through the real routes.
"""
import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from models.practice import GenerateQuizRequest, PhotoPage
from routers import practice as practice_router
from services.practice import extract, generate
from tests.test_practice_coach import JPEG, StubClient, _routing, b64

DEMO = {"role": "demo_code", "code": "quiz-demo"}


def draft(*questions, coverage=("two-digit addition",), title="Addition quiz"):
    return json.dumps({"title": title, "coverage": list(coverage), "questions": list(questions)})


def q(prompt, answer, type_="short_answer", options=None, topic="t"):
    return {"type": type_, "topic": topic, "prompt": prompt, "answer": answer, "options": options or []}


@pytest.fixture
def quota(monkeypatch):
    import core.demo_code_session as session

    calls = {"recorded": 0, "allowed": True}

    async def has(code):
        return calls["allowed"]

    async def record(code):
        calls["recorded"] += 1
        return True

    monkeypatch.setattr(session, "has_message_quota", has)
    monkeypatch.setattr(session, "record_message", record)
    return calls


def req(**kw):
    base = dict(subject="mathematics", grade="3", focus="adding two-digit numbers", question_count=5)
    base.update(kw)
    return GenerateQuizRequest(**base)


@pytest.mark.asyncio
async def test_a_wrong_maths_answer_is_recomputed_and_marked(monkeypatch, quota):
    stub = StubClient(draft(q("27 + 15 =", "32", "computation"), q("48 ÷ 6 =", "8", "computation")))
    _routing(monkeypatch, local=True, cloud=None, local_client=stub)
    out = await practice_router.demo_generate_quiz(req(), auth=DEMO)
    answers = {x["prompt"]: (x["answer"], x["answer_check"]) for x in out["quiz"]["questions"]}
    assert answers == {"27 + 15 =": ("42", "computed"), "48 ÷ 6 =": ("8", "computed")}
    assert out["report"]["answers_recomputed"] == 1


@pytest.mark.asyncio
async def test_every_other_answer_is_marked_for_the_adult_to_check(monkeypatch, quota):
    stub = StubClient(draft(
        q("Which river flooded every year in Egypt?", "Nile"),
        q("The Nile is in Africa.", "True", "true_false"),
        q("Who built the pyramids?", "B", "multiple_choice", ["Romans", "Egyptians", "Vikings"]),
    ))
    _routing(monkeypatch, local=True, cloud=None, local_client=stub)
    out = await practice_router.demo_generate_quiz(req(subject="history", focus="Ancient Egypt"), auth=DEMO)
    qs = out["quiz"]["questions"]
    assert {x["answer_check"] for x in qs} == {"verify"}
    assert qs[1]["options"] == ["True", "False"]
    assert qs[2]["answer"] == "Egyptians"  # a letter becomes the option it names


@pytest.mark.asyncio
async def test_a_multiple_choice_answer_that_is_not_an_option_is_dropped(monkeypatch, quota):
    stub = StubClient(draft(
        q("Which is a mammal?", "Whale", "multiple_choice", ["Shark", "Trout", "Eel"]),
        q("What do plants need for photosynthesis?", "sunlight"),
    ))
    _routing(monkeypatch, local=True, cloud=None, local_client=stub)
    out = await practice_router.demo_generate_quiz(req(subject="science", focus="living things"), auth=DEMO)
    assert [x["prompt"] for x in out["quiz"]["questions"]] == ["What do plants need for photosynthesis?"]
    assert out["report"]["dropped"] == 1 and out["report"]["short_by"] == 4


@pytest.mark.asyncio
async def test_a_question_copied_from_the_source_is_dropped(monkeypatch, quota):
    source = "1. Which river flooded every year in Egypt?\n2. What was the ruler called?"
    stub = StubClient(draft(
        q("Which river flooded every year in Egypt?", "Nile"),
        q("What did Egyptians build to bury their rulers?", "pyramids"),
    ))
    _routing(monkeypatch, local=True, cloud=None, local_client=stub)
    out = await practice_router.demo_generate_quiz(req(subject="history", source_text=source, focus=None), auth=DEMO)
    assert [x["prompt"] for x in out["quiz"]["questions"]] == ["What did Egyptians build to bury their rulers?"]


@pytest.mark.asyncio
async def test_never_more_questions_than_asked_and_numbered_in_order(monkeypatch, quota):
    stub = StubClient(draft(*[q(f"{n} + {n} =", str(2 * n), "computation") for n in range(1, 9)]))
    _routing(monkeypatch, local=True, cloud=None, local_client=stub)
    out = await practice_router.demo_generate_quiz(req(question_count=3), auth=DEMO)
    assert [x["number"] for x in out["quiz"]["questions"]] == [1, 2, 3]


@pytest.mark.asyncio
async def test_the_model_is_told_grade_level_kind_count_and_the_constitution(monkeypatch, quota):
    stub = StubClient(draft(q("2 + 2 =", "4", "computation")))
    _routing(monkeypatch, local=True, cloud=None, local_client=stub)
    await practice_router.demo_generate_quiz(
        req(grade="7", kind="final", level="challenge", question_count=40, source_text="old exam text"), auth=DEMO)
    call = stub.calls[0]
    text = call["messages"][0]["content"][-1]["text"]
    assert "grade 7" in text and "cumulative final" in text and "harder than grade level" in text
    assert "exactly 40" in text and "old exam text" in text
    assert "<constitution>" in call["system"]


@pytest.mark.asyncio
async def test_uploaded_pages_go_to_the_model_as_images(monkeypatch, quota):
    stub = StubClient(draft(q("2 + 2 =", "4", "computation")))
    _routing(monkeypatch, local=True, cloud=None, local_client=stub)
    await practice_router.demo_generate_quiz(req(focus=None, pages=[PhotoPage(data=b64(JPEG))]), auth=DEMO)
    blocks = stub.calls[0]["messages"][0]["content"]
    assert blocks[0]["type"] == "image" and blocks[0]["source"]["media_type"] == "image/png"


@pytest.mark.parametrize("subject", ["scripture", "saints", "morning_time", "free_study"])
def test_faith_subjects_are_never_quizzed(subject):
    with pytest.raises(generate.QuizRefused):
        generate.check_request(req(subject=subject))
    assert subject not in {s["id"] for s in generate.quiz_subjects()}


def test_every_other_bede_subject_can_be_quizzed():
    from models.schemas import Subject

    offered = {s["id"] for s in generate.quiz_subjects()}
    assert offered == {s.value for s in Subject} - {"scripture", "saints", "morning_time", "free_study"}


def test_logic_is_not_offered_below_grade_3():
    with pytest.raises(generate.QuizRefused):
        generate.check_request(req(subject="logic", grade="2"))
    generate.check_request(req(subject="logic", grade="3"))


def test_there_must_be_something_to_learn_from_and_at_most_50_questions():
    with pytest.raises(generate.QuizRefused):
        generate.check_request(req(focus=None))
    with pytest.raises(ValidationError):
        req(question_count=51)
    with pytest.raises(ValidationError):
        req(grade="9")


@pytest.mark.asyncio
async def test_cloud_drafting_needs_consent_and_makes_no_call_without_it(monkeypatch, quota):
    monkeypatch.setattr(extract.settings, "practice_cloud_reading_enabled", True)
    cloud = StubClient(draft(q("2 + 2 =", "4", "computation")))
    _routing(monkeypatch, local=False, cloud="openai", cloud_client=cloud)
    with pytest.raises(HTTPException) as exc:
        await practice_router.demo_generate_quiz(req(), auth=DEMO)
    assert exc.value.status_code == 409 and not cloud.calls
    out = await practice_router.demo_generate_quiz(req(cloud_consent=True), auth=DEMO)
    assert out["quiz"]["questions"] and len(cloud.calls) == 1


@pytest.mark.asyncio
async def test_the_demo_quota_is_checked_before_any_model_call(monkeypatch, quota):
    stub = StubClient(draft(q("2 + 2 =", "4", "computation")))
    _routing(monkeypatch, local=True, cloud=None, local_client=stub)
    quota["allowed"] = False
    with pytest.raises(HTTPException) as exc:
        await practice_router.demo_generate_quiz(req(), auth=DEMO)
    assert exc.value.status_code == 429 and not stub.calls and quota["recorded"] == 0


@pytest.mark.asyncio
async def test_an_unusable_draft_is_an_error_not_an_empty_quiz(monkeypatch, quota):
    _routing(monkeypatch, local=True, cloud=None, local_client=StubClient("I cannot help with that."))
    with pytest.raises(HTTPException) as exc:
        await practice_router.demo_generate_quiz(req(), auth=DEMO)
    assert exc.value.status_code == 502


def test_no_identity_field_can_ride_along_in_a_quiz():
    from models.practice import GeneratedQuiz

    data = {"title": "t", "subject": "history", "grade": "3", "kind": "quiz", "level": "on_level",
            "est_minutes": 5, "questions": [{"number": 1, "type": "short_answer", "prompt": "p", "answer": "a"}]}
    GeneratedQuiz.model_validate(data)
    with pytest.raises(ValidationError):
        GeneratedQuiz.model_validate({**data, "student_name": "x"})
