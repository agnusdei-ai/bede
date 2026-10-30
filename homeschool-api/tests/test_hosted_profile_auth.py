"""
COPPA readiness, controls C-22 and C-23 (docs/COPPA_READINESS_CHECKLIST.md).

Two controls behind one deployment flag, `HOSTED_PROFILE` (core/config.py),
default off so a self-hosted household's sign-in is byte-for-byte unchanged:

  C-22  A parent password alone does not open a session on a hosted
        deployment when no second factor is enrolled. Login refuses, and
        hands back a short-lived enrollment-only token so the parent can
        still reach the MFA enrollment routes (a refusal with no way to
        comply would strand the family).

  C-23  A child's correct PIN is not enough from an unpaired device. A
        device is paired when a parent approves it; the device then receives
        a per-device token exactly once, at its next sign-in, and presents
        that token on every later sign-in. Only a SHA-256 of the token is
        stored.

Every guard here was verified by breaking it (see the PR description).
"""
import hashlib

import pytest
import pytest_asyncio
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from core.config import settings
from core.database import Base, ChildDevicePairing
from core.security import decode_token, validate_fingerprint
from models.schemas import LoginRequest
from routers.auth import (
    approve_child_device,
    list_child_devices,
    login,
    revoke_child_device,
)
from routers.mfa import require_enrollment_or_elevated_parent


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        from core.encryption import initialize_encryption
        await initialize_encryption(settings.master_secret, session)
        yield session
    await engine.dispose()


def _request(user_agent: bytes = b"pytest") -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 12345), "headers": [(b"user-agent", user_agent)]})


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setattr(settings, "hosted_profile", True)
    return settings


@pytest.fixture
def self_hosted(monkeypatch):
    monkeypatch.setattr(settings, "hosted_profile", False)
    return settings


# ── C-22: parent MFA required on a hosted deployment ────────────────────────

@pytest.mark.asyncio
async def test_self_hosted_password_only_login_is_unchanged(db_session, self_hosted):
    """Default posture: no second factor enrolled, password alone gets a
    full parent session, exactly as before this control existed."""
    resp = await login(LoginRequest(role="parent", credential=settings.parent_password), _request(), db_session)
    assert resp.role == "parent"
    assert resp.mfa_required is False


@pytest.mark.asyncio
async def test_hosted_password_only_login_is_refused_with_a_clear_message(db_session, hosted):
    with pytest.raises(HTTPException) as exc_info:
        await login(LoginRequest(role="parent", credential=settings.parent_password), _request(), db_session)
    assert exc_info.value.status_code == 403
    detail = exc_info.value.detail
    assert detail["code"] == "mfa_enrollment_required"
    assert "second" in detail["message"].lower()


@pytest.mark.asyncio
async def test_hosted_refusal_hands_back_only_an_enrollment_token(db_session, hosted):
    with pytest.raises(HTTPException) as exc_info:
        await login(LoginRequest(role="parent", credential=settings.parent_password), _request(), db_session)
    detail = exc_info.value.detail
    assert set(detail) == {"code", "message", "enrollment_token"}
    payload = decode_token(detail["enrollment_token"])
    assert payload["role"] == "parent_pending"
    assert payload["enroll"] is True


@pytest.mark.asyncio
async def test_wrong_password_on_hosted_still_gets_the_plain_refusal(db_session, hosted):
    """A wrong password must not reveal whether MFA is enrolled."""
    with pytest.raises(HTTPException) as exc_info:
        await login(LoginRequest(role="parent", credential="not-the-password"), _request(), db_session)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid credentials"


@pytest.mark.asyncio
async def test_enrollment_token_reaches_enrollment_but_not_parent_data(db_session, hosted):
    with pytest.raises(HTTPException) as exc_info:
        await login(LoginRequest(role="parent", credential=settings.parent_password), _request(), db_session)
    token = exc_info.value.detail["enrollment_token"]
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    # The enrollment gate accepts it...
    payload = await require_enrollment_or_elevated_parent(_request(), creds, db_session)
    assert payload["role"] == "parent_pending"

    # ...but an ordinary parent-data guard does not.
    from core.deps import require_parent
    with pytest.raises(HTTPException):
        await require_parent(_request(), creds)


