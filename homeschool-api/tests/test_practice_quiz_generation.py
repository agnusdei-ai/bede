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


@pytest.mark.asyncio
async def test_a_long_source_is_copied_out_a_group_at_a_time_and_each_group_is_charged(monkeypatch, quota):
    stub = StubClient(draft(q("2 + 2 =", "4", "computation")))
    _routing(monkeypatch, local=True, cloud=None, local_client=stub)
    await practice_router.demo_generate_quiz(req(focus=None, pages=[PhotoPage(data=b64(JPEG))] * 8), auth=DEMO)
    images = [sum(b["type"] == "image" for b in c["messages"][0]["content"]) for c in stub.calls]
    assert images[:3] == [6, 2, 0]  # two groups copied out, then a text-only draft
    draft_text = stub.calls[2]["messages"][0]["content"][-1]["text"]
    assert "[Pages 1-6]" in draft_text and "[Pages 7-8]" in draft_text
    # writing + checking, plus two per group copied out: the content check
    # (services/content_screen.py) and the copying
    assert quota["recorded"] == 6


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


# ── Independent answer check ─────────────────────────────────────────────────

class SeqClient:
    """Returns each reply in turn: the draft first, then the check."""

    def __init__(self, *texts):
        self.texts, self.calls = list(texts), []
        self.messages = self

    async def create(self, **kwargs):
        from tests.test_practice_coach import _Reply

        self.calls.append(kwargs)
        text = self.texts[min(len(self.calls), len(self.texts)) - 1]
        if isinstance(text, Exception):
            raise text
        return _Reply(text)


def check(*answers):
    return json.dumps({"answers": [{"number": n, "answer": a, "sure": s} for n, a, s in answers]})


HISTORY = draft(
    q("Which river flooded every year in Egypt?", "Nile"),
    q("Who built the pyramids?", "Egyptians", "multiple_choice", ["Romans", "Egyptians", "Vikings"]),
    q("What was the ruler of Egypt called?", "pharaoh"),
    q("Explain why the flood mattered.", "rich soil", "written_response"),
)


@pytest.mark.asyncio
async def test_agreeing_answers_are_checked_and_disagreeing_ones_show_both(monkeypatch, quota):
    client = SeqClient(HISTORY, check((1, "The Nile", True), (2, "Egyptians", True), (3, "king", True)))
    _routing(monkeypatch, local=True, cloud=None, local_client=client)
    out = await practice_router.demo_generate_quiz(req(subject="history", focus="Egypt"), auth=DEMO)
    qs = {x["number"]: x for x in out["quiz"]["questions"]}
    assert qs[1]["answer_check"] == "checked" and qs[2]["answer_check"] == "checked"
    assert qs[3]["answer_check"] == "verify" and qs[3]["second_answer"] == "king"
    assert qs[4]["answer_check"] == "verify"  # an essay has no single key to check
    assert out["report"]["checked"] == 2 and out["report"]["disagreed"] == 1


@pytest.mark.asyncio
async def test_an_unsure_second_answer_never_counts_as_a_check(monkeypatch, quota):
    client = SeqClient(HISTORY, check((1, "Nile", False), (2, "Egyptians", False)))
    _routing(monkeypatch, local=True, cloud=None, local_client=client)
    out = await practice_router.demo_generate_quiz(req(subject="history", focus="Egypt"), auth=DEMO)
    assert {x["answer_check"] for x in out["quiz"]["questions"]} == {"verify"}


@pytest.mark.asyncio
async def test_the_checker_never_sees_the_first_answers(monkeypatch, quota):
    client = SeqClient(HISTORY, check())
    _routing(monkeypatch, local=True, cloud=None, local_client=client)
    await practice_router.demo_generate_quiz(req(subject="history", source_text="Egypt notes"), auth=DEMO)
    sent = client.calls[1]["messages"][0]["content"][0]["text"]
    assert "Which river flooded" in sent and "Egypt notes" in sent
    assert "pharaoh" not in sent and "Nile" not in sent


