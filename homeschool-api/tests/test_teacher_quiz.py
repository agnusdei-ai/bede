"""Teacher quizzes with reviewable answer keys (docs/PRACTICE_COACH.md,
"Teacher quizzes with answer keys").

The model is stubbed; everything Bede does with its output runs for real,
and the route tests go over HTTP through the real practice router, so
request validation, the educator guard and the error mapping are all the
ones a teacher's browser meets.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.deps import require_educator
from models.practice import (
    FinalizeResultsRequest,
    SettledScore,
    StudentResponse,
    TeacherQuestion,
    TeacherQuiz,
)
from routers import practice as practice_router
from services.practice import teacher_quiz
from tests.test_practice_coach import JPEG, StubClient, _routing, b64


class SeqClient:
    """Answers each call in turn, recording what it was sent."""

    def __init__(self, *texts):
        self.texts, self.calls = list(texts), []
        self.messages = self

    async def create(self, **kwargs):
        from tests.test_practice_coach import _Reply

        self.calls.append(kwargs)
        item = self.texts.pop(0)
        if isinstance(item, Exception):
            raise item
        return _Reply(item)


@pytest.fixture
def http():
    app = FastAPI()
    app.include_router(practice_router.router)
    app.dependency_overrides[require_educator] = lambda: {"role": "educator", "sub": "teacher-1"}
    with TestClient(app) as client:
        yield client


def question(number, prompt, answer, type_="short_answer", options=None, **kw):
    base = dict(number=number, type=type_, prompt=prompt, options=options or [], answer=answer,
                key_source="teacher", key_approved=True)
    base.update(kw)
    return base


def quiz(*questions, subject="mathematics", grade="4", approved=True):
    return {"title": "Week 3 check", "subject": subject, "grade": grade, "questions": list(questions),
            "approved": approved}


APPROVED = quiz(
    question(1, "27 + 15 =", "42", "computation"),
    question(2, "Which is a mammal?", "Whale", "multiple_choice", ["Shark", "Whale", "Trout"]),
    question(3, "The Nile is in Africa.", "True", "true_false", ["True", "False"]),
    question(4, "What is the capital of France?", "Paris", accepted_answers=["Paris, France"]),
    question(5, "Explain why the sky looks blue.", "", "written_response", points=4,
             rubric="2 points: names scattering. 2 points: says blue light scatters most."),
)


# ── Writing and approving the key ────────────────────────────────────────────

def test_a_teacher_typed_quiz_can_be_approved_and_printed(http):
    draft = quiz(*APPROVED["questions"], approved=False)
    review = http.post("/practice/educator/teacher-quiz/review", json={"quiz": draft}).json()
    assert review["problems"] == []
    out = http.post("/practice/educator/teacher-quiz/approve", json={"quiz": draft})
    assert out.status_code == 200 and out.json()["quiz"]["approved"] is True


def test_a_suggested_or_page_read_answer_is_never_approved_for_the_teacher(http):
    draft = quiz(
        question(1, "Which river flooded every year?", "Nile", key_source="bede", key_approved=False),
        question(2, "What did the pharaohs build?", "Pyramids", key_source="page", key_approved=False),
        subject="history", approved=False,
    )
    review = http.post("/practice/educator/teacher-quiz/review", json={"quiz": draft}).json()
    assert {(p["number"], p["problem"]) for p in review["problems"]} == {
        (1, "key_not_approved"), (2, "key_not_approved")}
    refused = http.post("/practice/educator/teacher-quiz/approve", json={"quiz": draft})
    assert refused.status_code == 422 and refused.json()["detail"]["problems"]


def test_an_unsettled_reading_or_missing_key_blocks_approval(http):
    draft = quiz(
        question(1, "8 x 7 =", "56", "computation", reading_note="The 7 may be a 1."),
        question(2, "Name a prime number.", ""),
        question(3, "Pick one", "Purple", "multiple_choice", ["Red", "Blue"]),
        approved=False,
    )
    problems = http.post("/practice/educator/teacher-quiz/review", json={"quiz": draft}).json()["problems"]
    assert {(p["number"], p["problem"]) for p in problems} == {
        (1, "reading_unsettled"), (2, "no_key"), (3, "answer_not_an_option")}


@pytest.mark.parametrize("subject", ["scripture", "saints", "morning_time", "free_study"])
def test_faith_subjects_are_never_scored_even_in_a_teacher_quiz(http, subject):
    draft = quiz(question(1, "Who was Moses?", "A prophet"), subject=subject, approved=False)
    problems = http.post("/practice/educator/teacher-quiz/review", json={"quiz": draft}).json()["problems"]
    assert {"number": None, "problem": "not_quizzed"} in problems


def test_logic_is_not_offered_below_grade_3(http):
    draft = quiz(question(1, "If A then B?", "B"), subject="logic", grade="2", approved=False)
    problems = http.post("/practice/educator/teacher-quiz/review", json={"quiz": draft}).json()["problems"]
    assert {"number": None, "problem": "logic_below_grade_3"} in problems


def test_a_quiz_has_no_field_for_a_learner():
    with pytest.raises(ValidationError):
        TeacherQuiz.model_validate({**APPROVED, "student_name": "Someone"})
    with pytest.raises(ValidationError):
        TeacherQuestion.model_validate({**APPROVED["questions"][0], "student": "Someone"})


def test_an_exported_file_imports_as_the_same_quiz(http):
    exported = TeacherQuiz.model_validate(APPROVED).model_dump(mode="json")
    assert exported["format"] == "bede.teacher-quiz" and exported["version"] == 1
    review = http.post("/practice/educator/teacher-quiz/review", json={"quiz": exported})
    assert review.status_code == 200 and review.json()["quiz"] == exported
    assert http.post("/practice/educator/teacher-quiz/review",
                     json={"quiz": {**exported, "format": "other"}}).status_code == 422


# ── Reading a quiz the teacher already has ───────────────────────────────────

EXTRACTED = json.dumps({"title": "Fractions quiz", "questions": [
    {"number": 1, "type": "computation", "prompt": "3/4 + 1/4 =", "answer": "1", "answer_from_page": True,
     "confidence": 0.95},
    {"number": 2, "type": "computation", "prompt": "12 × 3 =", "answer": "38", "answer_from_page": False,
     "confidence": 0.9},
    {"number": 3, "type": "multiple_choice", "prompt": "Which is largest?", "options": ["1/2", "1/3", "1/4"],
     "answer": "A", "answer_from_page": False, "confidence": 0.9, "stimulus": "diagram: three shaded bars"},
    {"number": 4, "type": "short_answer", "prompt": "Name the top number of a fraction.", "answer": "numerator",
     "answer_from_page": True, "confidence": 0.5},
    {"number": 5, "type": "computation", "prompt": "9 × 6 =", "answer": "56", "answer_from_page": True,
     "confidence": 0.95},
]})


def _extract(http, **kw):
    body = {"subject": "mathematics", "grade": "4", "pages": [{"data": b64(JPEG)}], "upload_consent": True}
    body.update(kw)
    return http.post("/practice/educator/teacher-quiz/extract", json=body)


def test_an_uploaded_quiz_is_read_and_every_answer_says_where_it_came_from(http, monkeypatch):
    local = StubClient(EXTRACTED)
    _routing(monkeypatch, local=True, cloud=None, local_client=local)
    out = _extract(http)
    assert out.status_code == 200
    qs = out.json()["quiz"]["questions"]
    assert [q["key_source"] for q in qs] == ["page", "bede", "bede", "page", "page"]
    assert not any(q["key_approved"] for q in qs)
    # Bede's own suggestion is recomputed; the teacher's printed key is
    # flagged, never silently replaced.
    assert (qs[1]["answer"], qs[1]["answer_check"]) == ("36", "computed")
    assert qs[4]["answer"] == "56" and "54" in qs[4]["reading_note"]
    assert qs[2]["answer"] == "1/2" and qs[2]["stimulus"] == "diagram: three shaded bars"
    assert qs[3]["reading_note"]  # low confidence
    assert out.json()["quiz"]["approved"] is False
    blocks = local.calls[0]["messages"][0]["content"]
    assert blocks[0]["type"] == "image" and blocks[0]["source"]["media_type"] == "image/png"


def test_an_uploaded_quiz_needs_the_teachers_tick_before_anything_is_read(http, monkeypatch):
    local = StubClient(EXTRACTED)
    _routing(monkeypatch, local=True, cloud=None, local_client=local)
    out = _extract(http, upload_consent=False)
    assert out.status_code == 409 and out.json()["detail"]["consent_required"] is True
    assert out.json()["detail"]["provider"] == "the school's own AI model"
    assert local.calls == []


def test_a_teacher_quiz_is_never_read_by_a_cloud_provider(http, monkeypatch):
    cloud = StubClient(EXTRACTED)
    _routing(monkeypatch, local=False, cloud="openai", cloud_client=cloud)
    monkeypatch.setattr(teacher_quiz.extract.settings, "practice_cloud_reading_enabled", True)
    out = _extract(http)
    assert out.status_code == 409 and "school's own AI model" in out.json()["detail"]
    assert cloud.calls == []
    typed = _extract(http, pages=[], source_text="1. 2 + 2 =")
    assert typed.status_code == 409 and cloud.calls == []


def test_pasted_quiz_text_is_read_without_photos(http, monkeypatch):
    local = StubClient(EXTRACTED)
    _routing(monkeypatch, local=True, cloud=None, local_client=local)
    out = _extract(http, pages=[], source_text="1. 3/4 + 1/4 = ___", upload_consent=False)
    assert out.status_code == 200
    assert "3/4 + 1/4" in local.calls[0]["messages"][0]["content"][-1]["text"]


def test_a_rejected_file_is_refused_before_the_model(http, monkeypatch):
    local = StubClient(EXTRACTED)
    _routing(monkeypatch, local=True, cloud=None, local_client=local)
    out = _extract(http, pages=[{"data": b64(b"GIF89a not really an image")}])
    assert out.status_code == 422 and local.calls == []


# ── Scoring one student's work ───────────────────────────────────────────────

READING = json.dumps({"responses": [
    {"number": 1, "response": "42", "confidence": 0.95},
    {"number": 2, "response": "Shark", "confidence": 0.95},
    {"number": 3, "response": "True", "confidence": 0.95},
    {"number": 4, "response": "paris", "confidence": 0.6, "ask_teacher": "Could be 'Paris' or 'Parts'."},
    {"number": 5, "response": "Light bounces off air and blue scatters more.", "confidence": 0.9},
]})
RUBRIC = json.dumps({"scores": [{"number": 5, "points": 3.4, "reason": "Names scattering; blue part is partial."}]})


def _score(http, **kw):
    body = {"quiz": APPROVED, "pages": [{"data": b64(JPEG)}], "upload_consent": True}
    body.update(kw)
    return http.post("/practice/educator/teacher-quiz/score", json=body)


def test_a_students_work_is_scored_against_the_key_in_code(http, monkeypatch):
    local = SeqClient(READING, RUBRIC)
    _routing(monkeypatch, local=True, cloud=None, local_client=local)
    out = _score(http)
    assert out.status_code == 200
    rows = {r["number"]: r for r in out.json()["results"]}
    assert (rows[1]["proposed_points"], rows[1]["method"], rows[1]["needs_teacher"]) == (1, "numeric", False)
    assert (rows[2]["proposed_points"], rows[2]["needs_teacher"]) == (0, False)
    assert (rows[3]["proposed_points"], rows[3]["needs_teacher"]) == (1, False)
    # Right answer, uncertain reading: still waits for the teacher.
    assert rows[4]["proposed_points"] == 1 and rows[4]["needs_teacher"] and "reading_uncertain" in rows[4]["reasons"]
    # The rubric proposal is rounded to a half point and always for review.
    assert (rows[5]["proposed_points"], rows[5]["method"], rows[5]["needs_teacher"]) == (3.5, "rubric_proposal", True)
    assert out.json()["possible"] == 8 and "total" not in out.json()


def test_the_reader_of_student_work_never_sees_the_answer_key(http, monkeypatch):
    local = SeqClient(READING, RUBRIC)
    _routing(monkeypatch, local=True, cloud=None, local_client=local)
    _score(http)
    read_call = json.dumps(local.calls[0]["messages"])
    assert "27 + 15" in read_call and "Which is a mammal?" in read_call
    assert "42" not in read_call and "Paris" not in read_call and "Whale" in read_call  # an option, not the key
    assert "scattering" not in read_call  # nor the rubric


def test_scoring_refuses_an_unapproved_key_before_reading_anything(http, monkeypatch):
    local = SeqClient(READING)
    _routing(monkeypatch, local=True, cloud=None, local_client=local)
    unapproved = quiz(question(1, "Which river?", "Nile", key_source="bede", key_approved=False),
                      subject="history", approved=True)  # the flag alone buys nothing
    out = _score(http, quiz=unapproved)
    assert out.status_code == 422 and local.calls == []
    not_flagged = quiz(*APPROVED["questions"], approved=False)
    assert _score(http, quiz=not_flagged).status_code == 422 and local.calls == []


def test_student_work_needs_the_teachers_tick_and_the_local_model(http, monkeypatch):
    local = SeqClient(READING)
    _routing(monkeypatch, local=True, cloud=None, local_client=local)
    out = _score(http, upload_consent=False)
    assert out.status_code == 409 and out.json()["detail"]["consent_required"] and local.calls == []
    cloud = StubClient(READING)
    _routing(monkeypatch, local=False, cloud="openai", cloud_client=cloud)
    out = _score(http)
    assert out.status_code == 409 and cloud.calls == []


def test_typed_answers_are_scored_without_a_model(http, monkeypatch):
    _routing(monkeypatch, local=False, cloud="openai", cloud_client=StubClient("{}"))
    typed = [{"number": 1, "response": "41"}, {"number": 4, "response": "Paris, France"},
             {"number": 5, "response": "Because of scattering."}]
    out = _score(http, pages=[], responses=typed, upload_consent=False)
    assert out.status_code == 200
    rows = {r["number"]: r for r in out.json()["results"]}
    assert rows[1]["proposed_points"] == 0 and rows[4]["proposed_points"] == 1
    # No local model, so no rubric proposal: the teacher scores it.
    assert rows[5]["proposed_points"] is None and rows[5]["method"] == "teacher_scores"
    # Unanswered questions are blanks worth nothing, not flagged.
    assert rows[2]["proposed_points"] == 0 and not rows[2]["needs_teacher"]


def test_a_missing_answer_on_the_page_is_flagged_not_scored_silently(http, monkeypatch):
    partial = json.dumps({"responses": [{"number": 1, "response": "42", "confidence": 0.95}]})
    _routing(monkeypatch, local=True, cloud=None, local_client=SeqClient(partial, RUBRIC))
    rows = {r["number"]: r for r in _score(http).json()["results"]}
    assert rows[2]["needs_teacher"] and rows[2]["reasons"] == ["not_found"]


def test_a_reading_that_smuggles_in_a_name_has_nowhere_to_put_it(http, monkeypatch):
    sneaky = json.dumps({"student_name": "Someone", "responses": [{"number": 1, "response": "42", "name": "x"}]})
    _routing(monkeypatch, local=True, cloud=None, local_client=SeqClient(sneaky, RUBRIC))
    out = _score(http)
    assert out.status_code == 200 and "Someone" not in out.text


# ── Deterministic comparison ─────────────────────────────────────────────────

def _q(**kw):
    return TeacherQuestion.model_validate(question(1, kw.pop("prompt", "p"), kw.pop("answer"), **kw))


@pytest.mark.parametrize("answer,response,points", [
    ("1/2", "0.5", 1), ("1/2", "2/4", 1), ("3 1/2", "7/2", 1), ("42", "x = 42", 1), ("42", "24", 0),
    ("7/2 (= 3 1/2)", "3 1/2", 1),
])
def test_numbers_are_compared_exactly(answer, response, points):
    r = teacher_quiz.score_one(_q(answer=answer, type="computation"), StudentResponse(number=1, response=response))
    assert (r.proposed_points, r.method, r.needs_teacher) == (points, "numeric", False)


@pytest.mark.parametrize("response,points", [("B", 1), ("(b)", 1), ("whale", 1), ("A", 0), ("Shark", 0)])
def test_a_choice_can_be_given_by_its_letter_or_its_text(response, points):
    q = _q(answer="Whale", type="multiple_choice", options=["Shark", "Whale", "Trout"])
    assert teacher_quiz.score_one(q, StudentResponse(number=1, response=response)).proposed_points == points


def test_a_choice_that_names_no_option_goes_to_the_teacher():
    q = _q(answer="Whale", type="multiple_choice", options=["Shark", "Whale", "Trout"])
    r = teacher_quiz.score_one(q, StudentResponse(number=1, response="dolphin"))
    assert r.proposed_points is None and r.needs_teacher and r.reasons == ["response_unclear"]


@pytest.mark.parametrize("response", ["T", "verdadero", "true."])
def test_true_false_accepts_ordinary_spellings(response):
    q = _q(answer="True", type="true_false", options=["True", "False"])
    assert teacher_quiz.score_one(q, StudentResponse(number=1, response=response)).proposed_points == 1


def test_a_short_answer_ignores_case_accents_and_punctuation_but_not_digits():
    q = _q(answer="Ávila", accepted_answers=["Avila, Spain"])
    for response in ("avila", "AVILA!", "avila spain"):
        assert teacher_quiz.score_one(q, StudentResponse(number=1, response=response)).proposed_points == 1
    q2 = _q(answer="Henry 8")
    assert teacher_quiz.score_one(q2, StudentResponse(number=1, response="Henry 7")).proposed_points == 0


def test_a_short_answer_that_misses_the_key_is_the_teachers_call():
    r = teacher_quiz.score_one(_q(answer="Paris"), StudentResponse(number=1, response="It is Paris"))
    assert r.proposed_points == 0 and r.needs_teacher and r.reasons == ["not_in_key"]


def test_a_written_response_without_a_rubric_is_scored_by_the_teacher():
    q = _q(answer="", type="written_response", points=3)
    r = teacher_quiz.score_one(q, StudentResponse(number=1, response="Some thoughts."))
    assert r.proposed_points is None and r.needs_teacher and r.reasons == ["no_rubric"]


@pytest.mark.asyncio
async def test_a_rubric_proposal_is_clamped_and_a_failure_leaves_the_teacher_to_score(monkeypatch):
    q = TeacherQuiz.model_validate(quiz(question(1, "Explain.", "", "written_response", points=2, rubric="r")))
    results = teacher_quiz.score_responses(q, [StudentResponse(number=1, response="an answer")])
    await teacher_quiz.propose_rubric_scores(
        SeqClient(json.dumps({"scores": [{"number": 1, "points": 9, "reason": "x"}]})), q, results)
    assert results[0].proposed_points == 2 and results[0].needs_teacher
    again = teacher_quiz.score_responses(q, [StudentResponse(number=1, response="an answer")])
    await teacher_quiz.propose_rubric_scores(SeqClient(RuntimeError("down")), q, again)
    assert again[0].proposed_points is None and again[0].method == "teacher_scores"


# ── The teacher settles the results ──────────────────────────────────────────

def test_nothing_counts_until_every_result_is_settled(http):
    results = [{"number": n, "points": 1} for n in (1, 2, 3, 4)] + [{"number": 5, "points": None}]
    out = http.post("/practice/educator/teacher-quiz/finalize", json={"quiz": APPROVED, "results": results})
    assert out.status_code == 409 and out.json()["detail"]["unsettled"] == [5]
    results[-1]["points"] = 3.5
    out = http.post("/practice/educator/teacher-quiz/finalize", json={"quiz": APPROVED, "results": results})
    assert out.status_code == 200
    assert (out.json()["total"], out.json()["possible"], out.json()["source"]) == (7.5, 8, "teacher_approved")


def test_a_result_above_the_questions_points_is_refused():
    req = FinalizeResultsRequest(quiz=TeacherQuiz.model_validate(APPROVED),
                                 results=[SettledScore(number=n, points=5) for n in range(1, 6)])
    with pytest.raises(Exception):
        teacher_quiz.finalize(req)


# ── Wiring ───────────────────────────────────────────────────────────────────

def test_the_real_app_serves_every_teacher_quiz_route_behind_the_educator_guard():
    import main
    from tests.test_valor_pilot_delivery_disabled import walk_app_routes

    served = dict(walk_app_routes(main.app.routes))
    for name in ("review", "approve", "extract", "score", "finalize"):
        assert served.get(f"/practice/educator/teacher-quiz/{name}") == frozenset({"POST"})


def test_without_an_educator_session_the_routes_refuse(monkeypatch):
    app = FastAPI()
    app.include_router(practice_router.router)
    with TestClient(app) as client:
        out = client.post("/practice/educator/teacher-quiz/review", json={"quiz": APPROVED})
    assert out.status_code in (401, 403)


def test_nothing_is_written_to_the_database():
    import inspect

    source = inspect.getsource(teacher_quiz)
    for forbidden in ("AsyncSession", "db.add", "commit(", "store."):
        assert forbidden not in source


# ── Long uploads: no page-count limit, read a group at a time ────────────────

def _q_raw(prompt, answer):
    return {"type": "short_answer", "prompt": prompt, "answer": answer, "answer_from_page": True, "confidence": 1.0}


def test_a_long_uploaded_quiz_is_read_a_group_at_a_time_and_joined_in_order(http, monkeypatch):
    groups = [
        json.dumps({"title": "Unit test", "questions": [_q_raw("Capital of France?", "Paris")]}),
        json.dumps({"title": "ignored", "questions": [_q_raw("Largest ocean?", "Pacific")]}),
        json.dumps({"questions": [_q_raw("Longest river?", "Nile")]}),
    ]
    local = SeqClient(*groups)
    _routing(monkeypatch, local=True, cloud=None, local_client=local)
    out = _extract(http, pages=[{"data": b64(JPEG)}] * 13, source_text="Also: name a planet.")
    assert out.status_code == 200, out.text
    quiz_out = out.json()["quiz"]
    assert [q["prompt"] for q in quiz_out["questions"]] == ["Capital of France?", "Largest ocean?", "Longest river?"]
    assert [q["number"] for q in quiz_out["questions"]] == [1, 2, 3]
    assert quiz_out["title"] == "Unit test"
    sizes = [sum(1 for b in c["messages"][0]["content"] if b["type"] == "image") for c in local.calls]
    assert sizes == [6, 6, 1]
    texts = [c["messages"][0]["content"][-1]["text"] for c in local.calls]
    assert "pages 1 to 6 of 13" in texts[0] and "pages 13 to 13 of 13" in texts[2]
    # The teacher's pasted text goes with the first group only.
    assert "name a planet" in texts[0] and "name a planet" not in texts[1]


def test_a_long_piece_of_student_work_is_read_in_groups_and_merged(http, monkeypatch):
    first = json.dumps({"responses": [
        {"number": 1, "response": "42", "confidence": 0.95},
        {"number": 2, "response": None, "confidence": 0.0},
    ]})
    second = json.dumps({"responses": [
        {"number": 1, "response": None, "confidence": 0.0},  # not on these pages: must not erase the answer
        {"number": 2, "response": "Whale", "confidence": 0.95},
        {"number": 3, "response": "Paris", "confidence": 0.95},
    ]})
    local = SeqClient(first, second, RUBRIC)
    _routing(monkeypatch, local=True, cloud=None, local_client=local)
    out = _score(http, pages=[{"data": b64(JPEG)}] * 7)
    assert out.status_code == 200, out.text
    rows = {r["number"]: r for r in out.json()["results"]}
    assert rows[1]["response"] == "42" and rows[2]["response"] == "Whale" and rows[3]["response"] == "Paris"
    # Both reads saw the questions and neither saw the key.
    for call in local.calls[:2]:
        sent = json.dumps(call["messages"])
        assert "27 + 15" in sent and "Paris" not in sent


def test_merging_keeps_the_more_confident_of_two_readings():
    merged = teacher_quiz.merge_responses([
        {"responses": [{"number": 1, "response": "7", "confidence": 0.4}]},
        {"responses": [{"number": 1, "response": "1", "confidence": 0.9}, "junk"]},
    ])
    assert merged["responses"] == [{"number": 1, "response": "1", "confidence": 0.9}]


def test_there_is_no_page_count_limit_on_a_teacher_upload():
    from models.practice import ExtractQuizRequest, ScoreSubmissionRequest

    pages = [{"data": "aGVsbG8gd29ybGQ="}] * 60
    assert len(ExtractQuizRequest(subject="mathematics", grade="4", pages=pages).pages) == 60
    assert len(ScoreSubmissionRequest(quiz=TeacherQuiz(**APPROVED), pages=pages).pages) == 60
