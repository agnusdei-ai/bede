"""
Normalizes any chat/tool-calling LLM backend behind one async interface, so
ai_service.py's Socratic-tutor logic (fallback questions, per-tool dispatch,
SSE framing) never has to know which model answered a turn — hosted Claude,
or a self-hosted model for an air-gapped deployment / a hedge against a
compromised upstream model. See docs/MODEL_PROVIDERS.md.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, List, Optional, Union


@dataclass
class TextDelta:
    """A chunk of assistant-visible text."""
    text: str


@dataclass
class ToolCall:
    """One fully-assembled tool invocation — providers buffer any wire-level
    streaming of partial tool-call JSON internally and only ever yield this
    once the call's input is complete and parsed."""
    id: str
    name: str
    input: dict


StreamEvent = Union[TextDelta, ToolCall]


class ModelProvider(ABC):
    """A pluggable tutor-model backend. Implementations translate their
    wire protocol into TextDelta/ToolCall events and back; everything above
    this interface (prompts, tool dispatch, SSE format) is provider-agnostic."""

    @abstractmethod
    def stream(
        self,
        *,
        system: Any,
        messages: List[dict],
        tools: Optional[List[dict]],
        max_tokens: int,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a tutor turn. `system` may be a plain string or Anthropic's
        cache_control block-list format — implementations that don't support
        prompt caching should flatten it to plain text. `tools` follows
        Anthropic's tool schema (name/description/input_schema); non-Anthropic
        providers translate to their own tool-calling format internally."""
        raise NotImplementedError
        yield  # pragma: no cover - makes this an async generator for type-checkers

    @abstractmethod
    async def complete(
        self,
        *,
        system: Optional[str],
        messages: List[dict],
        max_tokens: int,
    ) -> str:
        """Non-streaming completion, used for session summaries and learner
        profile synthesis — no tools, plain text in, plain text out."""
        raise NotImplementedError