@pytest.mark.asyncio
async def test_a_failed_check_leaves_answers_to_be_checked_by_the_adult(monkeypatch, quota):
    client = SeqClient(HISTORY, RuntimeError("provider down"))
    _routing(monkeypatch, local=True, cloud=None, local_client=client)
    out = await practice_router.demo_generate_quiz(req(subject="history", focus="Egypt"), auth=DEMO)
    assert {x["answer_check"] for x in out["quiz"]["questions"]} == {"verify"}
    assert out["report"]["check_failed"] is True


@pytest.mark.asyncio
async def test_computed_maths_answers_are_not_sent_to_the_checker(monkeypatch, quota):
    client = SeqClient(draft(q("27 + 15 =", "42", "computation")), check())
    _routing(monkeypatch, local=True, cloud=None, local_client=client)
    await practice_router.demo_generate_quiz(req(), auth=DEMO)
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_a_demo_draft_counts_both_model_calls(monkeypatch, quota):
    client = SeqClient(HISTORY, check())
    _routing(monkeypatch, local=True, cloud=None, local_client=client)
    await practice_router.demo_generate_quiz(req(subject="history", focus="Egypt"), auth=DEMO)
    assert quota["recorded"] == 2


# ── Teachers ──────────────────────────────────────────────────────────────────

TEACHER = {"role": "educator", "sub": "teacher-1"}


@pytest.mark.asyncio
async def test_a_teacher_drafts_on_the_local_model_only(monkeypatch):
    monkeypatch.setattr(extract.settings, "practice_cloud_reading_enabled", True)
    local = SeqClient(HISTORY, check())
    cloud = StubClient(HISTORY)
    _routing(monkeypatch, local=True, cloud="openai", local_client=local, cloud_client=cloud)
    out = await practice_router.educator_generate_quiz(req(subject="history", focus="Egypt", cloud_consent=True), auth=TEACHER)
    assert out["quiz"]["questions"] and local.calls and not cloud.calls


@pytest.mark.asyncio
async def test_a_teacher_without_a_local_model_is_refused_and_nothing_goes_to_the_cloud(monkeypatch):
    monkeypatch.setattr(extract.settings, "practice_cloud_reading_enabled", True)
    cloud = StubClient(HISTORY)
    _routing(monkeypatch, local=False, cloud="openai", cloud_client=cloud)
    with pytest.raises(HTTPException) as exc:
        await practice_router.educator_generate_quiz(req(subject="history", focus="Egypt", cloud_consent=True), auth=TEACHER)
    assert exc.value.status_code == 409 and not cloud.calls
    with pytest.raises(HTTPException) as exc:
        await practice_router.educator_generate_quiz(req(subject="history", focus="Egypt", route="cloud"), auth=TEACHER)
    assert exc.value.status_code == 422 and not cloud.calls


@pytest.mark.asyncio
async def test_teacher_options_never_offer_a_cloud_provider(monkeypatch):
    _routing(monkeypatch, local=False, cloud="openai")
    monkeypatch.setattr(extract.settings, "practice_cloud_reading_enabled", True)
    options = await practice_router.educator_quiz_options(auth=TEACHER)
    assert options["route"] == {"local_available": False, "cloud_provider": None, "draft_provider": None}


# ── Typed drafts: no photo leaves the browser ────────────────────────────────

@pytest.mark.asyncio
async def test_a_typed_draft_needs_no_photo_switch_and_never_fails_over(monkeypatch, quota):
    """A draft from a typed topic sends text only, so the photo switch does
    not govern it. It goes to the one provider the parent agreed to and is
    never retried on another, because the consent named that provider."""
    from services.adapters import router
    import services.ai_service as ai_service

    monkeypatch.setattr(extract.settings, "practice_cloud_reading_enabled", False)
    named = StubClient(draft(q("6 x 7 =", "42", "computation")))
    failover = StubClient(draft(q("1 + 1 =", "2", "computation")))
    _routing(monkeypatch, local=False, cloud="openai")
    asked_for = []
    monkeypatch.setattr(router, "resolve_named", lambda name, *a, **k: asked_for.append(name) or named)
    monkeypatch.setattr(ai_service, "_client", failover)

    out = await practice_router.demo_generate_quiz(
        req(grade="2", focus="Multiplication", cloud_consent=True), auth=DEMO)
    assert [x["prompt"] for x in out["quiz"]["questions"]] == ["6 x 7 ="]
    assert asked_for == ["openai"]
    assert named.calls and failover.calls == []


