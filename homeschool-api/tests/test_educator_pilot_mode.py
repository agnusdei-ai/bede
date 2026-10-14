"""No shared child-PIN authentication on the opted-in academic pilot host.

Tests are purely local JWTs and fake ASGI request context; no account
probing, external services, or real credentials.
"""
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from core.config import settings
from core.deps import _require_live_session, _validate_token
from core.security import create_access_token


def request():
    return Request({
        "type": "http", "method": "GET", "path": "/test",
        "headers": [(b"user-agent", b"synthetic-bede-test")],
        "client": ("127.0.0.1", 12000), "scheme": "https",
    })


@pytest.mark.asyncio
async def test_classroom_mode_blocks_existing_shared_pin_child_jwt(monkeypatch):
    monkeypatch.setattr(settings, "educator_pilot_enabled", True)
    token = create_access_token({"role": "child", "sub": "child"})
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(HTTPException) as exc:
        await _validate_token(request(), credentials)
    assert exc.value.status_code == 403
    assert "educator" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_household_child_login_unchanged_in_normal_mode(monkeypatch):
    monkeypatch.setattr(settings, "educator_pilot_enabled", False)
    token = create_access_token({"role": "child", "sub": "child"})
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    auth = await _validate_token(request(), credentials)
    assert auth["role"] == "child"


@pytest.mark.asyncio
async def test_teacher_session_rejected_when_pilot_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "educator_pilot_enabled", False)
    with pytest.raises(HTTPException) as exc:
        await _require_live_session(
            request(), {"role": "educator", "sub": "synthetic", "ev": 1},
        )
    assert exc.value.status_code == 403
