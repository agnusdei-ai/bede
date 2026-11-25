"""Automatic public beta closure without affecting family authentication."""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from core import public_demo_beta as beta
from core import security
from core.security import _b64url_decode, create_access_token, decode_token
from models.schemas import LoginRequest
from routers import auth


def at(monkeypatch, instant):
    monkeypatch.setattr(beta, "utc_now", lambda: datetime.fromisoformat(instant))


@pytest.mark.parametrize("instant,closed", [
    ("2027-01-01T05:59:59.999999+00:00", False),
    ("2027-01-01T06:00:00+00:00", True),
    ("2027-01-02T06:00:00+00:00", True),
])
def test_central_midnight_boundary(monkeypatch, instant, closed):
    at(monkeypatch, instant)
    assert beta.public_demo_closed() is closed


def test_new_demo_jwt_never_outlives_beta():
    token = create_access_token({"role": "demo_code"}, expires_delta=timedelta(days=365))
    payload = json.loads(_b64url_decode(token.split(".")[1]))
    assert payload["exp"] == int(beta.PUBLIC_DEMO_CLOSES_AT.timestamp())


@pytest.mark.parametrize("role", ["parent", "child", "parent_pending", "educator", "demo_code"])
def test_existing_token_rejected_only_for_demo_at_cutoff(monkeypatch, role):
    # Includes a correctly signed pre-change JWT without the new expiry cap.
    # This models an existing session, not just a newly minted capped JWT.
    from core import identity
    import hashlib
    import hmac
    header = security._b64url_encode(json.dumps({
        "alg": "HS256", "typ": "JWT", "dom": identity.domain_for_role(role),
    }).encode())
    body = security._b64url_encode(json.dumps({"role": role, "exp": 9999999999}).encode())
    signature = security._b64url_encode(hmac.new(
        identity.signing_key(identity.domain_for_role(role)),
        f"{header}.{body}".encode(), hashlib.sha256,
    ).digest())
    token = f"{header}.{body}.{signature}"
    at(monkeypatch, "2027-01-01T05:59:59+00:00")
    assert decode_token(token) is not None
    at(monkeypatch, "2027-01-01T06:00:00+00:00")
    assert (decode_token(token) is None) is (role == "demo_code")


@pytest.mark.asyncio
async def test_after_cutoff_no_code_is_minted_or_redeemed(monkeypatch):
    at(monkeypatch, "2027-01-01T06:00:00+00:00")
    mint, redeem = AsyncMock(), AsyncMock()
    monkeypatch.setattr(auth, "generate_code", mint)
    monkeypatch.setattr(auth, "redeem_code", redeem)
    for operation in [
        auth.create_demo_code(),
        auth.login(
            LoginRequest(role="demo_code", credential="123456"),
            Request({"type": "http", "headers": []}), None,
        ),
    ]:
        with pytest.raises(HTTPException) as error:
            await operation
        assert error.value.status_code == 410
        assert "info@agnusdei.ai" in error.value.detail
    mint.assert_not_awaited()
    redeem.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_is_read_only_and_exposes_fixed_deadline(monkeypatch):
    at(monkeypatch, "2027-01-01T06:00:00+00:00")
    assert await auth.public_demo_status() == {
        "closed": True,
        "closes_at": "2027-01-01T06:00:00+00:00",
        "time_zone": "America/Chicago",
    }


@pytest.mark.asyncio
async def test_mint_still_works_before_cutoff(monkeypatch):
    at(monkeypatch, "2027-01-01T05:59:59+00:00")
    mint = AsyncMock(return_value="123456")
    monkeypatch.setattr(auth, "generate_code", mint)
    assert (await auth.create_demo_code()).code == "123456"
    mint.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_demo_bearer_is_refused_by_request_guard(monkeypatch):
    from fastapi.security import HTTPAuthorizationCredentials
    from core import deps

    token = create_access_token({"role": "demo_code", "code": "123456"})
    monkeypatch.setattr(deps, "demo_code_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(deps, "log_event", AsyncMock())
    request = Request({
        "type": "http", "headers": [],
        "client": ("127.0.0.1", 1234), "method": "GET", "path": "/tutor/config",
    })
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    at(monkeypatch, "2027-01-01T05:59:59+00:00")
    assert (await deps.require_auth(request, credentials))["role"] == "demo_code"
    at(monkeypatch, "2027-01-01T06:00:00+00:00")
    with pytest.raises(HTTPException) as error:
        await deps.require_auth(request, credentials)
    assert error.value.status_code == 401


def test_http_status_and_mint_exchange_at_cutoff(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.database import get_db

    app = FastAPI()
    app.include_router(auth.router)
    async def no_database():
        yield None
    app.dependency_overrides[get_db] = no_database
    mint, redeem = AsyncMock(), AsyncMock()
    monkeypatch.setattr(auth, "generate_code", mint)
    monkeypatch.setattr(auth, "redeem_code", redeem)
    at(monkeypatch, "2027-01-01T06:00:00+00:00")
    with TestClient(app) as client:
        status = client.get("/auth/demo-status")
        assert status.status_code == 200
        assert status.json()["closed"] is True
        assert client.post("/auth/demo-code").status_code == 410
        assert client.post("/auth/login", json={
            "role": "demo_code", "credential": "123456",
        }).status_code == 410
    mint.assert_not_awaited()
    redeem.assert_not_awaited()
