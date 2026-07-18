"""Provider-adapter layer for Bede's tutor engine.

`services/ai_service.py` was written directly against the Anthropic Messages
API: a single module-level `_client = anthropic.AsyncAnthropic(...)` whose
`.messages.stream(...)` / `.messages.create(...)` it calls with an
Anthropic-shaped request (a `system` list of cache-controlled text blocks,
alternating `messages`, `tools` with `input_schema`) and whose responses it
consumes as Anthropic wire-protocol events (`content_block_start`,
`content_block_delta` with `text_delta`/`input_json_delta`,
`content_block_stop`) plus a final `.get_final_message()` carrying `.content`,
`.usage`, and `.stop_reason`.

An adapter is any object that presents that SAME surface. The Anthropic SDK
already is one natively (see anthropic_adapter). Everything else — OpenAI, a
self-hosted vLLM server, Mistral, any OpenAI-compatible endpoint — becomes an
adapter that TRANSLATES to and from that Anthropic shape (see
openai_compatible_adapter), so the ~2000 lines of prompt/tool/streaming logic
in ai_service.py and the ~20 tests that monkeypatch
`ai_service._client.messages.stream`/`.create` never have to change.

The lightweight event/message classes below are the common Anthropic-shaped
vocabulary a translating adapter emits. The Anthropic adapter doesn't use them
(it hands back the real SDK objects); they exist so a non-Anthropic adapter can
produce something ai_service.py consumes identically, dispatching on the same
`.type` strings and attribute names.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional, Protocol, runtime_checkable


class AdapterUsage:
    """Anthropic-shaped usage. ai_service reads `.input_tokens`/`.output_tokens`
    and getattr()s the two cache_* fields (absent on non-Anthropic providers,
    which is why they default to 0 rather than being required)."""

    __slots__ = (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    )

    def __init__(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


class TextBlock:
    """A `content` entry of type `text`. ai_service reads `response.content[0].text`."""

    __slots__ = ("type", "text")

    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class ToolUseBlock:
    """A `content` entry of type `tool_use`."""

    __slots__ = ("type", "id", "name", "input")

    def __init__(self, id: str, name: str, input: Dict[str, Any]) -> None:
        self.type = "tool_use"
        self.id = id
        self.name = name
        self.input = input


class AdapterMessage:
    """Anthropic-shaped final/non-streaming message: `.content` (list of blocks),
    `.usage`, `.stop_reason`. ai_service checks `len(content) == 0` for the
    empty-response fallback, so an empty turn must yield an empty list here."""

    __slots__ = ("content", "usage", "stop_reason", "role", "model")

    def __init__(
        self,
        content: List[Any],
        usage: AdapterUsage,
        stop_reason: Optional[str] = None,
        model: str = "",
    ) -> None:
        self.content = content
        self.usage = usage
        self.stop_reason = stop_reason
        self.role = "assistant"
        self.model = model


class _Delta:
    __slots__ = ("type", "text", "partial_json")

    def __init__(self, type: str, text: str = "", partial_json: str = "") -> None:
        self.type = type
        self.text = text
        self.partial_json = partial_json


class StreamEvent:
    """One Anthropic wire-protocol streaming event. ai_service dispatches on the
    `.type` string (`content_block_start` / `content_block_delta` /
    `content_block_stop`) rather than the Python class name — deliberately, since
    SDK class names have churned across versions — so a single class carrying the
    right `.type` and the fields that branch needs is all that's required."""

    __slots__ = ("type", "index", "content_block", "delta")

    def __init__(
        self,
        type: str,
        index: int = 0,
        content_block: Optional[Any] = None,
        delta: Optional[_Delta] = None,
    ) -> None:
        self.type = type
        self.index = index
        self.content_block = content_block
        self.delta = delta


@runtime_checkable
class MessagesInterface(Protocol):
    """The `.messages` namespace ai_service reaches through `_client.messages`."""

    def stream(self, **kwargs: Any) -> Any:  # returns an async context manager
        ...

    async def create(self, **kwargs: Any) -> Any:  # returns an AdapterMessage-like
        ...


@runtime_checkable
class ChatAdapter(Protocol):
    """What ai_service's `_client` must look like: an object exposing a
    `.messages` namespace with `.stream(**kwargs)` (async context manager
    yielding StreamEvents, with `.get_final_message()`) and
    `.create(**kwargs)` (returns an AdapterMessage). `anthropic.AsyncAnthropic`
    already satisfies this structurally."""

    messages: MessagesInterface
