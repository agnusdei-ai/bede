"""OpenAI-compatible adapter — one class for every non-Anthropic provider.

A single `OpenAICompatibleClient`, parameterized by `base_url` + `api_key` +
`model`, presents the Anthropic `.messages.stream()`/`.messages.create()`
surface ai_service.py expects, implemented on top of OpenAI's
`/v1/chat/completions` via the `openai` SDK's `AsyncOpenAI` (with `base_url`
overridden). Because vLLM, Mistral, Together, HF TGI, LM Studio, etc. all
expose that same OpenAI-compatible endpoint, this one class covers:

  * OpenAI itself (default base_url)
  * a self-hosted vLLM server running Qwen/Qwen3-Coder-30B-A3B-Instruct
    (start vLLM with `--tool-call-parser qwen3_coder` so it emits tool calls in
    the OpenAI `tool_calls` shape this adapter reads back)
  * Mistral's API
  * any other OpenAI-compatible or HF Inference endpoint

The translation is symmetric:

  request  (Anthropic → OpenAI):  system block(s) → a `system` role message;
           `tools`(input_schema) → `tools`(function.parameters); `tool_choice`
           auto/any/tool → auto/required/named-function; `max_tokens` passthrough.
  response (OpenAI → Anthropic):  streamed text deltas → `content_block_delta`
           `text_delta`; streamed `tool_calls` → a `content_block_start`
           `tool_use` + `input_json_delta` + `content_block_stop` triple per
           call; `usage.prompt_tokens`/`completion_tokens` →
           `.usage.input_tokens`/`.output_tokens`.

`openai` is imported lazily inside `__init__` so a deployment that never
configures a non-Anthropic provider (the default) doesn't need the package
installed or imported at all.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from .base import (
    AdapterMessage,
    AdapterUsage,
    StreamEvent,
    TextBlock,
    ToolUseBlock,
    _Delta,
)


# ── request translation: Anthropic Messages shape → OpenAI chat shape ────────

def _flatten_system(system: Any) -> Optional[str]:
    """Anthropic `system` is either a plain string (summary/profile calls) or a
    list of `{"type":"text","text":...,"cache_control":...}` blocks (the tutor's
    cached static+subject prompt). OpenAI has no separate system field or
    cache_control concept — collapse either form to one system-role string."""
    if system is None:
        return None
    if isinstance(system, str):
        return system
    parts: List[str] = []
    for block in system:
        if isinstance(block, dict):
            text = block.get("text", "")
        else:
            text = getattr(block, "text", "")
        if text:
            parts.append(text)
    return "\n\n".join(parts) if parts else None


def _content_to_text(content: Any) -> str:
    """ai_service passes string message content, but Anthropic content can also
    be a list of blocks — handle both, keeping only text/tool_result text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_result":
                    inner = block.get("content", "")
                    parts.append(inner if isinstance(inner, str) else json.dumps(inner))
        return "\n".join(parts)
    return str(content)


