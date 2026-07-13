"""
Any OpenAI-compatible chat-completions server — Ollama, vLLM, llama.cpp
server, LM Studio, text-generation-webui, etc. — for a fully air-gapped
deployment or as a hedge against a compromised/poisoned hosted model, at
the cost of tutoring quality versus hosted Claude. See docs/MODEL_PROVIDERS.md
for the setup and the honest limits of what this can and can't protect
against (it verifies the server answers as the configured model name; it
cannot verify the weight file itself hasn't been tampered with — that's an
operator-side checksum step before pointing LOCAL_MODEL_BASE_URL at it).
"""
import json
import logging
from typing import Any, AsyncIterator, List, Optional

import httpx

from core.config import settings
from .base import ModelProvider, StreamEvent, TextDelta, ToolCall

log = logging.getLogger(__name__)


def _flatten_system(system: Any) -> Optional[str]:
    """Anthropic's system param is either a plain string or a list of
    cache_control text blocks; OpenAI-compatible servers understand neither
    the block list nor cache_control, so this always collapses it to one
    system-role string (or None if there's nothing to say)."""
    if system is None:
        return None
    if isinstance(system, str):
        return system or None
    return "\n\n".join(block["text"] for block in system if block.get("text")) or None


def _to_openai_messages(system: Any, messages: List[dict]) -> List[dict]:
    out = []
    flat_system = _flatten_system(system)
    if flat_system:
        out.append({"role": "system", "content": flat_system})

    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
            continue
        # Anthropic multimodal content blocks (image + text) -> OpenAI's
        # image_url/text part format.
        parts = []
        for block in content:
            if block["type"] == "text":
                parts.append({"type": "text", "text": block["text"]})
            elif block["type"] == "image":
                source = block["source"]
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{source['media_type']};base64,{source['data']}"},
                })
        out.append({"role": m["role"], "content": parts})
    return out


def _to_openai_tools(tools: Optional[List[dict]]) -> Optional[List[dict]]:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


class LocalProvider(ModelProvider):
    """Self-hosted, OpenAI-compatible backend. Configured via
    LOCAL_MODEL_BASE_URL (default: a local Ollama instance) and
    LOCAL_MODEL_NAME (no default — must be set explicitly)."""

    def __init__(self):
        self._base_url = settings.local_model_base_url.rstrip("/")
        self._model = settings.local_model_name

    async def stream(
        self,
        *,
        system: Any,
        messages: List[dict],
        tools: Optional[List[dict]],
        max_tokens: int,
    ) -> AsyncIterator[StreamEvent]:
        payload: dict = {
            "model": self._model,
            "messages": _to_openai_messages(system, messages),
            "max_tokens": max_tokens,
            "stream": True,
        }
        openai_tools = _to_openai_tools(tools)
        if openai_tools:
            payload["tools"] = openai_tools

        # Tool-call argument fragments arrive keyed by their position in the
        # response's tool_calls array (OpenAI's streaming format), not by a
        # stable id the way Anthropic's content-block ids work — buffer by
        # that index until finish_reason confirms the calls are complete.
        tool_calls_buffer: dict = {}

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST", f"{self._base_url}/chat/completions", json=payload
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if not data or data == "[DONE]":
                        continue
                    chunk = json.loads(data)
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta", {})

                    if delta.get("content"):
                        yield TextDelta(delta["content"])

                    for tc_delta in delta.get("tool_calls") or []:
                        idx = tc_delta.get("index", 0)
                        entry = tool_calls_buffer.setdefault(idx, {"id": "", "name": "", "input_str": ""})
                        if tc_delta.get("id"):
                            entry["id"] = tc_delta["id"]
                        fn = tc_delta.get("function") or {}
                        if fn.get("name"):
                            entry["name"] = fn["name"]
                        if fn.get("arguments"):
                            entry["input_str"] += fn["arguments"]

                    if choice.get("finish_reason") == "tool_calls":
                        for entry in tool_calls_buffer.values():
                            try:
                                tool_input = json.loads(entry["input_str"]) if entry["input_str"] else {}
                            except json.JSONDecodeError:
                                continue
                            yield ToolCall(id=entry["id"], name=entry["name"], input=tool_input)
                        tool_calls_buffer.clear()

    async def complete(
        self,
        *,
        system: Optional[str],
        messages: List[dict],
        max_tokens: int,
    ) -> str:
        payload = {
            "model": self._model,
            "messages": _to_openai_messages(system, messages),
            "max_tokens": max_tokens,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{self._base_url}/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
