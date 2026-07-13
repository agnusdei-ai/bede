"""
Pluggable tutor-model backend. Defaults to hosted Claude (best tutoring
quality); MODEL_PROVIDER=local switches to any OpenAI-compatible self-hosted
backend for an air-gapped deployment, or as a hedge against a compromised
upstream model — see docs/MODEL_PROVIDERS.md.
"""
from core.config import settings

from .base import ModelProvider, StreamEvent, TextDelta, ToolCall

_provider_instance: "ModelProvider | None" = None


def get_provider() -> ModelProvider:
    """Returns the configured provider, lazily instantiated once and cached —
    same singleton-client pattern the old module-level Anthropic client used."""
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = _build_provider()
    return _provider_instance


def _build_provider() -> ModelProvider:
    if settings.model_provider == "local":
        from .local_provider import LocalProvider
        return LocalProvider()
    from .anthropic_provider import AnthropicProvider
    return AnthropicProvider()


__all__ = ["ModelProvider", "StreamEvent", "TextDelta", "ToolCall", "get_provider"]