def _translate_messages(system: Any, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    system_text = _flatten_system(system)
    if system_text:
        out.append({"role": "system", "content": system_text})
    for m in messages:
        role = m.get("role", "user")
        out.append({"role": role, "content": _content_to_text(m.get("content", ""))})
    return out


def _translate_tools(tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
    if not tools:
        return None
    out: List[Dict[str, Any]] = []
    for t in tools:
        # Strip Anthropic-only cache_control; map input_schema → parameters.
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
        )
    return out


def _translate_tool_choice(tool_choice: Optional[Dict[str, Any]]) -> Optional[Any]:
    if not tool_choice:
        return None
    kind = tool_choice.get("type")
    if kind == "auto":
        return "auto"
    if kind == "any":
        return "required"
    if kind == "tool" and tool_choice.get("name"):
        return {"type": "function", "function": {"name": tool_choice["name"]}}
    return None


def _build_request(model: str, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    req: Dict[str, Any] = {
        "model": model,
        "messages": _translate_messages(kwargs.get("system"), kwargs.get("messages", [])),
    }
    if "max_tokens" in kwargs and kwargs["max_tokens"] is not None:
        req["max_tokens"] = kwargs["max_tokens"]
    if "temperature" in kwargs and kwargs["temperature"] is not None:
        req["temperature"] = kwargs["temperature"]
    tools = _translate_tools(kwargs.get("tools"))
    if tools:
        req["tools"] = tools
    tc = _translate_tool_choice(kwargs.get("tool_choice"))
    if tc is not None:
        req["tool_choice"] = tc
    return req


# ── response translation: OpenAI → Anthropic ─────────────────────────────────

_FINISH_REASON_MAP = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "content_filter": "refusal",
    "function_call": "tool_use",
}


class _StreamContext:
    """Async context manager mirroring the Anthropic SDK's stream object.

    Text deltas are re-emitted live (so the child still sees Bede type in real
    time). Tool calls are accumulated across OpenAI chunks by index, then
    replayed at end-of-stream as one clean
    start → input_json_delta → stop triple per call — which is exactly the
    sequence ai_service's tool buffer expects (it only acts on
    content_block_stop, and its input_json_delta handler assumes a single open
    block, so emitting each tool's triple in full before the next keeps that
    invariant)."""

    def __init__(self, client: "OpenAICompatibleClient", request: Dict[str, Any]) -> None:
        self._client = client
        self._request = request
        self._raw = None
        self._final: Optional[AdapterMessage] = None

    async def __aenter__(self) -> "_StreamContext":
        self._raw = await self._client._openai.chat.completions.create(
            stream=True,
            stream_options={"include_usage": True},
            **self._request,
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        close = getattr(self._raw, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:
                pass

    async def __aiter__(self):
        text_parts: List[str] = []
        # index → {"id","name","args"} preserving first-seen order
        tool_calls: "Dict[int, Dict[str, str]]" = {}
        usage = AdapterUsage()
        finish_reason: Optional[str] = None

        async for chunk in self._raw:
            ch_usage = getattr(chunk, "usage", None)
            if ch_usage is not None:
                usage = AdapterUsage(
                    input_tokens=getattr(ch_usage, "prompt_tokens", 0) or 0,
                    output_tokens=getattr(ch_usage, "completion_tokens", 0) or 0,
                )
            if not getattr(chunk, "choices", None):
                continue
            choice = chunk.choices[0]
            if getattr(choice, "finish_reason", None):
                finish_reason = choice.finish_reason
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue

            text = getattr(delta, "content", None)
            if text:
                text_parts.append(text)
                yield StreamEvent(
                    type="content_block_delta",
                    delta=_Delta(type="text_delta", text=text),
                )

            for tc in getattr(delta, "tool_calls", None) or []:
                idx = getattr(tc, "index", 0) or 0
                slot = tool_calls.setdefault(idx, {"id": "", "name": "", "args": ""})
                if getattr(tc, "id", None):
                    slot["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        slot["args"] += fn.arguments

        # Replay accumulated tool calls as clean Anthropic event triples.
        content_blocks: List[Any] = []
        if text_parts:
            content_blocks.append(TextBlock("".join(text_parts)))

        for idx in sorted(tool_calls):
            slot = tool_calls[idx]
            if not slot["name"]:
                continue
            call_id = slot["id"] or f"call_{idx}"
            yield StreamEvent(
                type="content_block_start",
                index=idx,
                content_block=ToolUseBlock(id=call_id, name=slot["name"], input={}),
            )
            if slot["args"]:
                yield StreamEvent(
                    type="content_block_delta",
                    index=idx,
                    delta=_Delta(type="input_json_delta", partial_json=slot["args"]),
                )
            yield StreamEvent(type="content_block_stop", index=idx)
            try:
                parsed = json.loads(slot["args"]) if slot["args"] else {}
            except json.JSONDecodeError:
                parsed = {}
            content_blocks.append(ToolUseBlock(id=call_id, name=slot["name"], input=parsed))

        self._final = AdapterMessage(
            content=content_blocks,
            usage=usage,
            stop_reason=_FINISH_REASON_MAP.get(finish_reason or "", finish_reason),
            model=self._request.get("model", ""),
        )

    async def get_final_message(self) -> AdapterMessage:
        if self._final is None:
            self._final = AdapterMessage(content=[], usage=AdapterUsage())
        return self._final


class _Messages:
    def __init__(self, client: "OpenAICompatibleClient") -> None:
        self._client = client

    def stream(self, **kwargs: Any) -> _StreamContext:
        request = _build_request(self._client._model, kwargs)
        return _StreamContext(self._client, request)

    async def create(self, **kwargs: Any) -> AdapterMessage:
        request = _build_request(self._client._model, kwargs)
        resp = await self._client._openai.chat.completions.create(**request)
        choice = resp.choices[0]
        msg = choice.message

        content_blocks: List[Any] = []
        if getattr(msg, "content", None):
            content_blocks.append(TextBlock(msg.content))
        for tc in getattr(msg, "tool_calls", None) or []:
            fn = getattr(tc, "function", None)
            if fn is None:
                continue
            try:
                parsed = json.loads(fn.arguments) if fn.arguments else {}
            except json.JSONDecodeError:
                parsed = {}
            content_blocks.append(
                ToolUseBlock(id=getattr(tc, "id", "") or "", name=fn.name, input=parsed)
            )

        ch_usage = getattr(resp, "usage", None)
        usage = AdapterUsage(
            input_tokens=getattr(ch_usage, "prompt_tokens", 0) or 0 if ch_usage else 0,
            output_tokens=getattr(ch_usage, "completion_tokens", 0) or 0 if ch_usage else 0,
        )
        return AdapterMessage(
            content=content_blocks,
            usage=usage,
            stop_reason=_FINISH_REASON_MAP.get(
                choice.finish_reason or "", choice.finish_reason
            ),
            model=getattr(resp, "model", request.get("model", "")),
        )


class OpenAICompatibleClient:
    """Anthropic-shaped `_client` backed by any OpenAI-compatible endpoint.

    `base_url` empty ⇒ real OpenAI; set it to e.g.
    `http://gpu-box.lan:8000/v1` for a self-hosted vLLM server. `api_key` is
    still required by the OpenAI SDK even for a keyless local server — pass any
    non-empty placeholder (see `local_llm_api_key`'s default)."""

    def __init__(self, *, base_url: str = "", api_key: str = "", model: str = "") -> None:
        # Lazy import: keeps `openai` off the import path for Anthropic-only
        # (default) deployments — see this module's docstring.
        from openai import AsyncOpenAI

        client_kwargs: Dict[str, Any] = {"api_key": api_key or "not-needed"}
        if base_url:
            client_kwargs["base_url"] = base_url
        self._openai = AsyncOpenAI(**client_kwargs)
        self._model = model
        self.messages = _Messages(self)
