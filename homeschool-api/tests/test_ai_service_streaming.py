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

import anthropic
import httpx
import pytest
from anthropic.types import (
    RawContentBlockDeltaEvent,
    RawContentBlockStartEvent,
    RawContentBlockStopEvent,
)

from models.schemas import GradeStage, SessionConfig, Subject
from services import ai_service


def _text_events(text: str, index: int = 0):
    yield RawContentBlockStartEvent.model_validate(
        {"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}}
    )
    yield RawContentBlockDeltaEvent.model_validate(
        {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": text}}
    )
    yield RawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": index})


def _tool_use_events(tool_id: str, name: str, tool_input: dict, index: int = 0):
    import json as _json

    yield RawContentBlockStartEvent.model_validate({
        "type": "content_block_start", "index": index,
        "content_block": {"type": "tool_use", "id": tool_id, "name": name, "input": {}},
    })
    yield RawContentBlockDeltaEvent.model_validate({
        "type": "content_block_delta", "index": index,
        "delta": {"type": "input_json_delta", "partial_json": _json.dumps(tool_input)},
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


@asynccontextmanager
async def _fake_messages_stream(**kwargs):
    yield _FakeStream(list(_text_events("Hello there")))


def _stream_of(events):
    @asynccontextmanager
    async def _fake(**kwargs):
        yield _FakeStream(list(events))
    return _fake


def _config() -> SessionConfig:
    return SessionConfig(student_name="Guest", grade="4", grade_stage=GradeStage.core_mastery)


async def _run_stream(events) -> list[dict]:
    with patch.object(ai_service._client.messages, "stream", side_effect=_stream_of(events)):
        chunks = [
            chunk
            async for chunk in ai_service.stream_tutor_response(
                config=_config(),
                subject=Subject.living_books,
                history=[],
                child_message="Tell me about the river.",
            )
        ]
    return [json.loads(c) for c in chunks]


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


# ── Guaranteed continuation after a questionless tool card ──────────────────
#
# Regression coverage for a real observed outage: Bede's turn ended right on
# a celebrate_discovery card with no trailing text at all — a live transcript
# screenshot showed the conversation just stopping, with nothing for the
# child to respond to. The system prompt already asks the model to always
# add a question after one of these tools (see tools_guidance), but that's a
# request, not a guarantee — tool-calling models have a real tendency to
# treat a tool call as a natural end of turn. These tests exercise the
# code-level fallback in stream_tutor_response that fires regardless of
# whether the model complies.

@pytest.mark.asyncio
async def test_celebrate_discovery_as_the_last_block_gets_a_fallback_question():
    events = list(_tool_use_events(
        "toolu_1", "celebrate_discovery",
        {"specific_insight": "the river carves the canyon", "encouragement": "That's real thinking!"},
    ))
    parsed = await _run_stream(events)

    assert parsed[-1] == {"type": "done"}
    text_chunks = [p for p in parsed if p["type"] == "text"]
    assert text_chunks, "no fallback question was appended after a questionless tool card"
    assert text_chunks[-1]["content"].strip() in ai_service._FALLBACK_CONTINUATION_QUESTIONS


@pytest.mark.asyncio
async def test_no_fallback_appended_when_the_model_already_added_a_question():
    events = [
        *_tool_use_events("toolu_1", "celebrate_discovery", {"specific_insight": "x", "encouragement": "y"}, index=0),
        *_text_events(" What do you notice about the next bend in the river?", index=1),
    ]
    parsed = await _run_stream(events)

    text_chunks = [p for p in parsed if p["type"] == "text"]
    assert len(text_chunks) == 1, "a fallback was appended even though the model already asked a question"
    assert "next bend" in text_chunks[0]["content"]


@pytest.mark.asyncio
async def test_connect_to_faith_without_reflection_question_gets_a_fallback():
    events = list(_tool_use_events(
        "toolu_1", "connect_to_faith", {"connection": "Just as the river never stops moving, God's care never stops either."},
    ))
    parsed = await _run_stream(events)

    text_chunks = [p for p in parsed if p["type"] == "text"]
    assert text_chunks, "connect_to_faith with no reflection_question should still get a fallback"
    assert text_chunks[-1]["content"].strip() in ai_service._FALLBACK_CONTINUATION_QUESTIONS


@pytest.mark.asyncio
async def test_connect_to_faith_with_reflection_question_gets_no_fallback():
    events = list(_tool_use_events(
        "toolu_1", "connect_to_faith",
        {"connection": "The river never stops moving.", "reflection_question": "What else in creation never stops?"},
    ))
    parsed = await _run_stream(events)

    text_chunks = [p for p in parsed if p["type"] == "text"]
    assert not text_chunks, "connect_to_faith already had its own reflection_question — no fallback should be added"


@pytest.mark.asyncio
async def test_offer_socratic_hint_as_last_block_gets_no_fallback():
    """offer_socratic_hint's hint_question already IS the turn's question —
    it's deliberately not in _QUESTIONLESS_TOOLS."""
    events = list(_tool_use_events(
        "toolu_1", "offer_socratic_hint", {"hint_question": "What shape does flowing water tend to carve?"},
    ))
    parsed = await _run_stream(events)

    text_chunks = [p for p in parsed if p["type"] == "text"]
    assert not text_chunks, "offer_socratic_hint's own question should not trigger a redundant fallback"


# ── BYOK (bring-your-own-Anthropic-key) ──────────────────────────────────────
#
# A public demo visitor can supply their own Anthropic key at /auth/demo-code
# to unlock an uncapped session (see routers/tutor.py's chat() and
# core/demo_code_session.py's get_byok_key). stream_tutor_response must use
# THAT key's client for the call, never the shared operator _client, and must
# degrade gracefully (not crash the session) if that key turns out to be
# invalid, revoked, or out of credit.

@pytest.mark.asyncio
async def test_byok_key_builds_a_fresh_client_instead_of_using_the_shared_one():
    fake_client = _FakeAsyncAnthropicClient(list(_text_events("Hello from a fresh client")))
    captured_kwargs = {}

    def fake_constructor(**kwargs):
        captured_kwargs.update(kwargs)
        return fake_client

    with patch.object(ai_service.anthropic, "AsyncAnthropic", side_effect=fake_constructor), \
         patch.object(ai_service._client.messages, "stream", side_effect=_fake_messages_stream) as shared_client_stream:
        chunks = [
            chunk
            async for chunk in ai_service.stream_tutor_response(
                config=_config(),
                subject=Subject.living_books,
                history=[],
                child_message="Tell me about the river.",
                anthropic_api_key="sk-ant-visitor-key-123",
            )
        ]

    assert captured_kwargs.get("api_key") == "sk-ant-visitor-key-123", \
        "BYOK client must be constructed with the visitor's own key"
    shared_client_stream.assert_not_called()  # never falls back to the operator's shared client
    parsed = [json.loads(c) for c in chunks]
    text_chunks = [p for p in parsed if p["type"] == "text"]
    assert "".join(p["content"] for p in text_chunks) == "Hello from a fresh client"


@pytest.mark.asyncio
async def test_no_byok_key_uses_the_shared_operator_client():
    with patch.object(ai_service.anthropic, "AsyncAnthropic") as constructor:
        with patch.object(ai_service._client.messages, "stream", side_effect=_fake_messages_stream):
            chunks = [
                chunk
                async for chunk in ai_service.stream_tutor_response(
                    config=_config(),
                    subject=Subject.living_books,
                    history=[],
                    child_message="Tell me about the river.",
                )
            ]
    constructor.assert_not_called()  # no BYOK key -> never builds a new client at all
    assert any(json.loads(c)["type"] == "done" for c in chunks)


class _FakeAsyncAnthropicClient:
    """Stands in for a fresh anthropic.AsyncAnthropic(api_key=...) instance —
    only .messages.stream(...) is ever touched by ai_service."""
    def __init__(self, events):
        self.messages = _FakeMessages(events)


class _FakeMessages:
    def __init__(self, events):
        self._events = events

    def stream(self, **kwargs):
        return _stream_of(self._events)(**kwargs)


@pytest.mark.asyncio
async def test_invalid_byok_key_degrades_gracefully_instead_of_crashing():
    import httpx

    def raise_auth_error(**kwargs):
        @asynccontextmanager
        async def _fake(**_kwargs):
            raise anthropic.AuthenticationError(
                "invalid x-api-key",
                response=httpx.Response(401, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")),
                body=None,
            )
            yield  # pragma: no cover — unreachable, makes this a generator function
        return _fake(**kwargs)

    fake_client = _FakeAsyncAnthropicClient([])
    fake_client.messages.stream = raise_auth_error

    with patch.object(ai_service.anthropic, "AsyncAnthropic", return_value=fake_client):
        chunks = [
            chunk
            async for chunk in ai_service.stream_tutor_response(
                config=_config(),
                subject=Subject.living_books,
                history=[],
                child_message="Tell me about the river.",
                anthropic_api_key="sk-ant-a-bad-key",
            )
        ]

    parsed = [json.loads(c) for c in chunks]
    assert parsed[-1] == {"type": "done"}, "a bad BYOK key must still end the stream cleanly, not crash it"
    text_chunks = [p for p in parsed if p["type"] == "text"]
    assert text_chunks, "the child should see a graceful in-persona message, not silence"
    assert "api" not in text_chunks[0]["content"].lower() and "key" not in text_chunks[0]["content"].lower(), \
        "the fallback message must never leak API/key details into the child-facing chat"


# ── OpenAI BYOK tutoring path ─────────────────────────────────────────────
#
# A demo visitor can supply their own OpenAI key instead of Anthropic's (see
# routers/tutor.py's chat() and _stream_tutor_events_openai) — routed to a
# fully separate implementation since OpenAI's Chat Completions streaming
# wire format (SSE "data: {...}" lines, tool-call argument deltas keyed by
# index, a single finish_reason-bearing chunk at the end) has nothing in
# common with Anthropic's content_block_start/delta/stop model. These tests
# build realistic mocked SSE responses rather than trusting the shape by
# inspection, the same principle as the real-anthropic.types tests above.

class _FakeOpenAIResponse:
    def __init__(self, lines: list[str], status_ok: bool = True):
        self._lines = lines
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
            raise httpx.HTTPStatusError("401 Unauthorized", request=req, response=httpx.Response(401, request=req))

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeOpenAIStreamCtx:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *args):
        return False


class _FakeOpenAIClient:
    def __init__(self, lines: list[str], status_ok: bool = True):
        self._lines = lines
        self._status_ok = status_ok

    def stream(self, method, url, **kwargs):
        return _FakeOpenAIStreamCtx(_FakeOpenAIResponse(self._lines, self._status_ok))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _openai_sse(*events: dict) -> list[str]:
    lines = [f"data: {json.dumps(e)}" for e in events]
    lines.append("data: [DONE]")
    return lines


async def _run_openai_stream(lines: list[str], status_ok: bool = True) -> list[dict]:
    with patch.object(ai_service.httpx, "AsyncClient", return_value=_FakeOpenAIClient(lines, status_ok)):
        chunks = [
            chunk
            async for chunk in ai_service.stream_tutor_response(
                config=_config(),
                subject=Subject.living_books,
                history=[],
                child_message="Tell me about the river.",
                openai_api_key="sk-visitor-openai-key",
            )
        ]
    return [json.loads(c) for c in chunks]


@pytest.mark.asyncio
async def test_openai_byok_streams_plain_text():
    lines = _openai_sse(
        {"choices": [{"delta": {"content": "The river "}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "carves the canyon."}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    )
    parsed = await _run_openai_stream(lines)
    text_chunks = [p for p in parsed if p["type"] == "text"]
    assert "".join(p["content"] for p in text_chunks) == "The river carves the canyon."
    assert parsed[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_openai_byok_accumulates_tool_call_argument_deltas_by_index():
    """OpenAI streams a tool call's arguments as fragments across multiple
    chunks, keyed by position (index), unlike Anthropic's per-block id —
    the real failure mode this guards is naive accumulation losing or
    misordering fragments."""
    chunk_1 = {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "call_1", "function": {"name": "offer_socratic_hint", "arguments": ""}}
    ]}, "finish_reason": None}]}
    chunk_2 = {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"arguments": '{"hint_question": '}}
    ]}, "finish_reason": None}]}
    chunk_3 = {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"arguments": '"What shape does water carve?"}'}}
    ]}, "finish_reason": None}]}
    chunk_4 = {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}
    lines = _openai_sse(chunk_1, chunk_2, chunk_3, chunk_4)
    parsed = await _run_openai_stream(lines)
    tool_chunks = [p for p in parsed if p["type"] == "tool"]
    assert len(tool_chunks) == 1
    assert "What shape does water carve?" in tool_chunks[0]["content"]


