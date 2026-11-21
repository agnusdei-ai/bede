"""Outside pictures (the Wikipedia/Wikimedia "image" lookup) belong only to
History & Geography and Art & Music, Bede's picture-study subjects. Every
other subject's picture is drawn or absent. Each guard was verified by
breaking it."""
import json

import pytest

from models.practice import GradedAssessment
from models.schemas import Subject
from routers import practice as practice_router
from services.practice import diagrams
from tests.test_practice_coach import StubClient, _routing

DEMO = {"role": "demo_code", "code": "boundary-demo"}


def test_the_approved_subjects_are_bedes_own_picture_study_subjects():
    assert diagrams.IMAGE_SUBJECTS == {Subject.history.value, Subject.art_music.value}


def _reading(subject):
    return GradedAssessment.model_validate({"subject": subject, "sections": [{"label": "A", "items": [{
        "number": 1, "prompt": "Where was this battle?", "stimulus": "picture: Battle of Hastings",
        "student_response": "England", "teacher_mark": "correct"}]}]})


@pytest.mark.parametrize("subject", ["history", "art_music"])
def test_a_reading_in_an_approved_subject_keeps_its_outside_picture(subject):
    assert _reading(subject).sections[0].items[0].diagram.kind == "image"


@pytest.mark.parametrize("subject", ["reading", "science", "geography", "mathematics", "other"])
def test_a_reading_in_any_other_subject_keeps_its_words_and_loses_the_lookup(subject):
    item = _reading(subject).sections[0].items[0]
    assert item.diagram is None and item.stimulus == "picture: Battle of Hastings"


def test_a_stored_reading_reloaded_later_is_held_to_the_boundary_too():
    stored = _reading("science").model_dump(mode="json")
    stored["sections"][0]["items"][0]["diagram"] = {"kind": "image", "wiki_title": "Battle of Hastings", "caption": "x"}
    assert GradedAssessment.model_validate(stored).sections[0].items[0].diagram is None


@pytest.fixture
def quota(monkeypatch):
    import core.demo_code_session as session

    async def yes(code):
        return True

    monkeypatch.setattr(session, "has_message_quota", yes)
    monkeypatch.setattr(session, "record_message", yes)


def _draft(subject):
    picture = {"kind": "image", "wiki_title": "Mona Lisa", "caption": "Mona Lisa"}
    return json.dumps({"title": "t", "coverage": [], "questions": [
        {"type": "short_answer", "topic": "t", "prompt": "Who painted this?", "answer": "Leonardo", "options": [], "diagram": picture},
        {"type": "short_answer", "topic": "t", "prompt": "Name a primary colour.", "answer": "red", "options": []},
    ]})


@pytest.mark.asyncio
@pytest.mark.parametrize("subject,kept", [("art_music", 2), ("history", 2), ("science", 1), ("living_books", 1), ("nature_study", 1)])
async def test_a_quiz_draft_keeps_an_outside_picture_only_in_an_approved_subject(monkeypatch, quota, subject, kept):
    from models.practice import GenerateQuizRequest

    _routing(monkeypatch, local=True, cloud=None, local_client=StubClient(_draft(subject)))
    req = GenerateQuizRequest(subject=subject, grade="4", focus="topic", question_count=5)
    out = await practice_router.demo_generate_quiz(req, auth=DEMO)
    questions = out["quiz"]["questions"]
    assert len(questions) == kept
    assert all((q.get("diagram") or {}).get("kind") != "image" for q in questions) == (kept == 1)
