"""Provider-adapter layer + account-closure resilience.

The whole services/adapters/ refactor exists for one trigger case: the
deployment can NO LONGER rely on Anthropic at all (account closed/denied). These
tests validate that case explicitly —

1. the router never requires ANTHROPIC_API_KEY to boot or serve, and with a
   local (OpenAI-compatible/vLLM) provider configured it resolves `_client` to
   that adapter instead of Anthropic;
2. stream_tutor_response() and generate_session_summary() work END TO END
   against a mocked non-Anthropic adapter, proving the Anthropic-shape
   translation in openai_compatible_adapter.py is what ai_service consumes;
3. the ~20 existing tests' contract — `_client.messages.stream`/`.create` with
   Anthropic-shaped I/O — holds identically regardless of which concrete adapter
   backs `_client`.

The non-Anthropic backend is faked at the `openai` SDK boundary (a fake
AsyncOpenAI returning OpenAI-wire-shaped chunks), so the adapter's real
translation code runs — not a stubbed-out adapter.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from models.schemas import (
    ChatMessage,
    GradeStage,
    SessionConfig,
    SessionSummaryRequest,
    Subject,
)
from services import ai_service
from services.adapters import router
from services.adapters.openai_compatible_adapter import (
    OpenAICompatibleClient,
    _build_request,
    _flatten_system,
    _translate_tools,
)


# ── a settings stand-in the router can read ──────────────────────────────────

def _settings(**overrides):
    base = dict(
        bede_force_adapter="",
        bede_adapter_order="local,anthropic",
        anthropic_api_key="",
        local_llm_base_url="",
        local_llm_api_key="not-needed",
        local_llm_model="Qwen/Qwen3-Coder-30B-A3B-Instruct",
        openai_api_key="",
        openai_model="gpt-4.1-mini",
        mistral_api_key="",
        mistral_model="mistral-large-latest",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _cls(obj):
    return type(obj).__name__


# ── 1. router resolution under an Anthropic account closure ──────────────────

def test_default_order_is_not_anthropic_first():
    """Regression guard on the core design decision: the zero-config default
    must NOT put Anthropic first, or a closed account silently breaks boot."""
    from core.config import Settings

    order = Settings().bede_adapter_order.split(",")
    assert order[0].strip() == "local"
    assert "anthropic" in [o.strip() for o in order]


def test_account_closure_resolves_to_local_adapter_without_anthropic_key():
    s = _settings(anthropic_api_key="", local_llm_base_url="http://gpu-box.lan:8000/v1")
    client = router.get_default_client(s)
    assert isinstance(client, OpenAICompatibleClient)
    # And it must not have needed an Anthropic key to get there.
    assert s.anthropic_api_key == ""


def test_router_never_raises_when_nothing_is_configured():
    """App must still boot even with zero providers configured — construction is
    lazy, so only a real request would surface the misconfiguration."""
    s = _settings(anthropic_api_key="", local_llm_base_url="")
    client = router.get_default_client(s)  # must not raise
    assert client is not None


def test_legacy_anthropic_only_deployment_still_resolves_to_anthropic():
    s = _settings(anthropic_api_key="sk-ant-xyz", local_llm_base_url="")
    client = router.get_default_client(s)
    assert _cls(client) == "AsyncAnthropic"


def test_tts_openai_key_alone_does_not_hijack_the_tutor():
    """OPENAI_API_KEY exists for TTS; with the default order it must NOT route
    the tutor through OpenAI — only Anthropic (configured) should win here."""
    s = _settings(anthropic_api_key="sk-ant", openai_api_key="sk-openai-for-tts")
    client = router.get_default_client(s)
    assert _cls(client) == "AsyncAnthropic"


def test_openai_selected_only_when_explicitly_in_order():
    s = _settings(
        bede_adapter_order="local,openai,anthropic",
        anthropic_api_key="sk-ant",
        openai_api_key="sk-openai",
    )
    client = router.get_default_client(s)
    assert isinstance(client, OpenAICompatibleClient)


def test_force_adapter_overrides_order():
    s = _settings(
        bede_force_adapter="anthropic",
        bede_adapter_order="local,anthropic",
        anthropic_api_key="sk-ant",
        local_llm_base_url="http://gpu-box.lan:8000/v1",
    )
    assert _cls(router.get_default_client(s)) == "AsyncAnthropic"


def test_mistral_adapter_builds_against_its_endpoint():
    s = _settings(bede_force_adapter="mistral", mistral_api_key="sk-m")
    client = router.get_default_client(s)
    assert isinstance(client, OpenAICompatibleClient)
    assert str(client._openai.base_url).rstrip("/").endswith("mistral.ai/v1")


# ── 2. end-to-end through a fake OpenAI-compatible backend ───────────────────

def _oa_text_chunk(text):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None), finish_reason=None)],
        usage=None,
    )


def _oa_tool_chunks(tool_id, name, arguments_json):
    """OpenAI streams a tool call as a first chunk carrying id+name, then
    argument fragments — mirror that so the adapter's accumulation runs."""
    first = SimpleNamespace(
        choices=[SimpleNamespace(
            delta=SimpleNamespace(content=None, tool_calls=[
                SimpleNamespace(index=0, id=tool_id,
                                function=SimpleNamespace(name=name, arguments="")),
            ]),
            finish_reason=None,
        )],
        usage=None,
    )
    frag = SimpleNamespace(
        choices=[SimpleNamespace(
            delta=SimpleNamespace(content=None, tool_calls=[
                SimpleNamespace(index=0, id=None,
                                function=SimpleNamespace(name=None, arguments=arguments_json)),
            ]),
            finish_reason="tool_calls",
        )],
        usage=None,
    )
    return [first, frag]


