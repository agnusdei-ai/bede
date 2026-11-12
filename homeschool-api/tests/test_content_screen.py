"""Every uploaded picture is checked before Bede reads it
(services/content_screen.py).

The model is stubbed with a fake that answers the content check with a chosen
verdict and any other call with a reading, so the check, the routing, the
refusal, the audit and the "nothing was read" guarantee all run for real
through the real route functions. Each upload path is driven: a parent's
worksheet, the demo's, a parent's quiz draft and source, a teacher's draft,
source, quiz and student work, and a lesson photo in the chat.
"""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.requests import Request

from core.audit import _ANOMALY_RULES, AuditEvent
from core.database import PracticeAssessment
from core.deps import require_educator
from models.practice import GenerateQuizRequest, PhotoPage, QuizSourceRequest, ReadPhotosRequest
from models.schemas import GradeStage, SessionConfig, Subject, TutorRequest
from routers import practice as practice_router
from routers import tutor as tutor_router
from services import content_screen
from services.practice import extract
from tests.test_practice_coach import GOLDEN, JPEG, PNG, PARENT, _Reply, _routing, b64, db  # noqa: F401
from tests.test_teacher_quiz import APPROVED

pytestmark = pytest.mark.real_content_screen

DEMO = {"role": "demo_code", "code": "synthetic-demo"}
SCREEN_MARK = "You check pictures before a K-8 school app"
READING = json.dumps(GOLDEN["assessment"])


class ScreenClient:
    """Answers the content check with `verdict` (a reply, or an exception to
    raise) and every other call with `reading`."""

    def __init__(self, verdict, reading=READING):
        self.verdict, self.reading = verdict, reading
        self.calls = []
        self.messages = self

    def screens(self):
        return [c for c in self.calls if SCREEN_MARK in c.get("system", "")]

    def readings(self):
        return [c for c in self.calls if SCREEN_MARK not in c.get("system", "")]

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if SCREEN_MARK in kwargs.get("system", ""):
            if isinstance(self.verdict, Exception):
                raise self.verdict
            return _Reply(self.verdict)
        return _Reply(self.reading)


OK = '{"verdict": "ok"}'


def refuse(category):
    return json.dumps({"verdict": "refuse", "category": category})


@pytest.fixture
def audited(monkeypatch):
    import core.audit as audit

    seen = []
    monkeypatch.setattr(audit, "log_event_nowait", lambda event, **kw: seen.append((event, kw)))
    return seen


@pytest.fixture
def quota(monkeypatch):
    import core.demo_code_session as session

    calls = {"recorded": 0}

    async def has(code):
        return True

    async def record(code):
        calls["recorded"] += 1

    monkeypatch.setattr(session, "has_message_quota", has)
    monkeypatch.setattr(session, "record_message", record)
    return calls


def _pages(n=2):
    return [PhotoPage(data=b64(PNG)), PhotoPage(data=b64(JPEG))][:n] if n <= 2 else [PhotoPage(data=b64(PNG))] * n


# ── The verdict ──────────────────────────────────────────────────────────────

def test_a_clear_ok_passes_and_each_category_refuses():
    assert content_screen.parse_verdict('{"verdict": "ok"}') is None
    assert content_screen.parse_verdict(' ```json\n{"verdict":"ok"}\n``` ') is None
    for category in content_screen.REFUSAL_CATEGORIES:
        assert content_screen.parse_verdict(refuse(category)) == category


@pytest.mark.parametrize("reply", [
    "", "Looks fine to me.", "ok", '{"verdict": "fine"}', '{"verdict": "refuse"}',
    '{"verdict": "refuse", "category": "spooky"}', '{"verdict": "ok", "category": "sexual_content"}',
    '{"verdict": "ok"} {"verdict": "refuse", "category": "illicit"}', '["ok"]', '{"verdict": ',
])
def test_anything_unclear_fails_closed(reply):
    with pytest.raises(content_screen.ScreeningUnavailable):
        content_screen.parse_verdict(reply)


