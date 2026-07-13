import json
import logging
from typing import Any, AsyncIterator, List, Optional

import anthropic

from core.config import settings
from .base import ModelProvider, StreamEvent, TextDelta, ToolCall

log = logging.getLogger(__name__)


class AnthropicProvider(ModelProvider):
    """Hosted Claude — the default, highest-quality provider. A single shared
    async client avoids re-initialising on every request."""

    def __init__(self):
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def stream(
        self,
        *,
        system: Any,
        messages: List[dict],
        tools: Optional[List[dict]],
        max_tokens: int,
    ) -> AsyncIterator[StreamEvent]:
        kwargs = dict(model=settings.tutor_model, max_tokens=max_tokens, system=system, messages=messages)
        if tools:
            kwargs["tools"] = tools

        async with self._client.messages.stream(**kwargs) as stream:
            tool_calls_buffer: dict = {}

            async for event in stream:
                # Dispatch on the wire-protocol `.type` string, not the SDK's
                # Python class name — the class names are an implementation
                # detail that has changed across anthropic SDK versions (e.g.
                # "ContentBlockStart" -> "RawContentBlockStartEvent"), silently
                # breaking every branch below with zero exceptions raised.
                # `.type` mirrors the documented API event/delta type strings
                # and is stable across SDK versions.
                event_type = event.type

                if event_type == "content_block_start":
                    block = event.content_block
                    if hasattr(block, "type") and block.type == "tool_use":
                        tool_calls_buffer[block.id] = {"name": block.name, "input_str": ""}

                elif event_type == "content_block_delta":
                    delta = event.delta
                    delta_type = delta.type

                    if delta_type == "text_delta":
                        yield TextDelta(delta.text)

                    elif delta_type == "input_json_delta":
                        block_id = next(iter(tool_calls_buffer), None)
                        if block_id:
                            tool_calls_buffer[block_id]["input_str"] += delta.partial_json

                elif event_type == "content_block_stop":
                    for block_id, tc in list(tool_calls_buffer.items()):
                        if tc["input_str"]:
                            try:
                                tool_input = json.loads(tc["input_str"])
                                yield ToolCall(id=block_id, name=tc["name"], input=tool_input)
                            except json.JSONDecodeError:
                                pass
                        tool_calls_buffer.pop(block_id, None)

    async def complete(
        self,
        *,
        system: Optional[str],
        messages: List[dict],
        max_tokens: int,
    ) -> str:
        kwargs = dict(model=settings.session_model, max_tokens=max_tokens, messages=messages)
        if system:
            kwargs["system"] = system
        response = await self._client.messages.create(**kwargs)
        return response.content[0].text