def _oa_usage_chunk(prompt_tokens, completion_tokens):
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


class _FakeAsyncStream:
    def __init__(self, chunks):
        self._chunks = chunks

    async def __aiter__(self):
        for c in self._chunks:
            yield c

    async def close(self):
        pass


class _FakeCompletions:
    def __init__(self, stream_chunks=None, create_response=None):
        self._stream_chunks = stream_chunks or []
        self._create_response = create_response

    async def create(self, **kwargs):
        if kwargs.get("stream"):
            return _FakeAsyncStream(self._stream_chunks)
        return self._create_response


def _fake_openai_client(stream_chunks=None, create_response=None):
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=_FakeCompletions(stream_chunks, create_response)
        ),
        base_url="http://gpu-box.lan:8000/v1",
    )


def _local_adapter_with(stream_chunks=None, create_response=None):
    client = OpenAICompatibleClient(
        base_url="http://gpu-box.lan:8000/v1",
        api_key="not-needed",
        model="Qwen/Qwen3-Coder-30B-A3B-Instruct",
    )
    client._openai = _fake_openai_client(stream_chunks, create_response)
    return client


def _config():
    return SessionConfig(student_name="Guest", grade="4", grade_stage=GradeStage.core_mastery)


@pytest.mark.asyncio
async def test_stream_tutor_response_end_to_end_over_local_adapter(monkeypatch):
    """The exact account-closure path: _client is a non-Anthropic adapter and a
    full tutor turn still streams text + a done event, with usage captured."""
    chunks = [
        _oa_text_chunk("The river "),
        _oa_text_chunk("carves the canyon."),
        _oa_usage_chunk(1200, 42),
    ]
    adapter = _local_adapter_with(stream_chunks=chunks)
    monkeypatch.setattr(ai_service, "_client", adapter)

    record = AsyncMock()
    with patch("core.api_usage.record_usage", record):
        out = [
            json.loads(c)
            async for c in ai_service.stream_tutor_response(
                config=_config(),
                subject=Subject.living_books,
                history=[],
                child_message="Tell me about the river.",
            )
        ]

    text = "".join(p["content"] for p in out if p["type"] == "text")
    assert text == "The river carves the canyon."
    assert out[-1] == {"type": "done"}
    record.assert_awaited()
    assert record.await_args.kwargs["input_tokens"] == 1200
    assert record.await_args.kwargs["output_tokens"] == 42


