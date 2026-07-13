"""get_provider() picks AnthropicProvider vs LocalProvider off settings.model_provider."""
import services.model_providers as providers
from core.config import settings
from services.model_providers.anthropic_provider import AnthropicProvider
from services.model_providers.local_provider import LocalProvider


def _reset():
    providers._provider_instance = None


def test_defaults_to_anthropic_provider(monkeypatch):
    monkeypatch.setattr(settings, "model_provider", "anthropic")
    _reset()
    assert isinstance(providers.get_provider(), AnthropicProvider)
    _reset()


def test_local_selects_local_provider(monkeypatch):
    monkeypatch.setattr(settings, "model_provider", "local")
    monkeypatch.setattr(settings, "local_model_name", "llama3.1:8b")
    _reset()
    assert isinstance(providers.get_provider(), LocalProvider)
    _reset()


def test_provider_instance_is_cached_across_calls(monkeypatch):
    monkeypatch.setattr(settings, "model_provider", "anthropic")
    _reset()
    first = providers.get_provider()
    second = providers.get_provider()
    assert first is second
    _reset()