@pytest.mark.asyncio
async def test_a_typed_draft_still_needs_the_tick_for_that_provider(monkeypatch, quota):
    named = StubClient(draft(q("6 x 7 =", "42", "computation")))
    _routing(monkeypatch, local=False, cloud="openai", cloud_client=named)
    with pytest.raises(HTTPException) as exc:
        await practice_router.demo_generate_quiz(req(), auth=DEMO)
    assert exc.value.status_code == 409
    assert exc.value.detail["provider"] == "openai"
    assert named.calls == []


@pytest.mark.asyncio
async def test_photos_still_need_the_photo_switch_even_with_the_tick(monkeypatch, quota):
    monkeypatch.setattr(extract.settings, "practice_cloud_reading_enabled", False)
    named = StubClient(draft(q("6 x 7 =", "42", "computation")))
    _routing(monkeypatch, local=False, cloud="openai", cloud_client=named)
    with pytest.raises(HTTPException) as exc:
        await practice_router.demo_generate_quiz(
            req(pages=[PhotoPage(data=b64(JPEG))], cloud_consent=True), auth=DEMO)
    assert exc.value.status_code == 409
    assert named.calls == []


@pytest.mark.asyncio
async def test_options_offer_typed_drafts_but_not_photos_while_the_switch_is_off(monkeypatch):
    monkeypatch.setattr(extract.settings, "practice_cloud_reading_enabled", False)
    _routing(monkeypatch, local=False, cloud="openai")
    route = (await practice_router.demo_quiz_options(auth=DEMO))["route"]
    assert route == {"local_available": False, "cloud_provider": None, "draft_provider": "openai"}


@pytest.mark.asyncio
async def test_teacher_options_offer_no_typed_cloud_draft_either(monkeypatch):
    _routing(monkeypatch, local=True, cloud="openai")
    route = (await practice_router.educator_quiz_options(auth=TEACHER))["route"]
    assert route["cloud_provider"] is None and route["draft_provider"] is None


@pytest.mark.asyncio
async def test_resolve_named_uses_exactly_one_adapter(monkeypatch):
    from services.adapters import router

    built = []

    class Adapter:
        def __init__(self, name):
            self.name = name
            self.messages = self

        async def create(self, **kw):
            return self.name

    monkeypatch.setattr(router, "_configured_order", lambda settings: ["openai", "mistral"])
    monkeypatch.setattr(router, "_build", lambda name, settings: built.append(name) or Adapter(name))
    monkeypatch.setattr(router, "_named_clients", {})
    client = router.resolve_named("openai")
    assert await client.messages.create(model="m") == "openai"
    # Built once and reused, so each draft does not open a new connection pool.
    assert router.resolve_named("openai") is client
    assert built == ["openai"]
    with pytest.raises(router.NamedAdapterUnavailableError):
        router.resolve_named("anthropic")


@pytest.mark.asyncio
async def test_photos_go_only_to_the_named_provider_never_a_backup(monkeypatch):
    """Photos of a child's work go to the provider the parent ticked, and an
    error there is never retried on another provider."""
    from services.adapters import router
    import services.ai_service as ai_service
    from tests.test_practice_coach import GOLDEN, _req

    monkeypatch.setattr(extract.settings, "practice_cloud_reading_enabled", True)
    named = StubClient(json.dumps(GOLDEN["assessment"]))
    failover = StubClient(json.dumps(GOLDEN["assessment"]))
    _routing(monkeypatch, local=False, cloud="openai")
    asked_for = []
    monkeypatch.setattr(router, "resolve_named", lambda name, *a, **k: asked_for.append(name) or named)
    monkeypatch.setattr(ai_service, "_client", failover)
    await extract.read_pages(_req(cloud_consent=True))
    assert asked_for == ["openai"] and len(named.calls) == 1 and failover.calls == []