def test_the_unsafe_categories_are_the_ones_the_owner_named():
    # illicit, pornographic, violent, mature-rated, and self-harm; plus
    # not-schoolwork, which is refused for a worksheet but is not a safety matter.
    assert set(content_screen.UNSAFE_CATEGORIES) == {
        "self_harm", "sexual_content", "graphic_violence", "illicit", "mature"}
    # Both are safeguarding signals from a child (owner rulings 2026-11-11).
    assert set(content_screen.CRISIS_CATEGORIES) == {"self_harm", "sexual_content"}
    assert set(content_screen.REFUSAL_CATEGORIES) - set(content_screen.UNSAFE_CATEGORIES) == {"not_schoolwork"}


def test_the_rules_name_every_category_and_keep_ordinary_school_material():
    for context in ("worksheet", "lesson"):
        rules = content_screen._rules(context)
        for category in content_screen.REFUSAL_CATEGORIES:
            assert f"- {category}:" in rules
        assert "history page" in rules and "science lesson" in rules  # hard subjects are school material
        # a cartoon or an animation is judged by what it shows, like a photo
        assert "cartoon" in rules and "animation" in rules
        assert rules.index("- self_harm:") < rules.index("- sexual_content:")  # the most serious first
    assert "selfies" in content_screen._rules("worksheet")
    assert "pet" in content_screen._rules("lesson")  # a nature-study photo is a lesson


@pytest.mark.asyncio
async def test_the_pictures_go_to_the_client_it_was_given_and_nothing_else():
    client = ScreenClient(OK)
    await content_screen.screen_images(client, [("image/png", "iVBORdata"), ("image/png", "iVBORmore")], "worksheet")
    (call,) = client.calls
    images = [b for b in call["messages"][0]["content"] if b["type"] == "image"]
    assert [b["source"]["data"] for b in images] == ["iVBORdata", "iVBORmore"]
    assert "temperature" not in call  # the Anthropic SDK refuses it client-side


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("down"), TimeoutError()])
async def test_a_check_that_cannot_run_refuses(monkeypatch, failure):
    if isinstance(failure, TimeoutError):
        import asyncio

        async def slow(**kwargs):
            await asyncio.sleep(1)

        client = ScreenClient(OK)
        client.create = slow
        monkeypatch.setattr(content_screen, "SCREEN_TIMEOUT_SECONDS", 0.01)
    else:
        client = ScreenClient(failure)
    with pytest.raises(content_screen.ScreeningUnavailable):
        await content_screen.screen_images(client, [("image/png", "iVBOR")], "lesson")


def test_a_lesson_photo_is_labelled_with_its_real_type():
    assert content_screen.media_type_of(b64(JPEG)) == "image/jpeg"
    assert content_screen.media_type_of(b64(PNG)) == "image/png"


# ── Every practice upload path ────────────────────────────────────────────────

async def _parent_read(db):
    return await practice_router.read_assessment("Alice", ReadPhotosRequest(subject="latin", pages=_pages()),
                                                 auth=PARENT, db=db)


async def _demo_read(db):
    return await practice_router.demo_read_assessment(ReadPhotosRequest(subject="latin", pages=_pages()), auth=DEMO)


def _draft(**kw):
    return GenerateQuizRequest(subject="mathematics", grade="3", focus=None, question_count=3, pages=_pages(), **kw)


async def _parent_draft(db):
    return await practice_router.generate_quiz("Alice", _draft(), auth=PARENT, db=db)


async def _demo_draft(db):
    return await practice_router.demo_generate_quiz(_draft(), auth=DEMO)


async def _teacher_draft(db):
    return await practice_router.educator_generate_quiz(_draft(), auth={"role": "educator", "sub": "t"})


def _source():
    return QuizSourceRequest(subject="mathematics", pages=_pages())


async def _parent_source(db):
    return await practice_router.copy_quiz_source("Alice", _source(), auth=PARENT, db=db)


async def _demo_source(db):
    return await practice_router.demo_copy_quiz_source(_source(), auth=DEMO)


async def _teacher_source(db):
    return await practice_router.educator_copy_quiz_source(_source(), auth={"role": "educator", "sub": "t"})


PATHS = [_parent_read, _demo_read, _parent_draft, _demo_draft, _teacher_draft,
         _parent_source, _demo_source, _teacher_source]


def _route(monkeypatch, client):
    monkeypatch.setattr(extract.settings, "practice_cloud_reading_enabled", True)
    _routing(monkeypatch, local=True, cloud=None, local_client=client)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.__name__)
