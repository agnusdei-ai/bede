"""Who is told about a possible safety concern, once, and what happened
(services/safeguarding_alerts.py).

Every case uses mocked safety responses and a mocked mail transport. No real
picture is involved: the self-harm and sexual-content paths are driven by a
fake checker that answers the verdict, never by harmful imagery.
"""
import json

import pytest
from starlette.requests import Request

from core.audit import AuditEvent
from models.schemas import GradeStage, SessionConfig, Subject, TutorRequest
from routers import tutor as tutor_router
from services import content_screen, email_service, safeguarding_alerts
from tests.test_content_screen import SCREEN_MARK, ScreenClient, refuse
from tests.test_practice_coach import PNG, JPEG, b64

pytestmark = pytest.mark.real_content_screen


@pytest.fixture
def mail(monkeypatch):
    """A mail transport that records what it was asked to send."""
    sent = []

    async def send_email(to, subject, html_body, reply_to=None):
        sent.append({"to": to, "subject": subject, "html": html_body})
        return True

    monkeypatch.setattr(email_service, "email_configured", lambda: True)
    monkeypatch.setattr(email_service, "send_email", send_email)
    monkeypatch.setattr(safeguarding_alerts.settings, "parent_email", "parent@example.test")
    monkeypatch.setattr(safeguarding_alerts.settings, "school_safeguarding_email", "")
    monkeypatch.setattr(safeguarding_alerts.settings, "bede_location_id", "")
    return sent


@pytest.fixture
def audits(monkeypatch):
    import core.audit as audit

    seen = []

    async def log_event(event, **kw):
        seen.append((event, kw))

    monkeypatch.setattr(audit, "log_event", log_event)
    return seen


def _outcomes(audits):
    return [kw["detail"] for event, kw in audits if event == AuditEvent.SAFEGUARDING_ALERT]


async def _deliver(role="parent", student="Sam", source="picture-a", picture="self-harm"):
    return await safeguarding_alerts.deliver(
        role=role, student_name=student, trigger_excerpt=f"[picture: {picture}]",
        dedupe_source=source, picture=picture,
    )


# ── Routing ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_family_session_goes_to_the_parent(mail, audits):
    assert await _deliver(role="child") == "sent"
    assert [m["to"] for m in mail] == ["parent@example.test"]
    assert _outcomes(audits) == ["route=parent outcome=sent kind=picture"]


@pytest.mark.asyncio
async def test_a_teacher_led_session_goes_to_the_schools_route_never_the_parent(mail, audits, monkeypatch):
    monkeypatch.setattr(safeguarding_alerts.settings, "school_safeguarding_email", "safeguarding@school.test")
    assert await _deliver(role="educator") == "sent"
    assert [m["to"] for m in mail] == ["safeguarding@school.test"]
    assert _outcomes(audits) == ["route=school outcome=sent kind=picture"]


@pytest.mark.asyncio
async def test_school_mode_with_no_school_route_sends_nothing(mail, audits):
    """PARENT_EMAIL is set, and must still not be used: on a school
    deployment it is the operator's address, not the school's route."""
    assert await _deliver(role="educator") == "no_route"
    assert mail == []
    assert _outcomes(audits) == ["route=school outcome=no_route kind=picture"]


@pytest.mark.asyncio
async def test_a_campus_licensed_deployment_is_school_mode_for_every_role(mail, audits, monkeypatch):
    monkeypatch.setattr(safeguarding_alerts.settings, "bede_location_id", "synthetic-campus-1")
    assert safeguarding_alerts.route_for("child")[0] == "school"
    assert await _deliver(role="child") == "no_route"
    assert mail == []


# ── Duplicates ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_retried_concern_is_emailed_once(mail, audits):
    assert await _deliver(source="the-same-picture") == "sent"
    assert await _deliver(source="the-same-picture") == "duplicate"
    assert len(mail) == 1
    assert _outcomes(audits) == ["route=parent outcome=sent kind=picture",
                                 "route=parent outcome=duplicate kind=picture"]


@pytest.mark.asyncio
async def test_a_different_picture_or_learner_is_a_new_concern(mail, audits):
    await _deliver(source="picture-a")
    await _deliver(source="picture-b")
    await _deliver(source="picture-a", student="Ada")
    assert len(mail) == 3


