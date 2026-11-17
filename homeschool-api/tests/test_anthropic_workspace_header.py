"""
ANTHROPIC_WORKSPACE_ID: an organization-level Anthropic key is refused
("API key is not scoped to a workspace") unless every request names the
workspace to bill in the anthropic-workspace-id header. Found live on the demo
on 2026-11-17, when the backup provider failed every lesson for that reason.

These tests send a real request through the real SDK client the router builds,
into a mock transport, and read the header off the wire: a client constructed
with the right argument proves nothing if the request does not carry it.
"""

import httpx2 as httpx  # the transport the Anthropic SDK itself uses
import pytest
from pydantic import ValidationError

from core.config import Settings, settings
from services.adapters import router


def _anthropic_settings(**overrides):
    return settings.model_copy(update={
        "anthropic_api_key": "sk-ant-test",
        "bede_force_adapter": "anthropic",
        "bede_offline_installation": False,
        **overrides,
    })


async def _headers_sent(client) -> httpx.Headers:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "m",
            "content": [{"type": "text", "text": "OK"}], "stop_reason": "end_turn",
            "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    wired = client.with_options(http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await wired.messages.create(model="m", max_tokens=5,
                                messages=[{"role": "user", "content": "hi"}])
    return seen["headers"]


@pytest.mark.asyncio
async def test_the_workspace_header_reaches_the_wire():
    client = router._build("anthropic", _anthropic_settings(anthropic_workspace_id="wrkspc_01Abc-x"))
    headers = await _headers_sent(client)
    assert headers["anthropic-workspace-id"] == "wrkspc_01Abc-x"


@pytest.mark.asyncio
async def test_no_header_without_a_workspace_id():
    client = router._build("anthropic", _anthropic_settings(anthropic_workspace_id=""))
    headers = await _headers_sent(client)
    assert "anthropic-workspace-id" not in headers


@pytest.mark.asyncio
async def test_the_failover_client_path_carries_it_too():
    # The path real lessons take: the failover client builds each adapter itself.
    fc = router.FailoverClient(_anthropic_settings(anthropic_workspace_id="wrkspc_9"))
    client = fc._adapter("anthropic")
    headers = await _headers_sent(client)
    assert headers["anthropic-workspace-id"] == "wrkspc_9"


@pytest.mark.parametrize("bad", ["wrk spc", "wrk\r\nX-Evil: 1", "wrkspc;", "a/b", "x" * 129])
def test_a_value_that_is_not_a_plain_token_fails_at_boot(bad):
    with pytest.raises(ValidationError):
        Settings(anthropic_workspace_id=bad)


def test_blank_and_surrounding_space_are_cleaned():
    assert Settings(anthropic_workspace_id="  ").anthropic_workspace_id == ""
    assert Settings(anthropic_workspace_id=" wrkspc_1 ").anthropic_workspace_id == "wrkspc_1"