@pytest.mark.parametrize("category", content_screen.REFUSAL_CATEGORIES)
async def test_a_refused_upload_is_never_read_or_kept(monkeypatch, db, quota, audited, path, category):
    client = ScreenClient(refuse(category))
    _route(monkeypatch, client)
    with pytest.raises(HTTPException) as exc:
        await path(db)
    assert exc.value.status_code == 422
    assert str(exc.value.detail) == content_screen.refusal_message(category, "worksheet")
    assert len(client.screens()) == 1 and client.readings() == []
    assert (await db.execute(select(PracticeAssessment))).scalars().all() == []
    refusals = [kw for event, kw in audited if event == AuditEvent.UPLOAD_REFUSED]
    if category in content_screen.UNSAFE_CATEGORIES:
        assert [r["detail"] for r in refusals] == [f"category={category} surface=worksheet"]
    else:
        assert refusals == []  # not schoolwork is refused, but is not a safety event


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.__name__)
async def test_an_upload_that_cannot_be_checked_is_not_read(monkeypatch, db, quota, path):
    client = ScreenClient("I think it's fine")
    _route(monkeypatch, client)
    with pytest.raises(HTTPException) as exc:
        await path(db)
    assert exc.value.status_code == 503 and client.readings() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.__name__)
async def test_a_clean_upload_is_checked_once_per_group_then_read(monkeypatch, db, quota, path):
    client = ScreenClient(OK)
    _route(monkeypatch, client)
    try:
        await path(db)
    except HTTPException as exc:
        # A draft cannot be made from this fake's worksheet-shaped reply (a
        # 502), but it is never refused or left unchecked.
        assert exc.status_code == 502, exc.detail
    assert len(client.screens()) == 1
    assert client.calls[0] is client.screens()[0]  # the check comes before anything is read
    assert client.readings(), "the pages were read after passing the check"


@pytest.mark.asyncio
async def test_a_refusal_in_a_later_group_refuses_the_whole_upload(monkeypatch, db, audited):
    verdicts = [OK, refuse("graphic_violence")]

    class Later(ScreenClient):
        async def create(self, **kwargs):
            if SCREEN_MARK in kwargs.get("system", ""):
                self.verdict = verdicts.pop(0)
            return await super().create(**kwargs)

    client = Later(OK)
    _route(monkeypatch, client)
    req = ReadPhotosRequest(subject="latin", pages=[PhotoPage(data=b64(PNG))] * 8)
    with pytest.raises(HTTPException) as exc:
        await practice_router.read_assessment("Alice", req, auth=PARENT, db=db)
    assert exc.value.status_code == 422
    assert len(client.screens()) == 2 and len(client.readings()) == 1  # the first group only
    assert (await db.execute(select(PracticeAssessment))).scalars().all() == []


@pytest.mark.asyncio
async def test_the_demo_is_charged_for_the_check(monkeypatch, quota):
    client = ScreenClient(OK)
    _route(monkeypatch, client)
    await practice_router.demo_read_assessment(ReadPhotosRequest(subject="latin", pages=_pages()), auth=DEMO)
    assert quota["recorded"] == len(client.calls) == 2


@pytest.fixture
def teacher_http(monkeypatch):
    app = FastAPI()
    app.include_router(practice_router.router)
    app.dependency_overrides[require_educator] = lambda: {"role": "educator", "sub": "teacher-1"}
    with TestClient(app) as http:
        yield http


@pytest.mark.parametrize("call", ["extract", "score"])
def test_a_teachers_quiz_and_student_work_are_checked_over_http(monkeypatch, teacher_http, audited, call):
    client = ScreenClient(refuse("sexual_content"))
    _routing(monkeypatch, local=True, cloud=None, local_client=client)
    pages = [{"data": b64(JPEG)}]
    if call == "extract":
        body = {"subject": "mathematics", "grade": "4", "pages": pages, "upload_consent": True}
    else:
        body = {"quiz": APPROVED, "pages": pages, "upload_consent": True}
    out = teacher_http.post(f"/practice/educator/teacher-quiz/{call}", json=body,
                            headers={"user-agent": "synthetic-teacher-browser"})
    assert out.status_code == 422, out.text
    assert client.readings() == []
    (refusal,) = [kw for event, kw in audited if event == AuditEvent.UPLOAD_REFUSED]
    assert refusal["detail"] == "category=sexual_content surface=worksheet"
    assert refusal["user_agent"] == "synthetic-teacher-browser"  # who sent it, bound by the router