@pytest.mark.asyncio
async def test_tool_call_translation_end_to_end_over_local_adapter(monkeypatch):
    """A tool call streamed in OpenAI shape must surface as an Anthropic-shaped
    tool event ai_service formats into an SSE 'tool' chunk."""
    args = json.dumps({"specific_insight": "the river carves the canyon",
                       "encouragement": "That's real thinking!"})
    chunks = [
        *_oa_tool_chunks("call_1", "celebrate_discovery", args),
        _oa_usage_chunk(800, 30),
    ]
    adapter = _local_adapter_with(stream_chunks=chunks)
    monkeypatch.setattr(ai_service, "_client", adapter)

    with patch("core.api_usage.record_usage", AsyncMock()):
        out = [
            json.loads(c)
            async for c in ai_service.stream_tutor_response(
                config=_config(),
                subject=Subject.living_books,
                history=[],
                child_message="I figured out how canyons form!",
            )
        ]

    tool_chunks = [p for p in out if p["type"] == "tool"]
    assert tool_chunks, "the OpenAI-shaped tool call did not translate to a tool event"
    assert tool_chunks[0]["tool"] == "celebrate_discovery"
    assert out[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_empty_response_fallback_over_local_adapter(monkeypatch):
    """No content blocks at all (the refusal/empty case) must still trigger
    ai_service's fallback text, proving get_final_message().content is honored."""
    adapter = _local_adapter_with(stream_chunks=[_oa_usage_chunk(10, 0)])
    monkeypatch.setattr(ai_service, "_client", adapter)

    with patch("core.api_usage.record_usage", AsyncMock()):
        out = [
            json.loads(c)
            async for c in ai_service.stream_tutor_response(
                config=_config(),
                subject=Subject.living_books,
                history=[],
                child_message="[START]",
            )
        ]

    text = "".join(p["content"] for p in out if p["type"] == "text")
    assert "let's try something else" in text
    assert out[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_session_summary_end_to_end_over_local_adapter(monkeypatch):
    """generate_session_summary uses .messages.create (non-streaming) — verify
    the adapter's create() translation yields content[0].text + usage."""
    create_response = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content="A warm, specific summary for the parent.", tool_calls=None),
            finish_reason="stop",
        )],
        usage=SimpleNamespace(prompt_tokens=900, completion_tokens=250),
        model="Qwen/Qwen3-Coder-30B-A3B-Instruct",
    )
    adapter = _local_adapter_with(create_response=create_response)
    monkeypatch.setattr(ai_service, "_client", adapter)

    req = SessionSummaryRequest(
        session_config=_config(),
        conversation_history=[ChatMessage(role="user", content="hi")],
        subjects_completed=[Subject.mathematics],
        duration_minutes=45,
    )
    record = AsyncMock()
    with patch("core.api_usage.record_usage", record):
        summary = await ai_service.generate_session_summary(req)

    assert summary == "A warm, specific summary for the parent."
    record.assert_awaited_once()
    assert record.await_args.kwargs["input_tokens"] == 900
    assert record.await_args.kwargs["output_tokens"] == 250


# ── 3. request-translation unit checks (Anthropic shape → OpenAI shape) ──────

def test_flatten_system_handles_string_and_cached_block_list():
    assert _flatten_system("plain") == "plain"
    blocks = [
        {"type": "text", "text": "static persona", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "subject block"},
    ]
    assert _flatten_system(blocks) == "static persona\n\nsubject block"


def test_translate_tools_maps_input_schema_and_drops_cache_control():
    tools = [{
        "name": "celebrate_discovery",
        "description": "Celebrate a genuine insight.",
        "input_schema": {"type": "object", "properties": {"specific_insight": {"type": "string"}}},
        "cache_control": {"type": "ephemeral"},
    }]
    out = _translate_tools(tools)
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "celebrate_discovery"
    assert out[0]["function"]["parameters"]["properties"]["specific_insight"]["type"] == "string"
    assert "cache_control" not in out[0]["function"]