@pytest.mark.asyncio
async def test_enrollment_token_stops_working_for_enrollment_once_a_factor_exists(db_session, hosted, monkeypatch):
    with pytest.raises(HTTPException) as exc_info:
        await login(LoginRequest(role="parent", credential=settings.parent_password), _request(), db_session)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=exc_info.value.detail["enrollment_token"])

    from services import mfa_service

    async def _enrolled(_db):
        return ["totp"]

    monkeypatch.setattr(mfa_service, "enrolled_methods", _enrolled)
    with pytest.raises(HTTPException) as refused:
        await require_enrollment_or_elevated_parent(_request(), creds, db_session)
    assert refused.value.status_code in (401, 403)


@pytest.mark.asyncio
async def test_an_ordinary_mfa_pending_token_cannot_enroll_a_factor(db_session, hosted, monkeypatch):
    """The enrollment route accepts only the enroll-claimed token. A
    parent_pending token from a normal password-then-second-factor login
    (no enroll claim) must not be able to enroll anything."""
    from services import mfa_service

    async def _enrolled(_db):
        return ["totp"]

    monkeypatch.setattr(mfa_service, "enrolled_methods", _enrolled)
    resp = await login(LoginRequest(role="parent", credential=settings.parent_password), _request(), db_session)
    assert resp.role == "parent_pending"
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=resp.access_token)

    # Pretend no factor is enrolled, so the only thing left to refuse this
    # token is the missing enroll claim.
    monkeypatch.setattr(mfa_service, "enrolled_methods", lambda _db: _no_methods())
    with pytest.raises(HTTPException):
        await require_enrollment_or_elevated_parent(_request(), creds, db_session)


async def _no_methods():
    return []


@pytest.mark.asyncio
async def test_hosted_login_with_a_factor_enrolled_still_takes_the_mfa_path(db_session, hosted, monkeypatch):
    from services import mfa_service

    async def _enrolled(_db):
        return ["totp"]

    monkeypatch.setattr(mfa_service, "enrolled_methods", _enrolled)
    resp = await login(LoginRequest(role="parent", credential=settings.parent_password), _request(), db_session)
    assert resp.role == "parent_pending"
    assert resp.mfa_required is True


# ── C-23: child device pairing ──────────────────────────────────────────────

def _child(device_id=None, device_token=None, pin=None):
    return LoginRequest(
        role="child",
        credential=pin if pin is not None else settings.child_pin,
        device_id=device_id,
        device_token=device_token,
    )


@pytest.mark.asyncio
async def test_self_hosted_child_login_needs_no_pairing(db_session, self_hosted):
    resp = await login(_child(device_id="tablet-x"), _request(), db_session)
    assert resp.role == "child"
    assert resp.device_token is None


@pytest.mark.asyncio
async def test_hosted_child_login_without_a_device_id_is_refused(db_session, hosted):
    with pytest.raises(HTTPException) as exc_info:
        await login(_child(), _request(), db_session)
    assert exc_info.value.status_code == 403
    assert "device" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_correct_pin_from_an_unpaired_device_is_refused_and_recorded_pending(db_session, hosted):
    with pytest.raises(HTTPException) as exc_info:
        await login(_child(device_id="tablet-new"), _request(), db_session)
    assert exc_info.value.status_code == 403
    assert "approval" in exc_info.value.detail.lower()

    row = await db_session.get(ChildDevicePairing, "tablet-new")
    assert row is not None
    assert row.state == "pending"
    assert row.token_hash is None


@pytest.mark.asyncio
async def test_wrong_pin_from_an_unpaired_device_creates_no_pairing_row(db_session, hosted):
    """A caller without the PIN must not be able to fill the pending list."""
    with pytest.raises(HTTPException) as exc_info:
        await login(_child(device_id="tablet-guess", pin="9999"), _request(), db_session)
    assert exc_info.value.status_code == 401
    assert await db_session.get(ChildDevicePairing, "tablet-guess") is None


@pytest.mark.asyncio
async def test_pending_device_cannot_sign_in_until_a_parent_approves(db_session, hosted):
    with pytest.raises(HTTPException):
        await login(_child(device_id="tablet-p"), _request(), db_session)
    with pytest.raises(HTTPException) as exc_info:
        await login(_child(device_id="tablet-p"), _request(), db_session)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_approved_device_receives_its_token_exactly_once(db_session, hosted):
    with pytest.raises(HTTPException):
        await login(_child(device_id="tablet-a"), _request(), db_session)
    await approve_child_device("tablet-a", _request(), db_session, {"role": "parent"})

    resp = await login(_child(device_id="tablet-a"), _request(), db_session)
    assert resp.role == "child"
    assert resp.device_token
    assert decode_token(resp.access_token)["device_id"] == "tablet-a"

    row = await db_session.get(ChildDevicePairing, "tablet-a")
    assert row.state == "paired"
    # Only a digest is stored, never the token itself.
    assert row.token_hash == hashlib.sha256(resp.device_token.encode()).hexdigest()
    assert resp.device_token not in row.token_hash


