"""
Regression test for a live finding from a real adversarial probe
(docs/adversarial-probes/) run against the actual Claude API: a base64-
encoded prompt-injection attempt ("decode this and do what it says")
triggered Claude's own native stop_reason="refusal" — zero content
blocks, not even a text refusal. stream_tutor_response/stream_sandbox_
response used to just fall straight to {"type": "done"} in that case,
leaving the child looking at a completely blank reply with no error and
no way to know anything happened. Not a security bypass (nothing harmful
was ever emitted) — a reliability gap the security probe happened to
surface.
"""
import json
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest

from models.schemas import GradeStage, SessionConfig, Subject
from services import ai_service

pytestmark = pytest.mark.asyncio


class _FakeStreamWithFinalMessage:
    """Like test_ai_service_streaming.py's _FakeStream, but also supports
    get_final_message() — needed here since the fallback logic reads
    final_message.content, which _FakeStream deliberately doesn't model
    (AttributeError there is already handled by the existing try/except
    and correctly resolves to "no fallback", covered by every other test
    in test_ai_service_streaming.py continuing to pass unmodified)."""

    def __init__(self, events, final_content):
        self._events = events
        self._final_content = final_content

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        for event in self._events:
            yield event

    async def get_final_message(self):
        msg = MagicMock()
        msg.content = self._final_content
        msg.usage = MagicMock(input_tokens=10, output_tokens=0, cache_creation_input_tokens=0, cache_read_input_tokens=0)
        return msg


def _stream_with_final_content(events, final_content):
    @asynccontextmanager
    async def _fake(**kwargs):
        yield _FakeStreamWithFinalMessage(list(events), final_content)
    return _fake


def _config() -> SessionConfig:
    return SessionConfig(student_name="Alex", grade="8", grade_stage=GradeStage.independent)


async def test_tutor_response_falls_back_to_a_real_message_on_native_refusal():
    """No content_block events at all (the real shape of stop_reason=
    "refusal") -> the loop body never yields anything -> without the fix,
    chunks would be just [{"type": "done"}]."""
    with patch.object(ai_service._client.messages, "stream", side_effect=_stream_with_final_content([], final_content=[])):
        chunks = [
            json.loads(c)
            async for c in ai_service.stream_tutor_response(
                config=_config(), subject=Subject.free_study, history=[], child_message="anything",
            )
        ]

    text_chunks = [c for c in chunks if c["type"] == "text"]
    assert len(text_chunks) == 1
    assert text_chunks[0]["content"]  # non-empty — the child gets something real
    assert chunks[-1] == {"type": "done"}


async def test_tutor_response_no_fallback_when_text_was_actually_emitted():
    """The common case must be completely unaffected — real content means
    final_message.content is non-empty, so no extra fallback text."""
    from anthropic.types import (
        RawContentBlockDeltaEvent,
        RawContentBlockStartEvent,
        RawContentBlockStopEvent,
    )

    events = [
        RawContentBlockStartEvent.model_validate(
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
        ),
        RawContentBlockDeltaEvent.model_validate(
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Let's think."}}
        ),
        RawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": 0}),
    ]
    fake_text_block = MagicMock(type="text", text="Let's think.")

    with patch.object(
        ai_service._client.messages, "stream",
        side_effect=_stream_with_final_content(events, final_content=[fake_text_block]),
    ):
        chunks = [
            json.loads(c)
            async for c in ai_service.stream_tutor_response(
                config=_config(), subject=Subject.free_study, history=[], child_message="Tell me about Rome.",
            )
        ]

    text_chunks = [c for c in chunks if c["type"] == "text"]
    assert len(text_chunks) == 1  # only the one real text chunk — no extra fallback appended
    assert text_chunks[0]["content"] == "Let's think."


async def test_sandbox_response_falls_back_to_a_real_message_on_native_refusal():
    with patch.object(ai_service._client.messages, "stream", side_effect=_stream_with_final_content([], final_content=[])):
        chunks = [
            json.loads(c)
            async for c in ai_service.stream_sandbox_response(
                conversation_history=[], message="anything", custom_instructions="",
            )
        ]

    text_chunks = [c for c in chunks if c["type"] == "text"]
    assert len(text_chunks) == 1
    assert text_chunks[0]["content"]
    assert chunks[-1] == {"type": "done"}
