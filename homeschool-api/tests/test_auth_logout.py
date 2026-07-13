"""
Regression test for POST /auth/logout's demo_code revocation (routers/auth.py).

Real bug caught by this session's Fable-backed B4 review of the
demo-session-persistence rewrite: core.demo_code_session.end_session
became `async def` when that module moved off in-memory storage onto
Postgres, but the one call site inside logout() was never updated to
await it — `end_code_session(...)` silently created a coroutine object
and discarded it without ever running, so a demo visitor's "instant
terminate" logout stopped actually deleting their code server-side. The
route still returned {"success": true} and logged a normal audit entry,
so nothing about the response would have revealed the code was still
live — this test exists so that regression can't reappear silently again.
"""
import pytest
from starlette.requests import Request

import core.demo_code_session as demo_code_session
from routers.auth import logout

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


def _fake_request() -> Request:
    scope = {
        "type": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [(b"user-agent", b"pytest")],
    }
    return Request(scope)


async def test_logout_actually_deletes_the_demo_code_server_side():
    code = await demo_code_session.generate_code("Ellie", "3")
    assert await demo_code_session.code_exists(code) is True

    result = await logout(_fake_request(), auth={"role": "demo_code", "code": code})

    assert result == {"success": True}
    assert await demo_code_session.code_exists(code) is False


async def test_logout_is_a_no_op_for_non_demo_roles():
    """Parent/child tokens are stateless — logout must not try to touch
    the demo code store at all for them (no code in the auth payload)."""
    result = await logout(_fake_request(), auth={"role": "parent"})
    assert result == {"success": True}
