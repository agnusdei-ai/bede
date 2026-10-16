"""Synthetic identity-boundary checks for institutional pilot.

A campus SSO/LDAP identity must never become a Bede recovery administrator.
These are direct route authorization tests, not a hardware WebAuthn E2E claim.
"""
import pytest
from fastapi import HTTPException

from routers.educator_passkeys import (
    _require_strong_admin, recover_educator, invite_educator,
    RecoveryRequest, InviteRequest,
)


@pytest.mark.parametrize("principal", [
    {"role": "educator", "auth_method": "webauthn_uv", "sub": "synthetic"},
    {"role": "parent", "auth_method": "oidc", "sub": "campus-directory"},
    {"role": "parent", "auth_method": "saml", "sub": "campus-directory"},
    {"role": "parent", "auth_method": "ldap", "sub": "campus-directory"},
    {"role": "parent", "auth_method": "password", "sub": "campus-directory"},
    {"role": "parent", "auth_method": "email_otp", "sub": "campus-directory"},
    {"role": "parent", "auth_method": "webauthn", "sub": "campus-directory"},
    {"role": "admin", "auth_method": "webauthn_uv", "sub": "campus-directory"},
    {"role": "parent"},
    {},
])
def test_campus_directory_cannot_assume_bede_recovery_admin(principal):
    with pytest.raises(HTTPException) as exc:
        _require_strong_admin(principal)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_directory_identity_cannot_initiate_lost_device_recovery(monkeypatch):
    from routers import educator_passkeys as routes
    monkeypatch.setattr(routes.settings, "educator_pilot_enabled", True)
    monkeypatch.setattr(routes.settings, "demo_pin", "")  # is_demo_deployment is derived from demo_pin
    # No database required: authorization must reject before any DB access.
    with pytest.raises(HTTPException) as exc:
        await recover_educator(
            "00000000-0000-4000-8000-000000000001",
            RecoveryRequest(institutional_email="teacher@example.edu"),
            admin={"role": "parent", "auth_method": "oidc", "sub": "directory"},
            db=None,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_directory_identity_cannot_invite_teacher(monkeypatch):
    from routers import educator_passkeys as routes
    monkeypatch.setattr(routes.settings, "educator_pilot_enabled", True)
    monkeypatch.setattr(routes.settings, "demo_pin", "")  # is_demo_deployment is derived from demo_pin
    with pytest.raises(HTTPException) as exc:
        await invite_educator(
            InviteRequest(username="synthetic.teacher", institutional_email="teacher@example.edu"),
            admin={"role": "parent", "auth_method": "saml", "sub": "directory"},
            db=None,
        )
    assert exc.value.status_code == 403
