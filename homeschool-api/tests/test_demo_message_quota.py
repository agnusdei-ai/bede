"""
Router-level enforcement of core/demo_code_session.py's _MAX_MESSAGES_PER_CODE
(OWASP LLM10, "Unbounded Consumption") — the per-IP rate limit
(core/middleware.py) bounds REQUEST RATE, never aggregate spend, so nothing
previously stopped a single scripted demo session from running an unbounded
number of real model calls for its whole token lifetime. These tests verify
the actual enforcement point: routers/tutor.py's /chat and
routers/sandbox.py's /demo-chat must refuse an over-quota turn with a plain
message BEFORE calling the real model, never after.
"""
import json

import pytest
from starlette.requests import Request

import core.demo_code_session as demo_code_session
from core.audit import AuditEvent
from models.schemas import (
    GradeStage,
    SandboxDemoChatRequest,
    SessionConfig,
    Subject,
    TutorRequest,
)
from routers.sandbox import demo_chat
from routers.tutor import chat

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


def _fake_request() -> Request:
    scope = {
        "type": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [(b"user-agent", b"pytest")],
    }
    return Request(scope)


def _tutor_request() -> TutorRequest:
    return TutorRequest(
        session_config=SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery),
        current_subject=Subject.science,
        conversation_history=[],
        child_message="Where does a tree's mass come from?",
    )


async def _collect(response) -> list[str]:
    return [chunk async for chunk in response.body_iterator]


@pytest.fixture
def audit_events(monkeypatch):
    calls = []

    async def _fake_log_event(event, **kw):
        calls.append((event, kw))

    import routers.tutor as tutor_module
    import routers.sandbox as sandbox_module
    monkeypatch.setattr(tutor_module, "log_event", _fake_log_event)
    monkeypatch.setattr(sandbox_module, "log_event", _fake_log_event)
    return calls


async def test_chat_refuses_over_quota_demo_turn_without_calling_the_model(monkeypatch, audit_events):
    demo_code_session._MAX_MESSAGES_PER_CODE = 2
    try:
        code = await demo_code_session.generate_code(student_name="Ellie", grade="4")

        model_calls = []

        async def spy_stream(*args, **kwargs):
            model_calls.append(1)
            yield '{"type": "text", "content": "should never be reached"}'
            yield '{"type": "done"}'

        monkeypatch.setattr("routers.tutor.stream_tutor_response", spy_stream)

        # Two turns fit under the cap...
        for _ in range(2):
            response = await chat(_tutor_request(), _fake_request(), auth={"role": "demo_code", "code": code}, db=None)
            await _collect(response)
        assert len(model_calls) == 2

        # ...the third is refused before the model is ever called.
        response = await chat(_tutor_request(), _fake_request(), auth={"role": "demo_code", "code": code}, db=None)
        chunks = await _collect(response)

        assert len(model_calls) == 2, "an over-quota turn must never reach the model"
        assert any("reached its message limit" in c for c in chunks)
        assert any('"type": "done"' in c for c in chunks)

        rate_limited = [kw for event, kw in audit_events if event == AuditEvent.RATE_LIMITED]
        assert any(kw.get("detail") == "demo_message_quota" for kw in rate_limited)
    finally:
        demo_code_session._MAX_MESSAGES_PER_CODE = 400


async def test_chat_over_quota_message_is_localized(monkeypatch):
    demo_code_session._MAX_MESSAGES_PER_CODE = 1
    try:
        code = await demo_code_session.generate_code()

        async def spy_stream(*args, **kwargs):
            yield '{"type": "done"}'

        monkeypatch.setattr("routers.tutor.stream_tutor_response", spy_stream)

        await _collect(await chat(_tutor_request(), _fake_request(), auth={"role": "demo_code", "code": code}, db=None))

        response = await chat(
            _tutor_request(), _fake_request(),
            auth={"role": "demo_code", "code": code, "locale": "es"}, db=None,
        )
        chunks = [json.loads(c) for c in await _collect(response)]
        assert any("límite de mensajes" in c.get("content", "") for c in chunks)
    finally:
        demo_code_session._MAX_MESSAGES_PER_CODE = 400


async def test_chat_under_quota_demo_turn_is_unaffected(monkeypatch):
    code = await demo_code_session.generate_code()

    async def healthy_stream(*args, **kwargs):
        yield '{"type": "text", "content": "Cells."}'
        yield '{"type": "done"}'

    monkeypatch.setattr("routers.tutor.stream_tutor_response", healthy_stream)

    response = await chat(_tutor_request(), _fake_request(), auth={"role": "demo_code", "code": code}, db=None)
    chunks = await _collect(response)

    assert any("Cells." in c for c in chunks)
    assert (await demo_code_session.has_message_quota(code)) is True


async def test_demo_chat_refuses_over_quota_turn_without_calling_the_model(monkeypatch, audit_events):
    demo_code_session._MAX_MESSAGES_PER_CODE = 1
    try:
        code = await demo_code_session.generate_code()

        model_calls = []

        async def spy_stream(*args, **kwargs):
            model_calls.append(1)
            yield '{"type": "text", "content": "should never be reached"}'
            yield '{"type": "done"}'

        monkeypatch.setattr("routers.sandbox.stream_sandbox_response", spy_stream)

        req = SandboxDemoChatRequest(message="What is the capital of France?", conversation_history=[])

        first = await demo_chat(req, _fake_request(), auth={"role": "demo_code", "code": code})
        await _collect(first)
        assert len(model_calls) == 1

        second = await demo_chat(req, _fake_request(), auth={"role": "demo_code", "code": code})
        chunks = await _collect(second)

        assert len(model_calls) == 1, "an over-quota turn must never reach the model"
        assert any("reached its message limit" in c for c in chunks)
        assert any('"type": "done"' in c for c in chunks)

        rate_limited = [kw for event, kw in audit_events if event == AuditEvent.RATE_LIMITED]
        assert any("demo_message_quota" in str(kw.get("detail", "")) for kw in rate_limited)
    finally:
        demo_code_session._MAX_MESSAGES_PER_CODE = 400