@pytest.mark.asyncio
async def test_openai_byok_celebrate_discovery_alone_gets_the_same_fallback_guarantee():
    """The ends_on_questionless_tool guarantee from PR #17 must hold
    identically regardless of provider — shared via _dispatch_completed_tool_call."""
    lines = _openai_sse(
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "celebrate_discovery", "arguments": ""}}]}, "finish_reason": None}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"specific_insight": "x", "encouragement": "y"}'}}]}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    )
    parsed = await _run_openai_stream(lines)
    text_chunks = [p for p in parsed if p["type"] == "text"]
    assert text_chunks, "no fallback question was appended after a questionless tool card on the OpenAI path"
    assert text_chunks[-1]["content"].strip() in ai_service._FALLBACK_CONTINUATION_QUESTIONS


@pytest.mark.asyncio
async def test_openai_byok_degrades_gracefully_on_http_error():
    parsed = await _run_openai_stream(lines=[], status_ok=False)
    assert parsed[-1] == {"type": "done"}
    text_chunks = [p for p in parsed if p["type"] == "text"]
    assert text_chunks, "the child should see a graceful in-persona message, not silence"
    assert "api" not in text_chunks[0]["content"].lower() and "key" not in text_chunks[0]["content"].lower()


def test_tools_to_openai_format_preserves_name_description_and_schema():
    openai_tools = ai_service._tools_to_openai_format(ai_service.TUTOR_TOOLS)
    assert len(openai_tools) == len(ai_service.TUTOR_TOOLS)
    for original, converted in zip(ai_service.TUTOR_TOOLS, openai_tools):
        assert converted["type"] == "function"
        assert converted["function"]["name"] == original["name"]
        assert converted["function"]["description"] == original["description"]
        assert converted["function"]["parameters"] == original["input_schema"]
