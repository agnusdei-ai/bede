"""
Pre-deployment adversarial-testing pass (docs/SECURITY.md) over
check_safeguarding()/safeguarding_response() (services/ai_service.py) —
the deterministic, pre-Claude crisis-signal check that bypasses the LLM
entirely for distress/danger language. Had zero prior test coverage
despite being the most safety-critical deterministic check in the app.

The finding this suite exists to guard against: the app supports a real,
live Spanish-locale session (LOCALE=es, docs/LOCALIZATION.md), but this
check was English-only — a Spanish-speaking child's actual distress or
danger language would never have triggered it, and even if it somehow had
(inherited from a future locale-agnostic pattern), the fixed response text
was English-only too, the worst possible moment to hand a child a reply in
a language they read less fluently than the one they just reached for.
"""
import pytest
from starlette.requests import Request

from models.schemas import GradeStage, SessionConfig, Subject, TutorRequest
from routers.tutor import chat as tutor_chat
from services.ai_service import check_safeguarding, safeguarding_response, SAFEGUARDING_RESPONSE


# ── English (regression coverage — pre-existing behavior, never tested before) ──

@pytest.mark.parametrize("message", [
    "you're hurting me",
    "my brother keeps hitting me",
    "he beats me every night",
    "I want to kill myself",
    "I want to hurt myself",
    "I've been cutting myself",
    "I'm not safe here",
    "I don't feel safe at home",
    "I was abused by someone I trust",
    "she hurt me really badly",
])
def test_english_crisis_language_triggers_safeguarding(message):
    assert check_safeguarding(message) is True


@pytest.mark.parametrize("message", [
    "What is 7 times 8?",
    "Can you help me with my narration for history?",
    "I scraped my knee playing outside",
    "The Romans were beaten in that battle by the Gauls.",
    "My character in the story wants to hurt the villain.",
    "Tell me about the Civil War.",
])
def test_ordinary_lesson_text_does_not_trigger_safeguarding(message):
    assert check_safeguarding(message) is False


# ── Spanish (the fix) ────────────────────────────────────────────────────────

@pytest.mark.parametrize("message", [
    "me lastima mucho",
    "mi papá me pega todos los días",
    "me golpean en casa",
    "quiero morir",
    "quiero matarme",
    "quiero hacerme daño",
    "estoy pensando en matarme",
    "he estado cortarme",
    "no estoy segura en mi casa",
    "no me siento segura",
    "me abusaron cuando era pequeña",
    "fui violada",
    "me hizo daño mi tío",
])
def test_spanish_crisis_language_triggers_safeguarding(message):
    assert check_safeguarding(message) is True


@pytest.mark.parametrize("message", [
    "¿Cuánto es siete por ocho?",
    "me tocó a mí jugar primero",  # ordinary "it was my turn" idiom — must not misfire
    "los romanos golpearon a los galos en esa batalla",
    "ayúdame con mi narración de historia",
])
def test_ordinary_spanish_lesson_text_does_not_trigger_safeguarding(message):
    assert check_safeguarding(message) is False


# ── safeguarding_response() locale selection ────────────────────────────────

def test_safeguarding_response_defaults_to_english():
    assert safeguarding_response() == SAFEGUARDING_RESPONSE
    assert safeguarding_response("en") == SAFEGUARDING_RESPONSE


def test_safeguarding_response_returns_spanish_for_es_locale():
    text = safeguarding_response("es")
    assert text != SAFEGUARDING_RESPONSE
    assert "seguridad" in text.lower()


def test_safeguarding_response_falls_back_to_english_for_unknown_locale():
    """A locale without a translation yet must still return a real, correct
    answer — just not in the child's own language — never raise or return
    something empty."""
    assert safeguarding_response("it") == SAFEGUARDING_RESPONSE
    assert safeguarding_response("pl") == SAFEGUARDING_RESPONSE
    assert safeguarding_response("not-a-real-locale") == SAFEGUARDING_RESPONSE


# ── End-to-end: the actual /tutor/chat path picks the right language ───────


def _fake_request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 12345), "headers": [(b"user-agent", b"pytest")]})


@pytest.mark.asyncio
async def test_tutor_chat_router_returns_spanish_safeguarding_response_for_es_locale():
    req = TutorRequest(
        session_config=SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery),
        current_subject=Subject.mathematics,
        conversation_history=[],
        child_message="quiero matarme",
    )
    response = await tutor_chat(req, _fake_request(), auth={"role": "parent", "locale": "es"}, db=None)
    chunks = [c async for c in response.body_iterator]

    assert "seguridad" in chunks[0].lower()


@pytest.mark.asyncio
async def test_tutor_chat_router_defaults_to_english_when_auth_has_no_locale_claim():
    """Older tokens issued before the locale claim existed must still work."""
    req = TutorRequest(
        session_config=SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery),
        current_subject=Subject.mathematics,
        conversation_history=[],
        child_message="I want to kill myself",
    )
    response = await tutor_chat(req, _fake_request(), auth={"role": "parent"}, db=None)
    chunks = [c async for c in response.body_iterator]

    assert "your safety matters most" in chunks[0]