def test_build_request_moves_system_into_a_system_role_message():
    req = _build_request(
        "some-model",
        {
            "system": [{"type": "text", "text": "You are Bede."}],
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 400,
        },
    )
    assert req["model"] == "some-model"
    assert req["messages"][0] == {"role": "system", "content": "You are Bede."}
    assert req["messages"][1] == {"role": "user", "content": "Hello"}
    assert req["max_tokens"] == 400


# ── 4. failover router (Phase 6) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failover_create_falls_through_to_the_next_adapter():
    """A primary raising an auth-style error must transparently fail over to the
    next configured adapter, and the breaker should mark the primary down."""
    s = _settings(
        bede_adapter_order="local,anthropic",
        anthropic_api_key="sk-ant",
        local_llm_base_url="http://gpu-box.lan:8000/v1",
    )
    fc = router.FailoverClient(s)

    ok_result = object()
    good = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=ok_result)))
    bad = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=ConnectionError("down"))))
    fc._built = {"local": bad, "anthropic": good}

    result = await fc.messages.create(model="m", messages=[])
    assert result is ok_result
    assert fc._breaker.is_open("local")


def test_ai_service_client_is_wired_through_the_failover_router():
    """ai_service._client must be a FailoverClient (Phase-6 live failover),
    not the plain first-configured-adapter resolver — otherwise a primary
    outage (e.g. Mistral erroring while its key is still valid on the Render
    demo) would never fail over to the secondary mid-request."""
    assert isinstance(ai_service._client, router.FailoverClient)
    # And the drop-in contract every existing test relies on must still hold:
    # a stable .messages object exposing .stream/.create, so
    # patch.object(ai_service._client.messages, "stream"/"create", ...) works
    # exactly as it did against a single adapter.
    assert hasattr(ai_service._client.messages, "stream")
    assert hasattr(ai_service._client.messages, "create")


@pytest.mark.asyncio
async def test_generate_session_summary_fails_over_to_the_next_adapter(monkeypatch):
    """End-to-end through ai_service: if the primary adapter's create() raises
    an auth/connection-style error, generate_session_summary() must still
    succeed by transparently retrying the next configured adapter, instead of
    surfacing the primary's failure to the caller."""
    s = _settings(
        bede_adapter_order="mistral,openai",
        mistral_api_key="sk-mistral",  # both configured; fake adapters injected below
        openai_api_key="sk-openai",
    )
    fc = router.FailoverClient(s)
    fake_response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="All done for today!")],
        usage=SimpleNamespace(input_tokens=900, output_tokens=250),
    )
    bad = SimpleNamespace(
        messages=SimpleNamespace(create=AsyncMock(side_effect=ConnectionError("mistral down")))
    )
    good = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
    fc._built = {"mistral": bad, "openai": good}
    monkeypatch.setattr(ai_service, "_client", fc)

    req = SessionSummaryRequest(
        session_config=_config(),
        conversation_history=[ChatMessage(role="user", content="We finished our math lesson.")],
        subjects_completed=[Subject.mathematics],
        duration_minutes=30,
    )
    record = AsyncMock()
    with patch("core.api_usage.record_usage", record):
        result = await ai_service.generate_session_summary(req)

    assert result == "All done for today!"
    bad.messages.create.assert_awaited()
    good.messages.create.assert_awaited()
    assert fc._breaker.is_open("mistral")
    record.assert_awaited_once()


@pytest.mark.asyncio
async def test_failover_skips_a_tripped_adapter_on_the_next_call():
    s = _settings(
        bede_adapter_order="local,anthropic",
        anthropic_api_key="sk-ant",
        local_llm_base_url="http://gpu-box.lan:8000/v1",
    )
    fc = router.FailoverClient(s)
    good = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value="ok")))
    bad = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=ConnectionError("down"))))
    fc._built = {"local": bad, "anthropic": good}

    await fc.messages.create(model="m", messages=[])       # trips local
    bad.messages.create.reset_mock()
    await fc.messages.create(model="m", messages=[])       # should skip local entirely
    bad.messages.create.assert_not_awaited()
