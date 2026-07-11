"""
Regression test for a live outage: stream_tutor_response() dispatched on
type(event).__name__ against old anthropic SDK class names, and pre-formatted
each chunk as a complete "data: ...\\n\\n" string yielded into
EventSourceResponse. requirements.txt pins anthropic/sse-starlette with no
upper bound, and a routine dependency-version bump silently broke both:
event-type checks stopped matching (zero text/tool content ever streamed),
and sse-starlette's real ASGI encoding re-wraps an already-"data: "-prefixed
string, producing invalid "data: data: {...}" that the frontend's JSON.parse
silently drops.

This constructs the fake Claude stream from real anthropic.types objects
(via model_validate on realistic wire-format payloads) rather than plain
dicts/mocks, so a future SDK schema change fails this test loudly instead of
being silently absorbed the way the class-name check was.
"""
import json
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from anthropic.types import (
    RawContentBlockDeltaEvent,
    RawContentBlockStartEvent,
    RawContentBlockStopEvent,
)

from models.schemas import GradeStage, SessionConfig, Subject
from services import ai_service


def _text_events(text: str):
    yield RawContentBlockStartEvent.model_validate(
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
    )
    yield RawContentBlockDeltaEvent.model_validate(
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}
    )
    yield RawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": 0})


class _FakeStream:
    def __init__(self, events):
        self._events = events

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        for event in self._events:
            yield event


@asynccontextmanager
async def _fake_messages_stream(**kwargs):
    yield _FakeStream(list(_text_events("Hello there")))


def _config() -> SessionConfig:
    return SessionConfig(student_name="Guest", grade="4", grade_stage=GradeStage.core_mastery)


@pytest.mark.asyncio
async def test_stream_tutor_response_emits_text_from_real_sdk_events():
    with patch.object(ai_service._client.messages, "stream", side_effect=_fake_messages_stream):
        chunks = [
            chunk
            async for chunk in ai_service.stream_tutor_response(
                config=_config(),
                subject=Subject.living_books,
                history=[],
                child_message="[START]",
            )
        ]

    assert len(chunks) >= 2, "expected at least a text chunk and a done chunk"

    # Every yielded chunk must be plain JSON with no "data: " framing —
    # EventSourceResponse owns that framing; a pre-formatted "data: ..."
    # string here would come out double-wrapped and unparseable client-side.
    parsed = [json.loads(c) for c in chunks]

    text_chunks = [p for p in parsed if p["type"] == "text"]
    assert text_chunks, "no text chunk was emitted — event-type dispatch is broken"
    assert "".join(p["content"] for p in text_chunks) == "Hello there"

    assert parsed[-1] == {"type": "done"}