def test_only_the_screened_wrapper_hands_pages_to_a_model():
    """`page_groups` rebuilds pages but does not check them. Anything that
    calls it except `screened_page_groups` is an unchecked upload path."""
    import ast

    root = Path(__file__).resolve().parents[1]
    callers = set()
    for path in [*root.glob("services/**/*.py"), *root.glob("routers/**/*.py")]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Call):
                    f = node.func
                    name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                    if name == "page_groups":
                        callers.add(f"{path.relative_to(root)}::{fn.name}")
    assert callers == {
        "services/practice/extract.py::screened_page_groups",
        "services/practice/upload_safety.py::prepare_pages",  # no route calls it (next test)
    }, callers


def test_prepare_pages_is_not_reachable_from_any_route():
    root = Path(__file__).resolve().parents[1]
    for path in [*root.glob("services/**/*.py"), *root.glob("routers/**/*.py")]:
        if path.name == "upload_safety.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert "prepare_pages(" not in text, path


# ── A lesson photo or drawing in the chat ──────────────────────────────────────

def _request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 1), "headers": [(b"user-agent", b"pytest")]})


def _turn(image):
    return TutorRequest(
        session_config=SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery),
        current_subject=Subject.science, conversation_history=[], child_message="Look!", drawing_image=image,
    )


@pytest.fixture
def tutor(monkeypatch):
    import services.ai_service as ai_service

    async def no_flags(*a, **k):
        return {"flagged": False, "categories": [], "confidence": "low", "should_block": False}

    reached = []

    async def stream(*args, **kwargs):
        reached.append(kwargs.get("drawing_image"))
        yield json.dumps({"type": "text", "content": "What a lovely leaf."})
        yield json.dumps({"type": "done"})

    monkeypatch.setattr(tutor_router, "classify_child_message", no_flags)
    monkeypatch.setattr(tutor_router, "stream_tutor_response", stream)

    def use(client):
        monkeypatch.setattr(ai_service, "_client", client)
        return reached

    return use


async def _chunks(response):
    return [json.loads(c) for c in [chunk async for chunk in response.body_iterator]]


@pytest.mark.asyncio
@pytest.mark.parametrize("category", content_screen.REFUSAL_CATEGORIES)
async def test_a_refused_lesson_picture_never_reaches_the_tutor(tutor, audited, category):
    client = ScreenClient(refuse(category))
    reached = tutor(client)
    response = await tutor_router.chat(_turn(b64(JPEG)), _request(), auth={"role": "parent"}, db=None)
    chunks = await _chunks(response)
    assert reached == []
    expected = (tutor_router.safeguarding_response("en") if category in content_screen.CRISIS_CATEGORIES
                else content_screen.refusal_message(category, "lesson"))
    assert chunks == [{"type": "text", "content": expected}, {"type": "done"}]
    (call,) = client.calls
    image = call["messages"][0]["content"][0]
    assert image["source"]["media_type"] == "image/jpeg" and SCREEN_MARK in call["system"]
    refusals = [kw for event, kw in audited if event == AuditEvent.UPLOAD_REFUSED]
    if category in content_screen.UNSAFE_CATEGORIES:
        assert [(r["detail"], r["student_name"], r["role"]) for r in refusals] == [
            (f"category={category} surface=lesson", "Sam", "parent")]
    else:
        assert refusals == []


@pytest.mark.asyncio
async def test_a_lesson_picture_that_cannot_be_checked_is_not_sent(tutor):
    reached = tutor(ScreenClient(RuntimeError("down")))
    response = await tutor_router.chat(_turn(b64(PNG)), _request(), auth={"role": "parent"}, db=None)
    chunks = await _chunks(response)
    assert reached == []
    assert chunks[0]["content"] == content_screen.unavailable_message("lesson")


@pytest.mark.asyncio
async def test_a_spanish_lesson_is_refused_in_spanish(tutor):
    tutor(ScreenClient(refuse("mature")))
    response = await tutor_router.chat(_turn(b64(PNG)), _request(), auth={"role": "parent", "locale": "es"}, db=None)
    chunks = await _chunks(response)
    assert chunks[0]["content"] == content_screen.refusal_message("mature", "lesson", "es")
    assert "Bede no puede" in chunks[0]["content"]