@pytest.mark.asyncio
async def test_the_same_concern_alerts_again_after_the_window(mail, audits, monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(safeguarding_alerts.time, "monotonic", lambda: clock["now"])
    await _deliver()
    clock["now"] += safeguarding_alerts.DUPLICATE_WINDOW_SECONDS + 1
    await _deliver()
    assert len(mail) == 2


def test_only_a_digest_is_remembered(mail):
    import asyncio

    secret_picture = "iVBOR" + "A" * 200
    asyncio.run(_deliver(source=secret_picture))
    remembered = " ".join(safeguarding_alerts._recent)
    assert secret_picture not in remembered and "Sam" not in remembered
    assert all(len(k) == 64 for k in safeguarding_alerts._recent)


# ── Delivery failures ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_failed_send_is_recorded_and_can_be_retried(mail, audits, monkeypatch):
    async def fails(*a, **k):
        return False

    monkeypatch.setattr(email_service, "send_email", fails)
    assert await _deliver() == "failed"
    [(event, kw)] = [(e, kw) for e, kw in audits if e == AuditEvent.SAFEGUARDING_ALERT]
    assert kw["success"] is False and kw["detail"] == "route=parent outcome=failed kind=picture"
    # the failure is not remembered as sent, so a retry tries again
    monkeypatch.setattr(email_service, "send_email", mail_ok := _recorder(mail))
    assert await _deliver() == "sent"


def _recorder(sent):
    async def send_email(to, subject, html_body, reply_to=None):
        sent.append({"to": to, "subject": subject, "html": html_body})
        return True
    return send_email


@pytest.mark.asyncio
async def test_a_send_that_raises_never_breaks_the_turn(mail, audits, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("transport down")

    monkeypatch.setattr(email_service, "send_distress_alert", boom)
    assert await _deliver() == "failed"


@pytest.mark.asyncio
async def test_mail_not_configured_is_its_own_outcome(mail, audits, monkeypatch):
    monkeypatch.setattr(email_service, "email_configured", lambda: False)
    assert await _deliver() == "not_configured"
    assert mail == []


@pytest.mark.asyncio
async def test_the_audit_never_carries_the_address(mail, audits, monkeypatch):
    monkeypatch.setattr(safeguarding_alerts.settings, "school_safeguarding_email", "safeguarding@school.test")
    await _deliver(role="educator")
    await _deliver(role="child", source="other")
    assert "@" not in json.dumps([kw for _, kw in audits])


# ── The email itself ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_email_is_a_possible_concern_and_carries_no_image(mail, audits):
    picture = b64(PNG)
    await safeguarding_alerts.deliver(
        role="child", student_name="Sam", trigger_excerpt="[picture: sexual content]",
        dedupe_source=picture, picture="sexual content",
    )
    [message] = mail
    flat = " ".join(message["html"].split())
    assert message["subject"].startswith("Possible safety concern in Sam's Bede session")
    assert "possible concern, not a confirmed fact about Sam" in flat
    assert "The picture is not attached and was not kept." in flat
    assert picture[:40] not in message["html"] and "base64" not in message["html"]
    assert "<img" not in message["html"]


# ── Through the real chat route ──────────────────────────────────────────────

def _request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 1), "headers": [(b"user-agent", b"pytest")]})


def _turn(image):
    return TutorRequest(
        session_config=SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery),
        current_subject=Subject.science, conversation_history=[], child_message="Look!", drawing_image=image,
    )


async def _chat(monkeypatch, image, verdict, role="parent"):
    import asyncio
    import services.ai_service as ai_service

    async def no_flags(*a, **k):
        return {"flagged": False, "categories": [], "confidence": "low", "should_block": False}

    async def stream(*a, **k):
        yield json.dumps({"type": "text", "content": "Nice."})
        yield json.dumps({"type": "done"})

    tasks = []
    real_create = asyncio.create_task

    def track(coro, *a, **k):
        t = real_create(coro, *a, **k)
        tasks.append(t)
        return t

    monkeypatch.setattr(tutor_router.asyncio, "create_task", track)
    monkeypatch.setattr(tutor_router, "classify_child_message", no_flags)
    monkeypatch.setattr(tutor_router, "stream_tutor_response", stream)
    monkeypatch.setattr(ai_service, "_client", ScreenClient(verdict))
    response = await tutor_router.chat(_turn(image), _request(), auth={"role": role}, db=None)
    chunks = [json.loads(c) async for c in response.body_iterator]
    await asyncio.gather(*tasks, return_exceptions=True)
    return chunks


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ["self_harm", "sexual_content"])
async def test_a_retried_crisis_turn_emails_the_parent_once(monkeypatch, mail, audits, category):
    image = b64(JPEG)
    first = await _chat(monkeypatch, image, refuse(category))
    second = await _chat(monkeypatch, image, refuse(category))
    assert first[0]["content"] == second[0]["content"] == tutor_router.safeguarding_response("en")
    assert [m["to"] for m in mail] == ["parent@example.test"]
    assert _outcomes(audits) == ["route=parent outcome=sent kind=picture",
                                 "route=parent outcome=duplicate kind=picture"]


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ["not_schoolwork", "graphic_violence", "illicit", "mature"])
async def test_off_topic_or_other_unsafe_pictures_raise_no_safeguarding_email(monkeypatch, mail, audits, category):
    chunks = await _chat(monkeypatch, b64(PNG), refuse(category))
    assert chunks[0]["content"] == content_screen.refusal_message(category, "lesson")
    assert mail == [] and _outcomes(audits) == []


@pytest.mark.asyncio
async def test_a_crisis_picture_on_a_campus_deployment_follows_the_school_route(monkeypatch, mail, audits):
    monkeypatch.setattr(safeguarding_alerts.settings, "bede_location_id", "synthetic-campus-1")
    monkeypatch.setattr(safeguarding_alerts.settings, "school_safeguarding_email", "safeguarding@school.test")
    await _chat(monkeypatch, b64(PNG), refuse("self_harm"))
    assert [m["to"] for m in mail] == ["safeguarding@school.test"]


def test_the_screen_mark_is_still_the_rules_opening():
    assert content_screen._rules("lesson").startswith(SCREEN_MARK)


@pytest.mark.asyncio
async def test_two_different_crisis_pictures_with_the_same_words_are_two_concerns(monkeypatch, mail, audits):
    """The route keys a picture concern on the picture, not the child's
    message, so "Look!" with a second picture is not taken for a retry."""
    await _chat(monkeypatch, b64(PNG), refuse("self_harm"))
    await _chat(monkeypatch, b64(JPEG), refuse("self_harm"))
    assert len(mail) == 2
