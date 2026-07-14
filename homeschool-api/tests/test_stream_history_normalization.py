"""
Real check that stream_tutor_response and stream_sandbox_response actually
apply _normalize_alternating_roles to the messages sent to the Anthropic
API, not just that the pure function works in isolation (see
test_normalize_alternating_roles.py). Captures the exact `messages` kwarg
the code passes to _client.messages.stream(...) and asserts it strictly
alternates roles.
"""
import json
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from anthropic.types import RawContentBlockDeltaEvent, RawContentBlockStartEvent, RawContentBlockStopEvent

from models.schemas import ChatMessage, GradeStage, SessionConfig, Subject
from services import ai_service


class _FakeStream:
    def __init__(self, events):
        self._events = events

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        for event in self._events:
            yield event


def _text_events(text: str = "ok"):
    yield RawContentBlockStartEvent.model_validate(
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
    )
    yield RawContentBlockDeltaEvent.model_validate(
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}
    )
    yield RawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": 0})


def _capturing_stream(captured: dict):
    @asynccontextmanager
    async def _fake(**kwargs):
        captured["messages"] = kwargs["messages"]
        yield _FakeStream(list(_text_events()))
    return _fake


def _config() -> SessionConfig:
    return SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery)


def _strictly_alternates(messages: list[dict]) -> bool:
    return all(a["role"] != b["role"] for a, b in zip(messages, messages[1:]))


@pytest.mark.asyncio
async def test_tutor_stream_normalizes_a_consecutive_assistant_history_before_calling_the_api():
    """The exact shape the [CONTINUE] gap produces (see
    scripts/bugcatcher.mts's S5 scenario, both apps): client-supplied
    history with two assistant turns in a row, immediately followed by the
    child's real next message."""
    history = [
        ChatMessage(role="user", content="12!"),
        ChatMessage(role="assistant", content="Exactly right, 12."),
        ChatMessage(role="assistant", content="Are you still there?"),
    ]
    captured: dict = {}
    with patch.object(ai_service._client.messages, "stream", side_effect=_capturing_stream(captured)):
        async for _ in ai_service.stream_tutor_response(
            config=_config(),
            subject=Subject.mathematics,
            history=history,
            child_message="Sorry, I'm back!",
        ):
            pass

    sent = captured["messages"]
    assert _strictly_alternates(sent), f"consecutive same-role turns sent to the API: {sent}"
    # The merge preserved both original assistant lines, just joined
    assert any("Exactly right, 12." in m["content"] and "Are you still there?" in m["content"] for m in sent if isinstance(m["content"], str))


@pytest.mark.asyncio
async def test_sandbox_stream_also_normalizes_consecutive_same_role_history():
    history = [
        ChatMessage(role="assistant", content="First reply."),
        ChatMessage(role="assistant", content="Second reply, no user turn between."),
    ]
    captured: dict = {}
    with patch.object(ai_service._client.messages, "stream", side_effect=_capturing_stream(captured)):
        async for _ in ai_service.stream_sandbox_response(
            conversation_history=history,
            message="A new question",
            custom_instructions="",
        ):
            pass

    sent = captured["messages"]
    assert _strictly_alternates(sent), f"consecutive same-role turns sent to the API: {sent}"


@pytest.mark.asyncio
async def test_a_normal_alternating_history_is_sent_unchanged():
    history = [
        ChatMessage(role="user", content="Hi"),
        ChatMessage(role="assistant", content="Hello"),
    ]
    captured: dict = {}
    with patch.object(ai_service._client.messages, "stream", side_effect=_capturing_stream(captured)):
        async for _ in ai_service.stream_tutor_response(
            config=_config(),
            subject=Subject.living_books,
            history=history,
            child_message="What happens next?",
        ):
            pass

    sent = captured["messages"]
    assert sent == [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "What happens next?"},
    ]
