"""
Tests for the self-hosted, OpenAI-compatible provider (Ollama/vLLM/llama.cpp-
style /chat/completions) — the air-gapped/poisoning-hedge alternative to
hosted Claude. Exercises the Anthropic->OpenAI request translation and the
OpenAI->normalized-event response translation, using httpx.MockTransport so
no real network call is made.
"""
import json
from unittest.mock import patch

import httpx
import pytest

from services.model_providers.base import TextDelta, ToolCall
from services.model_providers.local_provider import (
    LocalProvider,
    _flatten_system,
    _to_openai_messages,
    _to_openai_tools,
)

# Captured before any patching, so the fake client factory below doesn't
# recursively call its own patched replacement of httpx.AsyncClient.
_RealAsyncClient = httpx.AsyncClient


def _sse_body(*chunks: dict) -> bytes:
    lines = [f"data: {json.dumps(c)}" for c in chunks]
    lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode()


def _patched_client(handler):
    return patch(
        "services.model_providers.local_provider.httpx.AsyncClient",
        lambda *a, **kw: _RealAsyncClient(transport=httpx.MockTransport(handler)),
    )


# ── Request translation (Anthropic shapes -> OpenAI shapes) ─────────────────

def test_flatten_system_collapses_cache_control_block_list():
    system = [
        {"type": "text", "text": "Block one", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "Block two"},
    ]
    assert _flatten_system(system) == "Block one\n\nBlock two"


def test_flatten_system_passes_through_plain_string():
    assert _flatten_system("just a string") == "just a string"


def test_flatten_system_none_for_empty_input():
    assert _flatten_system(None) is None
    assert _flatten_system("") is None


def test_to_openai_messages_translates_image_and_text_blocks():
    messages = [{
        "role": "user",
        "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAA="}},
            {"type": "text", "text": "what is this?"},
        ],
    }]
    out = _to_openai_messages(None, messages)
    assert out == [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA="}},
            {"type": "text", "text": "what is this?"},
        ],
    }]


def test_to_openai_messages_prepends_system_role_when_present():
    out = _to_openai_messages("be kind", [{"role": "user", "content": "hi"}])
    assert out[0] == {"role": "system", "content": "be kind"}
    assert out[1] == {"role": "user", "content": "hi"}


def test_to_openai_tools_translates_anthropic_schema():
    tools = [{
        "name": "foo",
        "description": "does foo",
        "input_schema": {"type": "object", "properties": {"x": {"type": "string"}}},
    }]
    assert _to_openai_tools(tools) == [{
        "type": "function",
        "function": {
            "name": "foo",
            "description": "does foo",
            "parameters": {"type": "object", "properties": {"x": {"type": "string"}}},
        },
    }]


def test_to_openai_tools_none_for_empty():
    assert _to_openai_tools(None) is None
    assert _to_openai_tools([]) is None


# ── Response translation (OpenAI SSE -> normalized events) ───────────────────

@pytest.mark.asyncio
async def test_stream_emits_text_deltas():
    body = _sse_body(
        {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": " there"}, "finish_reason": None}]},
    )

    def handler(request):
        return httpx.Response(200, content=body)

    provider = LocalProvider()
    with _patched_client(handler):
        events = [
            e async for e in provider.stream(
                system=None, messages=[{"role": "user", "content": "hi"}], tools=None, max_tokens=100,
            )
        ]

    assert events == [TextDelta("Hello"), TextDelta(" there")]


@pytest.mark.asyncio
async def test_stream_emits_tool_call_once_finish_reason_arrives():
    body = _sse_body(
        {"choices": [{
            "delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "offer_socratic_hint", "arguments": ""}}]},
            "finish_reason": None,
        }]},
        {"choices": [{
            "delta": {"tool_calls": [{"index": 0, "function": {"arguments": json.dumps({"hint_question": "Why?"})}}]},
            "finish_reason": None,
        }]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    )

    def handler(request):
        return httpx.Response(200, content=body)

    provider = LocalProvider()
    with _patched_client(handler):
        events = [
            e async for e in provider.stream(
                system=None, messages=[{"role": "user", "content": "hi"}],
                tools=[{"name": "offer_socratic_hint", "input_schema": {}}], max_tokens=100,
            )
        ]

    assert events == [ToolCall(id="call_1", name="offer_socratic_hint", input={"hint_question": "Why?"})]


@pytest.mark.asyncio
async def test_stream_drops_tool_call_with_unparseable_arguments():
    body = _sse_body(
        {"choices": [{
            "delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "foo", "arguments": "{not json"}}]},
            "finish_reason": None,
        }]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    )

    def handler(request):
        return httpx.Response(200, content=body)

    provider = LocalProvider()
    with _patched_client(handler):
        events = [
            e async for e in provider.stream(
                system=None, messages=[{"role": "user", "content": "hi"}], tools=None, max_tokens=100,
            )
        ]

    assert events == []


@pytest.mark.asyncio
async def test_complete_returns_message_content():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello world"}}]})

    provider = LocalProvider()
    with _patched_client(handler):
        result = await provider.complete(
            system=None, messages=[{"role": "user", "content": "hi"}], max_tokens=50,
        )

    assert result == "hello world"
