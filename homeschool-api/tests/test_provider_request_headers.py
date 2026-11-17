"""
AI_PROVIDER_HEADERS and per-server MCP headers (core/request_headers.py).

Prompted by 2026-11-17: the demo's Claude backup was refused because an
organization-level Anthropic key needs an anthropic-workspace-id header. The
fix is general rather than one named setting: any provider, any header the
provider needs beyond its key, and any MCP server's key.

Provider tests send a real request through the real SDK client the router
builds, into a mock transport, and read the headers off the wire. A client
constructed with the right argument proves nothing if the request does not
carry it.
"""

import json

import httpx
import httpx2  # the transport the Anthropic SDK itself uses
import pytest
from pydantic import ValidationError

from core.config import Settings, settings
from core.request_headers import (
    PROVIDER_ADAPTERS, HeaderConfigError, check_headers, parse_provider_headers,
)
from services import mcp_client
from services.adapters import router

_ANTHROPIC_REPLY = {
    "id": "msg_1", "type": "message", "role": "assistant", "model": "m",
    "content": [{"type": "text", "text": "OK"}], "stop_reason": "end_turn",
    "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
}
_OPENAI_REPLY = {
    "id": "c1", "object": "chat.completion", "created": 0, "model": "m",
    "choices": [{"index": 0, "finish_reason": "stop",
                 "message": {"role": "assistant", "content": "OK"}}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


def _settings(headers: dict | None = None, **overrides):
    return settings.model_copy(update={
        "anthropic_api_key": "sk-ant-test",
        "openai_api_key": "sk-openai-test",
        "mistral_api_key": "mistral-test",
        "bede_offline_installation": False,
        "ai_provider_headers": json.dumps(headers) if headers else "",
        **overrides,
    })


async def _anthropic_headers(client) -> httpx2.Headers:
    seen = {}

    def handler(request):
        seen["h"] = request.headers
        return httpx2.Response(200, json=_ANTHROPIC_REPLY)

    wired = client.with_options(http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    await wired.messages.create(model="m", max_tokens=5, messages=[{"role": "user", "content": "hi"}])
    return seen["h"]


async def _openai_headers(adapter) -> httpx.Headers:
    seen = {}

    def handler(request):
        seen["h"] = request.headers
        return httpx.Response(200, json=_OPENAI_REPLY)

    sdk = adapter._openai.with_options(http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await sdk.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}])
    return seen["h"]


# ── Providers: the headers reach the wire ────────────────────────────────────

@pytest.mark.asyncio
async def test_claude_workspace_header_reaches_the_wire():
    s = _settings({"anthropic": {"anthropic-workspace-id": "wrkspc_01Abc-x"}})
    headers = await _anthropic_headers(router._build("anthropic", s))
    assert headers["anthropic-workspace-id"] == "wrkspc_01Abc-x"
    assert headers["x-api-key"] == "sk-ant-test"  # the key still comes from its own setting


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["openai", "mistral"])
async def test_openai_compatible_providers_send_their_headers(name):
    s = _settings({name: {"OpenAI-Project": "proj_1", "X-Gateway": "a b"}})
    headers = await _openai_headers(router._build(name, s))
    assert headers["openai-project"] == "proj_1"
    assert headers["x-gateway"] == "a b"


@pytest.mark.asyncio
async def test_headers_go_only_to_the_provider_they_name():
    s = _settings({"anthropic": {"anthropic-workspace-id": "wrkspc_1"}})
    assert "anthropic-workspace-id" not in await _openai_headers(router._build("openai", s))


@pytest.mark.asyncio
async def test_no_setting_means_no_extra_headers():
    headers = await _anthropic_headers(router._build("anthropic", _settings()))
    assert "anthropic-workspace-id" not in headers


@pytest.mark.asyncio
async def test_the_failover_client_path_carries_them():
    # The path real lessons take: the failover client builds each adapter itself.
    fc = router.FailoverClient(_settings({"anthropic": {"anthropic-workspace-id": "wrkspc_9"}}))
    headers = await _anthropic_headers(fc._adapter("anthropic"))
    assert headers["anthropic-workspace-id"] == "wrkspc_9"


def test_the_router_and_the_header_map_agree_on_which_providers_exist():
    assert tuple(router.KNOWN_ADAPTERS) == PROVIDER_ADAPTERS


# ── Providers: bad config fails at boot, in plain words ──────────────────────

