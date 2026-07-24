"""
core/provider_state.py — the DB-backed "which configured adapter is
primary" override, and its live effect on services/adapters/router.py's
FailoverClient. Mirrors tests/test_license_state.py's shape for the same
"DB value wins over env, live, no restart" precedent.
"""
from types import SimpleNamespace

import pytest

from core import provider_state
from services.adapters import router as adapter_router
from services.adapters.openai_compatible_adapter import OpenAICompatibleClient


@pytest.fixture(autouse=True)
def _reset_cache():
    yield
    provider_state._set_cached_primary(None)


def _settings(**overrides):
    base = dict(
        bede_force_adapter="",
        bede_adapter_order="local,anthropic",
        anthropic_api_key="",
        local_llm_base_url="",
        local_llm_api_key="not-needed",
        local_llm_model="qwen3:8b",
        openai_api_key="",
        openai_model="gpt-4.1-mini",
        mistral_api_key="",
        mistral_model="mistral-large-latest",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ── effective_order() — pure reordering logic ────────────────────────────────

def test_no_override_leaves_order_unchanged():
    assert provider_state.effective_order(["local", "mistral"]) == ["local", "mistral"]


def test_override_moves_chosen_provider_to_front():
    provider_state._set_cached_primary("mistral")
    assert provider_state.effective_order(["local", "mistral"]) == ["mistral", "local"]


def test_stale_override_for_unconfigured_provider_is_ignored():
    """A DB override naming a provider whose credentials were since removed
    from .env must fall back to the env order silently, not break service."""
    provider_state._set_cached_primary("openai")
    assert provider_state.effective_order(["local", "mistral"]) == ["local", "mistral"]


# ── DB round trip (real SQLite, like test_license_state's demo_db tests) ─────

@pytest.mark.asyncio
async def test_set_primary_persists_and_applies_live(demo_db):
    async with demo_db() as db:
        assert provider_state.current_primary() is None
        await provider_state.set_primary(db, "mistral")
        assert provider_state.current_primary() == "mistral"

        from core.database import AIProviderOverride
        row = await db.get(AIProviderOverride, "primary")
        assert row is not None and row.provider == "mistral"


@pytest.mark.asyncio
async def test_refresh_from_db_picks_up_a_value_set_before_this_process(demo_db):
    async with demo_db() as db:
        from core.database import AIProviderOverride
        db.add(AIProviderOverride(key="primary", provider="local"))
        await db.commit()

        assert provider_state.current_primary() is None  # cache not yet synced
        await provider_state.refresh_from_db(db)
        assert provider_state.current_primary() == "local"


@pytest.mark.asyncio
async def test_clear_primary_removes_row_and_reverts_cache(demo_db):
    async with demo_db() as db:
        await provider_state.set_primary(db, "mistral")
        await provider_state.clear_primary(db)
        assert provider_state.current_primary() is None

        from core.database import AIProviderOverride
        assert await db.get(AIProviderOverride, "primary") is None


@pytest.mark.asyncio
async def test_set_primary_overwrites_existing_row(demo_db):
    async with demo_db() as db:
        await provider_state.set_primary(db, "mistral")
        await provider_state.set_primary(db, "local")
        assert provider_state.current_primary() == "local"

        from core.database import AIProviderOverride
        row = await db.get(AIProviderOverride, "primary")
        assert row.provider == "local"


# ── Live effect on the failover router ───────────────────────────────────────

def test_failover_live_order_honors_db_override():
    s = _settings(
        bede_adapter_order="local,mistral",
        local_llm_base_url="http://gpu-box.lan:8000/v1",
        mistral_api_key="sk-mistral",
    )
    fc = adapter_router.FailoverClient(s)
    assert fc._live_order() == ["local", "mistral"]

    provider_state._set_cached_primary("mistral")
    assert fc._live_order() == ["mistral", "local"]


def test_get_default_client_honors_db_override():
    s = _settings(
        bede_adapter_order="local,mistral",
        local_llm_base_url="http://gpu-box.lan:8000/v1",
        mistral_api_key="sk-mistral",
    )
    provider_state._set_cached_primary("mistral")
    client = adapter_router.get_default_client(s)
    assert isinstance(client, OpenAICompatibleClient)
    assert str(client._openai.base_url).rstrip("/").endswith("mistral.ai/v1")


def test_force_adapter_still_wins_over_db_override():
    """A BEDE_FORCE_ADAPTER pin is a stronger, explicit operator decision —
    a parent's live DB override must not be able to bypass it, since
    _configured_order() only ever contains the forced adapter to begin
    with when it's set."""
    s = _settings(
        bede_force_adapter="anthropic",
        bede_adapter_order="local,anthropic",
        anthropic_api_key="sk-ant",
        local_llm_base_url="http://gpu-box.lan:8000/v1",
    )
    provider_state._set_cached_primary("local")
    fc = adapter_router.FailoverClient(s)
    assert fc._live_order() == ["anthropic"]


# ── configured_adapters()/preference_order() public helpers ─────────────────

def test_configured_adapters_lists_only_credentialed_providers():
    s = _settings(anthropic_api_key="sk-ant", mistral_api_key="sk-m")
    assert adapter_router.configured_adapters(s) == ["mistral", "anthropic"]


def test_preference_order_is_the_env_order():
    s = _settings(bede_adapter_order="mistral,local,anthropic")
    assert adapter_router.preference_order(s) == ["mistral", "local", "anthropic"]


# ── GET/POST /admin/ai-provider — drives the real handlers against a real
#    (SQLite) DB, same pattern as test_license_state's endpoint test ─────────

from unittest.mock import MagicMock

from fastapi import HTTPException

from core.config import settings as real_settings
from routers.admin import SetAIProviderRequest, ai_provider_status, set_ai_provider


def _fake_request():
    request = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers = {}
    return request


@pytest.fixture(autouse=True)
def _restore_real_settings(monkeypatch):
    # conftest.py sets ANTHROPIC_API_KEY globally so unrelated tests can
    # boot ai_service; clear it here so these tests control exactly which
    # adapters are "configured" instead of always finding anthropic too.
    monkeypatch.setattr(real_settings, "anthropic_api_key", "")
    monkeypatch.setattr(real_settings, "bede_adapter_order", "local,anthropic")
    monkeypatch.setattr(real_settings, "bede_force_adapter", "")
    monkeypatch.setattr(real_settings, "local_llm_base_url", "")
    monkeypatch.setattr(real_settings, "mistral_api_key", "")
    monkeypatch.setattr(real_settings, "openai_api_key", "")
    yield


@pytest.mark.asyncio
async def test_set_ai_provider_endpoint_rejects_unknown_provider(demo_db):
    async with demo_db() as db:
        with pytest.raises(HTTPException) as exc_info:
            await set_ai_provider(SetAIProviderRequest(provider="ollama"), _fake_request(), db=db, _={})
        assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_set_ai_provider_endpoint_rejects_unconfigured_provider(demo_db, monkeypatch):
    monkeypatch.setattr(real_settings, "mistral_api_key", "")  # explicitly unconfigured
    async with demo_db() as db:
        with pytest.raises(HTTPException) as exc_info:
            await set_ai_provider(SetAIProviderRequest(provider="mistral"), _fake_request(), db=db, _={})
        assert exc_info.value.status_code == 422
        assert "mistral" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_set_ai_provider_endpoint_applies_override_live(demo_db, monkeypatch):
    monkeypatch.setattr(real_settings, "bede_adapter_order", "local,mistral")
    monkeypatch.setattr(real_settings, "local_llm_base_url", "http://gpu-box.lan:8000/v1")
    monkeypatch.setattr(real_settings, "mistral_api_key", "sk-mistral")

    async with demo_db() as db:
        result = await set_ai_provider(SetAIProviderRequest(provider="mistral"), _fake_request(), db=db, _={})
        assert result["primary"] == "mistral"
        assert result["override"] == "mistral"
        assert result["effective_order"] == ["mistral", "local"]

        status = await ai_provider_status(_={})
        assert status["primary"] == "mistral"


@pytest.mark.asyncio
async def test_set_ai_provider_endpoint_clears_override(demo_db, monkeypatch):
    monkeypatch.setattr(real_settings, "bede_adapter_order", "local,mistral")
    monkeypatch.setattr(real_settings, "local_llm_base_url", "http://gpu-box.lan:8000/v1")
    monkeypatch.setattr(real_settings, "mistral_api_key", "sk-mistral")

    async with demo_db() as db:
        await set_ai_provider(SetAIProviderRequest(provider="mistral"), _fake_request(), db=db, _={})
        result = await set_ai_provider(SetAIProviderRequest(provider=None), _fake_request(), db=db, _={})
        assert result["override"] is None
        assert result["primary"] == "local"
