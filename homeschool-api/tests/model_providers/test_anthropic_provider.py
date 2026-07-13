"""
Regression test for a live outage: the old inline streaming code in
ai_service.py dispatched on type(event).__name__ against anthropic SDK class
names, and a routine dependency-version bump silently broke it (event-type
checks stopped matching, zero text/tool content ever streamed) — see
git history for services/ai_service.py before the model-provider refactor.

This constructs the fake Claude stream from real anthropic.types objects (via
model_validate on realistic wire-format payloads) rather than plain
dicts/mocks, so a future SDK schema change fails this test loudly instead of
being silently absorbed the way the class-name check was. It now lives here,
against AnthropicProvider.stream() directly, since that's the only place
left in the codebase that talks to the raw anthropic SDK event stream.
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

from services.model_providers.anthropic_provider import AnthropicProvider
from services.model_providers.base import TextDelta, ToolCall


def _text_events(text: str, index: int = 0):
    yield RawContentBlockStartEvent.model_validate(
        {"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}}
    )
    yield RawContentBlockDeltaEvent.model_validate(
        {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": text}}
    )
    yield RawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": index})


def _tool_use_events(tool_id: str, name: str, tool_input: dict, index: int = 0):
    yield RawContentBlockStartEvent.model_validate({
        "type": "content_block_start", "index": index,
        "content_block": {"type": "tool_use", "id": tool_id, "name": name, "input": {}},
    })
    yield RawContentBlockDeltaEvent.model_validate({
        "type": "content_block_delta", "index": index,
        "delta": {"type": "input_json_delta", "partial_json": json.dumps(tool_input)},
    })
    yield RawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": index})


class _FakeStream:
    def __init__(self, events):
        self._events = events

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        for event in self._events:
            yield event


def _stream_of(events):
    @asynccontextmanager
    async def _fake(**kwargs):
        yield _FakeStream(list(events))
    return _fake


async def _collect(events) -> list:
    provider = AnthropicProvider()
    with patch.object(provider._client.messages, "stream", side_effect=_stream_of(events)):
        return [
            e
            async for e in provider.stream(
                system="system prompt", messages=[{"role": "user", "content": "hi"}],
                tools=None, max_tokens=500,
            )
        ]


@pytest.mark.asyncio
async def test_stream_emits_text_delta_from_real_sdk_events():
    out = await _collect(list(_text_events("Hello there")))
    assert out == [TextDelta("Hello there")]


@pytest.mark.asyncio
async def test_stream_emits_tool_call_from_real_sdk_events():
    out = await _collect(list(_tool_use_events("toolu_1", "celebrate_discovery", {"specific_insight": "x"})))
    assert out == [ToolCall(id="toolu_1", name="celebrate_discovery", input={"specific_insight": "x"})]


@pytest.mark.asyncio
async def test_stream_handles_text_then_tool_call_in_order():
    events = [
        *_text_events("Great job! ", index=0),
        *_tool_use_events("toolu_1", "offer_socratic_hint", {"hint_question": "Why?"}, index=1),
    ]
    out = await _collect(events)
    assert out == [
        TextDelta("Great job! "),
        ToolCall(id="toolu_1", name="offer_socratic_hint", input={"hint_question": "Why?"}),
    ]


@pytest.mark.asyncio
async def test_malformed_tool_json_is_silently_dropped():
    events = [
        RawContentBlockStartEvent.model_validate({
            "type": "content_block_start", "index": 0,
            "content_block": {"type": "tool_use", "id": "toolu_1", "name": "offer_socratic_hint", "input": {}},
        }),
        RawContentBlockDeltaEvent.model_validate({
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": "{not valid json"},
        }),
        RawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": 0}),
    ]
    out = await _collect(events)
    assert out == []