@pytest.mark.parametrize("raw, fragment", [
    ('{"anthropc": {"a": "b"}}', "not a provider"),
    ('{"anthropic": {"bad name": "x"}}', "not a valid header name"),
    ('{"anthropic": {"X-A": "x\\r\\nX-Evil: 1"}}', "no line breaks"),
    ('{"anthropic": {"X-A": "x\\u0000"}}', "no line breaks"),
    ('{"anthropic": {"Host": "evil"}}', "cannot be configured"),
    ('{"anthropic": {"Content-Type": "text/plain"}}', "cannot be configured"),
    ('{"anthropic": {"Authorization": "Bearer x"}}', "own key setting"),
    ('{"openai": {"api-key": "x"}}', "own key setting"),
    ('{"anthropic": {"X-A": 5}}', "must be text"),
    ('{"anthropic": {"X-A": "1", "x-a": "2"}}', "set twice"),
    ('["anthropic"]', "keyed by provider"),
    ('{"anthropic": "x"}', "JSON object"),
])
def test_a_malformed_setting_fails_at_boot(raw, fragment):
    with pytest.raises(ValidationError) as caught:
        Settings(ai_provider_headers=raw)
    assert fragment in str(caught.value)


def test_too_many_headers_is_refused():
    with pytest.raises(HeaderConfigError):
        check_headers({f"X-{i}": "v" for i in range(17)}, where="t", allow_credentials=False)


def test_an_error_never_repeats_a_value():
    secret = "do-not-echo-123"
    for raw in ('{"anthropic": {"Authorization": "%s"}}' % secret,
                '{"anthropic": {"X-A": "%s\\n"}}' % secret,
                '{"anthropic": {"X-A": "%s"' % secret):
        with pytest.raises(ValidationError) as caught:
            Settings(ai_provider_headers=raw)
        assert secret not in str(caught.value)


@pytest.mark.parametrize("name, value", [("X-A", "ok\n"), ("X-A\n", "ok")])
def test_a_trailing_line_break_is_refused(name, value):
    # Python's `$` matches before a final newline; the check must not.
    with pytest.raises(HeaderConfigError):
        check_headers({name: value}, where="t", allow_credentials=False)


def test_blank_is_no_headers():
    assert parse_provider_headers("") == {}
    assert parse_provider_headers("   ") == {}


# ── MCP servers ──────────────────────────────────────────────────────────────

def _servers(entry: dict):
    return mcp_client.parse_servers(json.dumps([entry]))


def test_an_mcp_server_can_be_given_its_key():
    (server,) = _servers({"name": "books", "url": "https://books.example/mcp",
                          "headers": {"Authorization": "Bearer tok"}})
    assert server.headers == {"Authorization": "Bearer tok"}
    assert "tok" not in repr(server)  # a printed config never shows the key


@pytest.mark.asyncio
async def test_mcp_headers_reach_the_wire_and_cannot_replace_the_protocols():
    (server,) = _servers({"name": "books", "url": "https://books.example/mcp",
                          "headers": {"Authorization": "Bearer tok", "X-Tenant": "t1"}})
    seen = {}

    def handler(request):
        seen["h"] = request.headers
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})

    client = mcp_client.MCPServerClient(
        server, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await client._request("initialize", {})
    assert seen["h"]["authorization"] == "Bearer tok"
    assert seen["h"]["x-tenant"] == "t1"
    assert seen["h"]["mcp-protocol-version"] == mcp_client.MCP_PROTOCOL_VERSION


@pytest.mark.parametrize("headers", [
    {"Mcp-Session-Id": "x"}, {"MCP-Protocol-Version": "x"}, {"Host": "x"}, {"X-A": "a\nb"},
])
def test_mcp_headers_get_the_same_checks(headers):
    with pytest.raises(mcp_client.MCPConfigError):
        _servers({"name": "books", "url": "https://books.example/mcp", "headers": headers})


def test_a_key_is_never_sent_over_plain_http_except_to_this_machine():
    with pytest.raises(mcp_client.MCPConfigError, match="https"):
        _servers({"name": "books", "url": "http://192.168.1.20:9000/mcp",
                  "headers": {"Authorization": "Bearer tok"}})
    (local,) = _servers({"name": "books", "url": "http://localhost:9000/mcp",
                         "headers": {"Authorization": "Bearer tok"}})
    assert local.headers
    (plain,) = _servers({"name": "books", "url": "http://192.168.1.20:9000/mcp"})
    assert plain.headers == {}