@pytest.mark.asyncio
async def test_the_tick_names_the_provider_the_parent_switched_to(monkeypatch):
    from core import provider_state

    _routing(monkeypatch, local=False, cloud="openai")
    from services.adapters import router
    monkeypatch.setattr(router, "configured_adapters", lambda *a, **k: ["openai", "mistral"])
    monkeypatch.setattr(provider_state, "_cached_primary", "mistral")
    route = (await practice_router.demo_quiz_options(auth=DEMO))["route"]
    assert route["draft_provider"] == "mistral"


# ── A long quiz source, sent in parts ─────────────────────────────────────────

def _source(n, **kw):
    from models.practice import QuizSourceRequest

    return QuizSourceRequest(subject="mathematics", pages=[PhotoPage(data=b64(JPEG))] * n, **kw)


@pytest.mark.asyncio
async def test_a_source_part_is_copied_out_a_group_at_a_time_and_charged_per_group(monkeypatch, quota):
    stub = StubClient("Q1. 2 + 2 = ?")
    _routing(monkeypatch, local=True, cloud=None, local_client=stub)
    out = await practice_router.demo_copy_quiz_source(_source(8, first_page=13), auth=DEMO)
    assert out["pages_read"] == 8
    assert "[Pages 13-18]" in out["text"] and "[Pages 19-20]" in out["text"]
    assert quota["recorded"] == 4  # per group: the content check, then the copying
    quota["allowed"] = False
    with pytest.raises(HTTPException) as exc:
        await practice_router.demo_copy_quiz_source(_source(1), auth=DEMO)
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_copying_a_source_follows_the_photo_consent_rules(monkeypatch):
    cloud = StubClient("Q1.")
    _routing(monkeypatch, local=False, cloud="openai", cloud_client=cloud)
    with pytest.raises(HTTPException) as exc:
        await practice_router._copy_source(_source(1))
    assert exc.value.status_code == 409 and cloud.calls == []
    with pytest.raises(HTTPException) as exc:  # teachers never reach a cloud provider
        await practice_router.educator_copy_quiz_source(_source(1, route="cloud", cloud_consent=True), auth={"role": "educator"})
    assert exc.value.status_code == 422 and cloud.calls == []


@pytest.mark.asyncio
async def test_faith_subjects_cannot_be_copied_out_as_a_quiz_source(monkeypatch):
    from models.practice import QuizSourceRequest

    _routing(monkeypatch, local=True, cloud=None, local_client=StubClient("x"))
    with pytest.raises(HTTPException) as exc:
        await practice_router._copy_source(QuizSourceRequest(subject="scripture", pages=[PhotoPage(data=b64(JPEG))]))
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_copied_out_pages_reach_the_draft_and_count_as_photos_for_consent(monkeypatch, quota):
    cloud = StubClient(draft(q("2 + 2 =", "4", "computation")))
    _routing(monkeypatch, local=False, cloud="openai", cloud_client=cloud)
    monkeypatch.setattr(extract.settings, "practice_cloud_reading_enabled", False)
    with pytest.raises(HTTPException) as exc:  # the photo switch governs text copied from photos
        await practice_router.demo_generate_quiz(
            req(focus=None, source_pages_text="[Pages 1-6]\nQ1. 2+2", cloud_consent=True), auth=DEMO)
    assert exc.value.status_code == 409 and cloud.calls == []
    monkeypatch.setattr(extract.settings, "practice_cloud_reading_enabled", True)
    await practice_router.demo_generate_quiz(
        req(focus=None, source_pages_text="[Pages 1-6]\nQ1. 2+2", cloud_consent=True), auth=DEMO)
    assert "[Pages 1-6]" in cloud.calls[0]["messages"][0]["content"][-1]["text"]
