"""
Router-level wiring for AIUC-1 B005 (routers/tutor.py's chat()). Verifies
the classifier's should_block/category output actually drives the right
behavior at the endpoint: self_harm reuses the exact safeguarding crisis
path (audit event + distress alert), other blocking categories redirect
without a distress alert, prompt_injection-only never blocks, and a
classifier failure doesn't take the turn down (fails open end-to-end,
not just inside services/moderation.py).
"""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

import routers.tutor as tutor_module
from models.schemas import GradeStage, SessionConfig, Subject, TutorRequest
from routers.tutor import chat as tutor_chat

pytestmark = pytest.mark.asyncio


def _fake_request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 12345), "headers": [(b"user-agent", b"pytest")]})


def _req(message: str = "tell me about fractions") -> TutorRequest:
    return TutorRequest(
        session_config=SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery),
        current_subject=Subject.mathematics,
        conversation_history=[],
        child_message=message,
    )


@pytest.fixture
def created_tasks(monkeypatch):
    """The distress alert (like the audit log write) is fire-and-forget via
    asyncio.create_task — captured here so a test can await it before
    asserting, same technique as tests/test_audit_anomaly.py."""
    tasks = []
    orig_create_task = asyncio.create_task

    def _tracking(coro, *a, **kw):
        t = orig_create_task(coro, *a, **kw)
        tasks.append(t)
        return t

    monkeypatch.setattr(tutor_module.asyncio, "create_task", _tracking)
    return tasks


async def _run(monkeypatch, moderation_result: dict, stream_called: list, created_tasks: list):
    async def fake_classify(*args, **kwargs):
        return moderation_result

    async def fake_stream(*args, **kwargs):
        stream_called.append(True)
        yield '{"type": "text", "content": "Let\'s think about that."}'
        yield '{"type": "done"}'

    monkeypatch.setattr("routers.tutor.classify_child_message", fake_classify)
    monkeypatch.setattr("routers.tutor.stream_tutor_response", fake_stream)

    response = await tutor_chat(_req(), _fake_request(), auth={"role": "parent"}, db=None)
    chunks = [c async for c in response.body_iterator]
    await asyncio.gather(*created_tasks)
    return chunks


async def test_self_harm_flag_reuses_the_safeguarding_crisis_path(monkeypatch, created_tasks):
    alert_calls = []
    monkeypatch.setattr(
        "routers.tutor.send_distress_alert",
        AsyncMock(side_effect=lambda *a, **kw: alert_calls.append(a)),
    )
    stream_called = []
    chunks = await _run(
        monkeypatch,
        {"flagged": True, "categories": ["self_harm"], "confidence": "high", "should_block": True},
        stream_called,
        created_tasks,
    )

    assert "your safety matters most" in chunks[0]
    assert stream_called == []  # never reached the tutor
    assert len(alert_calls) == 1  # distress alert fired, same as the regex path


async def test_violence_flag_redirects_without_a_distress_alert(monkeypatch, created_tasks):
    alert_calls = []
    monkeypatch.setattr(
        "routers.tutor.send_distress_alert",
        AsyncMock(side_effect=lambda *a, **kw: alert_calls.append(a)),
    )
    stream_called = []
    chunks = await _run(
        monkeypatch,
        {"flagged": True, "categories": ["violence"], "confidence": "high", "should_block": True},
        stream_called,
        created_tasks,
    )

    assert "today's subject" in chunks[0]
    assert "your safety matters most" not in chunks[0]
    assert stream_called == []
    assert alert_calls == []  # not a personal-crisis signal — no distress email


async def test_prompt_injection_flag_alone_never_blocks(monkeypatch, created_tasks):
    stream_called = []
    chunks = await _run(
        monkeypatch,
        {"flagged": True, "categories": ["prompt_injection"], "confidence": "high", "should_block": False},
        stream_called,
        created_tasks,
    )

    assert stream_called == [True]  # reached the real tutor call
    assert any("Let's think about that" in c for c in chunks)


async def test_unflagged_message_passes_through_untouched(monkeypatch, created_tasks):
    stream_called = []
    chunks = await _run(
        monkeypatch,
        {"flagged": False, "categories": [], "confidence": "low", "should_block": False},
        stream_called,
        created_tasks,
    )
    assert stream_called == [True]


async def test_classifier_exception_fails_open_at_the_router_level(monkeypatch):
    """services/moderation.py already fails open internally — this tests
    the router's OWN try/except around the call (routers/tutor.py),
    deliberate belt-and-suspenders in case classify_child_message somehow
    still raised despite its own contract not to."""
    async def raising_classify(*args, **kwargs):
        raise RuntimeError("simulated moderation outage")

    async def fake_stream(*args, **kwargs):
        yield '{"type": "text", "content": "Cells."}'
        yield '{"type": "done"}'

    monkeypatch.setattr("routers.tutor.classify_child_message", raising_classify)
    monkeypatch.setattr("routers.tutor.stream_tutor_response", fake_stream)

    response = await tutor_chat(_req(), _fake_request(), auth={"role": "parent"}, db=None)
    chunks = [c async for c in response.body_iterator]

    # The router's own try/except around classify_child_message fails open
    # catches this and still ends with a recoverable {"type": "done"} —
    # never a hung connection or an unhandled 500.
    assert any('"type": "done"' in c for c in chunks)
