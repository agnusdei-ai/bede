"""
Real check for routers/tutor.py's /chat stream resilience — a Fable-adjacent
instability report (Science subject freezing mid-conversation, spinner
never resolving) traced to two gaps: no timeout around the Anthropic
streaming call, and no try/except around event_generator's consumption of
it, so an upstream stall or any other mid-stream exception used to leave
the SSE connection open with no {"type": "done"} ever sent — the child's
own reader.read() then waits forever with nothing to time it out either
(see the matching client-side fix in services/api.ts's parseSSEStream).

Verifies the fix at the router level: however stream_tutor_response fails
(hangs past the stall timeout, or raises outright), /chat's event_generator
must still terminate with a real, recoverable {"type": "done"} the child's
UI can act on — never an unhandled exception, never a hang.
"""
import asyncio

import pytest
from starlette.requests import Request

import core.sse_utils as sse_utils
from models.schemas import GradeStage, SessionConfig, Subject, TutorRequest
from routers.tutor import chat

pytestmark = pytest.mark.asyncio


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


@pytest.fixture(autouse=True)
def _low_stall_timeout(monkeypatch):
    """Real end-to-end timeout would make this test take 45s — the
    production value is exercised directly in test_sse_utils.py instead."""
    monkeypatch.setattr(sse_utils, "STREAM_STALL_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr("routers.tutor.STREAM_STALL_TIMEOUT_SECONDS", 0.05)


async def test_a_stalled_upstream_stream_still_ends_with_a_recoverable_done(monkeypatch):
    async def stalling_stream(*args, **kwargs):
        yield '{"type": "text", "content": "Let\'s think about"}'
        await asyncio.sleep(1.0)  # far past the 0.05s test timeout
        yield '{"type": "done"}'  # never reached

    monkeypatch.setattr("routers.tutor.stream_tutor_response", stalling_stream)

    response = await chat(_tutor_request(), _fake_request(), auth={"role": "parent"}, db=None)
    chunks = await _collect(response)

    assert '"type": "text", "content": "Let\'s think about"' in chunks[0]
    assert any('"type": "done"' in c for c in chunks)
    assert any("too long" in c for c in chunks)


async def test_an_exception_mid_stream_still_ends_with_a_recoverable_done(monkeypatch):
    async def erroring_stream(*args, **kwargs):
        yield '{"type": "text", "content": "So the tree"}'
        raise RuntimeError("simulated upstream failure")

    monkeypatch.setattr("routers.tutor.stream_tutor_response", erroring_stream)

    response = await chat(_tutor_request(), _fake_request(), auth={"role": "parent"}, db=None)
    chunks = await _collect(response)

    assert '"type": "text", "content": "So the tree"' in chunks[0]
    assert any('"type": "done"' in c for c in chunks)
    assert any("went wrong" in c for c in chunks)


async def test_a_healthy_stream_is_unaffected_by_the_stall_guard(monkeypatch):
    async def healthy_stream(*args, **kwargs):
        yield '{"type": "text", "content": "Cells."}'
        yield '{"type": "done"}'

    monkeypatch.setattr("routers.tutor.stream_tutor_response", healthy_stream)

    response = await chat(_tutor_request(), _fake_request(), auth={"role": "parent"}, db=None)
    chunks = await _collect(response)

    assert chunks == ['{"type": "text", "content": "Cells."}', '{"type": "done"}']