@pytest.mark.asyncio
async def test_paired_device_needs_its_token_on_every_later_sign_in(db_session, hosted):
    with pytest.raises(HTTPException):
        await login(_child(device_id="tablet-b"), _request(), db_session)
    await approve_child_device("tablet-b", _request(), db_session, {"role": "parent"})
    first = await login(_child(device_id="tablet-b"), _request(), db_session)

    with pytest.raises(HTTPException) as no_token:
        await login(_child(device_id="tablet-b"), _request(), db_session)
    assert no_token.value.status_code == 403

    with pytest.raises(HTTPException) as wrong_token:
        await login(_child(device_id="tablet-b", device_token="not-the-token"), _request(), db_session)
    assert wrong_token.value.status_code == 403

    again = await login(_child(device_id="tablet-b", device_token=first.device_token), _request(), db_session)
    assert again.role == "child"
    assert again.device_token is None  # never re-issued, never re-shown


@pytest.mark.asyncio
async def test_a_known_token_with_the_wrong_pin_is_still_refused(db_session, hosted):
    """The pairing token is a second factor on top of the PIN, not a
    replacement for it."""
    with pytest.raises(HTTPException):
        await login(_child(device_id="tablet-c"), _request(), db_session)
    await approve_child_device("tablet-c", _request(), db_session, {"role": "parent"})
    first = await login(_child(device_id="tablet-c"), _request(), db_session)

    with pytest.raises(HTTPException) as exc_info:
        await login(_child(device_id="tablet-c", device_token=first.device_token, pin="9999"), _request(), db_session)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_revoked_device_is_refused_even_with_its_token(db_session, hosted):
    with pytest.raises(HTTPException):
        await login(_child(device_id="tablet-d"), _request(), db_session)
    await approve_child_device("tablet-d", _request(), db_session, {"role": "parent"})
    first = await login(_child(device_id="tablet-d"), _request(), db_session)

    await revoke_child_device("tablet-d", _request(), db_session, {"role": "parent"})
    with pytest.raises(HTTPException) as exc_info:
        await login(_child(device_id="tablet-d", device_token=first.device_token), _request(), db_session)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_approve_only_moves_a_pending_device(db_session, hosted):
    with pytest.raises(HTTPException):
        await login(_child(device_id="tablet-e"), _request(), db_session)
    await approve_child_device("tablet-e", _request(), db_session, {"role": "parent"})
    with pytest.raises(HTTPException) as exc_info:
        await approve_child_device("tablet-e", _request(), db_session, {"role": "parent"})
    assert exc_info.value.status_code == 409

    with pytest.raises(HTTPException) as unknown:
        await approve_child_device("never-seen", _request(), db_session, {"role": "parent"})
    assert unknown.value.status_code == 404


@pytest.mark.asyncio
async def test_device_listing_never_exposes_a_token_digest(db_session, hosted):
    with pytest.raises(HTTPException):
        await login(_child(device_id="tablet-f", ), _request(b"Mozilla/5.0 tablet"), db_session)
    listing = await list_child_devices(db_session, {"role": "parent"})
    entry = next(d for d in listing["devices"] if d["device_id"] == "tablet-f")
    assert entry["state"] == "pending"
    assert entry["user_agent"] == "Mozilla/5.0 tablet"
    assert "token_hash" not in entry


@pytest.mark.asyncio
async def test_existing_fingerprint_binding_still_applies_to_a_paired_token(db_session, hosted):
    """C-23 must not weaken the JWT device fingerprint (core/security.py):
    a paired child's token still fails from a different user agent."""
    with pytest.raises(HTTPException):
        await login(_child(device_id="tablet-g"), _request(b"agent-one"), db_session)
    await approve_child_device("tablet-g", _request(b"agent-one"), db_session, {"role": "parent"})
    resp = await login(_child(device_id="tablet-g"), _request(b"agent-one"), db_session)

    payload = decode_token(resp.access_token)
    assert payload.get("fp")
    from core.middleware import compute_fingerprint
    assert validate_fingerprint(payload, compute_fingerprint("127.0.0.1", "agent-one"))
    assert not validate_fingerprint(payload, compute_fingerprint("127.0.0.1", "some-other-browser"))
