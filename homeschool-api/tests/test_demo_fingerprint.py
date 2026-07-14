"""
Real bug this fixes: a demo visitor's device fingerprint (SHA-256 of
IP + User-Agent, bound into the JWT at /auth/login) is checked with an
exact-hash comparison and zero tolerance (core/security.py's
validate_fingerprint). On mobile, a visitor's public IP legitimately
changes mid-session far more often than a real family's home network
does — a WiFi<->cellular handoff, a carrier's CGNAT pool rotating —
and the very next authenticated request (often the one a subject switch
fires, see demo/src/App.tsx's per-subject [START] effect) then 401'd
with "Session cannot be used from a different device," which the demo
frontend treats as TrialSessionEndedError and boots the visitor back to
the code-entry screen even though they never left their own device.

routers/auth.py now skips fingerprint binding specifically for
demo_code tokens (parent/child unchanged) — relying on
validate_fingerprint's own pre-existing "no fp claim -> allow" branch,
not a new bypass. The demo's real replay defense is unaffected: a code
can only ever be redeemed once (core/demo_code_session.py's
redeem_code), tokens still expire after 2 hours
(settings.demo_code_token_expire_minutes), and the diagnostic preview
specifically stays IP-quota-capped (core/diagnostic_preview_quota.py).
"""
import pytest
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from core.deps import _validate_token, require_auth
from core.security import create_access_token, decode_token
from models.schemas import LoginRequest
from routers.auth import create_demo_code, login

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


def _fake_request(ip: str = "203.0.113.1", ua: str = "pytest-agent/1") -> Request:
    scope = {
        "type": "http",
        "client": (ip, 12345),
        "headers": [(b"user-agent", ua.encode())],
    }
    return Request(scope)


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


async def _demo_login(ip: str, ua: str, db=None):
    code_resp = await create_demo_code()
    result = await login(
        LoginRequest(role="demo_code", credential=code_resp.code),
        _fake_request(ip, ua),
        db=db,
    )
    return result.access_token


async def test_demo_code_login_does_not_bind_a_fingerprint():
    token = await _demo_login("203.0.113.1", "iPhone Safari 18")
    payload = decode_token(token)
    assert "fp" not in payload


async def test_demo_code_token_survives_a_different_ip_on_the_next_request():
    """The exact scenario from the bug report: login on WiFi, then the
    next request (e.g. a subject switch) arrives from a different IP
    after a WiFi<->cellular handoff. Must NOT 401."""
    token = await _demo_login("203.0.113.1", "Mozilla/5.0 (iPhone) Safari")

    # A later request from a materially different IP (simulating a
    # carrier network handoff) and even a slightly different UA string.
    later_request = _fake_request("198.51.100.77", "Mozilla/5.0 (iPhone) Safari")
    payload = await require_auth(later_request, _bearer(token))

    assert payload["role"] == "demo_code"


async def test_demo_code_token_still_rejects_a_tampered_or_garbage_bearer_token():
    """Dropping the fingerprint must not turn this into 'any string is a
    valid session' — signature/expiry validation is untouched."""
    with pytest.raises(Exception):
        await require_auth(_fake_request(), _bearer("not.a.real.token"))


async def test_parent_role_fingerprint_binding_is_unchanged():
    """Regression guard: this fix must be scoped to demo_code only. A
    manually-issued parent token, bound the same way create_access_token
    always has, must still reject a request from a different device."""
    from core.middleware import compute_fingerprint

    login_request = _fake_request("203.0.113.1", "Desktop Chrome")
    fp = compute_fingerprint(login_request.client.host, "Desktop Chrome")
    token = create_access_token({"sub": "parent", "role": "parent"}, fingerprint=fp)

    # Same device — still fine.
    payload = await _validate_token(login_request, _bearer(token))
    assert payload["role"] == "parent"

    # A different device entirely — still rejected, exactly as before.
    with pytest.raises(Exception):
        await _validate_token(_fake_request("198.51.100.77", "Different Browser"), _bearer(token))
