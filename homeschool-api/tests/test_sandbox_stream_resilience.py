"""
Real check that routers/sandbox.py's /chat and /demo-chat carry the same
AI_BACKEND_FAILURE reliability signal as routers/tutor.py's /chat (see
tests/test_tutor_stream_resilience.py and core/audit.py) — a parent
testing config in the sandbox, or a public-demo visitor, still
contributes to (and benefits from) the one shared "is Bede's AI backend
healthy" pattern, since both routes call through the same adapter layer.
"""
import asyncio

import pytest
from starlette.requests import Request

import routers.sandbox as sandbox_module
from core.audit import AuditEvent
from core.config import settings
from models.schemas import SandboxChatRequest, SandboxDemoChatRequest
from routers.sandbox import chat, demo_chat

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


def _fake_request() -> Request:
    scope = {
        "type": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [(b"user-agent", b"pytest")],
    }
    return Request(scope)


async def _collect(response) -> list[str]:
    return [chunk async for chunk in response.body_iterator]


@pytest.fixture
def audit_events(monkeypatch):
    calls = []
    monkeypatch.setattr(
        sandbox_module, "log_event_nowait",
        lambda event, **kwargs: calls.append((event, kwargs)),
    )
    return calls


@pytest.fixture(autouse=True)
def _sandbox_pin(monkeypatch):
    monkeypatch.setattr(settings, "sandbox_pin", "111222")


async def test_sandbox_chat_exception_logs_ai_backend_failure(monkeypatch, audit_events):
    async def erroring_stream(*args, **kwargs):
        yield '{"type": "text", "content": "So the tree"}'
        raise RuntimeError("simulated upstream failure")

    monkeypatch.setattr("routers.sandbox.stream_sandbox_response", erroring_stream)

    req = SandboxChatRequest(sandbox_pin="111222", message="test")
    response = await chat(req, _fake_request(), _={"role": "parent"})
    chunks = await _collect(response)

    assert any("went wrong" in c for c in chunks)
    failures = [kw for event, kw in audit_events if event == AuditEvent.AI_BACKEND_FAILURE]
    assert len(failures) == 1
    assert failures[0]["role"] == "parent"
    assert "cause=exception" in failures[0]["detail"]
    assert "RuntimeError" in failures[0]["detail"]


async def test_sandbox_chat_stall_logs_ai_backend_failure(monkeypatch, audit_events):
    # sandbox.py calls with_stall_timeout() without an explicit
    # timeout_seconds override (unlike routers/tutor.py's chat()), so its
    # default is bound to the real production STREAM_STALL_TIMEOUT_SECONDS
    # at import time — patching that module attribute after the fact
    # wouldn't change an already-bound default. Faking with_stall_timeout
    # itself to raise immediately exercises the same except-branch without
    # needing the real multi-second wait.
    async def _raises_timeout(agen, timeout_seconds=None):
        raise asyncio.TimeoutError()
        yield  # pragma: no cover - makes this a generator function

    monkeypatch.setattr("routers.sandbox.with_stall_timeout", _raises_timeout)

    async def never_called_stream(*args, **kwargs):
        yield '{"type": "done"}'

    monkeypatch.setattr("routers.sandbox.stream_sandbox_response", never_called_stream)

    req = SandboxChatRequest(sandbox_pin="111222", message="test")
    response = await chat(req, _fake_request(), _={"role": "parent"})
    chunks = await _collect(response)

    assert any("too long" in c for c in chunks)
    failures = [kw for event, kw in audit_events if event == AuditEvent.AI_BACKEND_FAILURE]
    assert len(failures) == 1
    assert "cause=stall" in failures[0]["detail"]


async def test_sandbox_chat_healthy_stream_never_logs_a_failure(monkeypatch, audit_events):
    async def healthy_stream(*args, **kwargs):
        yield '{"type": "text", "content": "Cells."}'
        yield '{"type": "done"}'

    monkeypatch.setattr("routers.sandbox.stream_sandbox_response", healthy_stream)

    req = SandboxChatRequest(sandbox_pin="111222", message="test")
    response = await chat(req, _fake_request(), _={"role": "parent"})
    await _collect(response)

    assert audit_events == []


async def test_sandbox_demo_chat_exception_logs_ai_backend_failure(monkeypatch, audit_events):
    async def erroring_stream(*args, **kwargs):
        yield '{"type": "text", "content": "So the tree"}'
        raise RuntimeError("simulated upstream failure")

    monkeypatch.setattr("routers.sandbox.stream_sandbox_response", erroring_stream)

    req = SandboxDemoChatRequest(message="test")
    response = await demo_chat(req, _fake_request(), auth={"role": "demo_code", "code": "nonexistent"})
    chunks = await _collect(response)

    assert any("went wrong" in c for c in chunks)
    failures = [kw for event, kw in audit_events if event == AuditEvent.AI_BACKEND_FAILURE]
    assert len(failures) == 1
    assert failures[0]["role"] == "demo_code"
    assert "subject=sandbox_demo" in failures[0]["detail"]