@pytest.mark.asyncio
async def test_a_clean_lesson_picture_reaches_the_tutor_and_a_turn_without_one_is_not_checked(tutor):
    client = ScreenClient(OK)
    reached = tutor(client)
    image = b64(PNG)
    chunks = await _chunks(await tutor_router.chat(_turn(image), _request(), auth={"role": "parent"}, db=None))
    assert reached == [image] and chunks[0]["content"] == "What a lovely leaf."
    client.calls.clear()
    await _chunks(await tutor_router.chat(_turn(None), _request(), auth={"role": "parent"}, db=None))
    assert client.calls == [] and reached == [image, None]


@pytest.fixture
def safeguarding(monkeypatch):
    raised = {"audit": [], "alerts": []}

    async def log_event(event, **kw):
        if event == AuditEvent.SAFEGUARDING:
            raised["audit"].append(kw)

    async def alert(student, when, excerpt, picture=None):
        raised["alerts"].append((student, excerpt, picture))
        return True

    monkeypatch.setattr(tutor_router, "log_event", log_event)
    monkeypatch.setattr(tutor_router, "send_distress_alert", alert)
    return raised


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", ["en", "es"])
@pytest.mark.parametrize("category,label", [("self_harm", "self-harm"), ("sexual_content", "sexual content")])
async def test_a_crisis_picture_alerts_the_parent_straight_away(tutor, audited, safeguarding, locale,
                                                                category, label):
    """Even a cartoon: a child's picture showing self-harm or sexual content
    is a safeguarding signal, answered exactly as a child writing about
    self-harm is, with the parent emailed at once."""
    import asyncio

    reached = tutor(ScreenClient(refuse(category)))
    response = await tutor_router.chat(
        _turn(b64(PNG)), _request(), auth={"role": "parent", "locale": locale}, db=None)
    chunks = await _chunks(response)
    await asyncio.sleep(0)  # the parent alert is sent without holding up the reply
    assert reached == []
    assert chunks == [{"type": "text", "content": tutor_router.safeguarding_response(locale)}, {"type": "done"}]
    assert [(a["student_name"], a["detail"]) for a in safeguarding["audit"]] == [
        ("Sam", f"trigger(picture):[picture: {label}]")]
    assert safeguarding["alerts"] == [("Sam", f"[picture: {label}]", label)]
    assert [kw["detail"] for event, kw in audited if event == AuditEvent.UPLOAD_REFUSED] == [
        f"category={category} surface=lesson"]


@pytest.mark.asyncio
@pytest.mark.parametrize("category", [c for c in content_screen.REFUSAL_CATEGORIES
                                      if c not in content_screen.CRISIS_CATEGORIES])
async def test_other_refused_pictures_do_not_raise_a_safeguarding_alert(tutor, audited, safeguarding, category):
    tutor(ScreenClient(refuse(category)))
    await _chunks(await tutor_router.chat(_turn(b64(PNG)), _request(), auth={"role": "parent"}, db=None))
    assert safeguarding == {"audit": [], "alerts": []}


def test_the_parents_email_says_a_picture_was_sent_and_not_kept():
    from services.email_service import build_distress_alert_html

    body = build_distress_alert_html("Sam", "2026-11-11T21:00:00Z", "[picture: sexual content]",
                                     picture="sexual content")
    assert "sent Bede a picture that appeared to show sexual content" in body
    assert "The picture was not kept." in body and "What Sam said" not in body
    said = build_distress_alert_html("Sam", "2026-11-11T21:00:00Z", "I want to hurt myself")
    assert "What Sam said" in said and "picture" not in said  # a message alert is unchanged


def test_a_self_harm_worksheet_says_so_and_points_to_help():
    message = content_screen.refusal_message("self_harm", "worksheet")
    assert "self-harm" in message and "talk with them" in message


def test_refusals_alert_a_parent_on_the_same_terms_as_flagged_text():
    assert _ANOMALY_RULES[AuditEvent.UPLOAD_REFUSED] == _ANOMALY_RULES[AuditEvent.MODERATION_FLAGGED]
