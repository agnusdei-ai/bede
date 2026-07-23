"""
routers/recovery.py — the public, unauthenticated "I've lost my password
and possibly my second factor" flow. Requires proving >=2 of {recovery
code, TOTP, WebAuthn} before issuing a narrow parent_recovery token, which
is itself only good for one thing: setting a new password.

WebAuthn itself isn't exercised here (it needs a real browser ceremony —
services/mfa_service.py's own webauthn functions are the unit under test
elsewhere, if ever); these tests cover the 2-of-3 counting logic using the
two factors that don't require a hardware key: recovery code + TOTP.
"""
import pyotp
import pytest
import pytest_asyncio
from fastapi import HTTPException
from starlette.requests import Request

from core import parent_credential
from core.deps import require_parent_recovery
from core.security import decode_token
from models.schemas import ChangePasswordRecoveryRequest, RecoveryVerifyRequest
from routers.recovery import recovery_methods, reset_password, verify
from services import mfa_service, parent_recovery

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


@pytest_asyncio.fixture
async def db_session(demo_db):
    async with demo_db() as session:
        yield session


@pytest.fixture(autouse=True)
def _reset_cache():
    parent_credential._set_cached_version(0)
    yield
    parent_credential._set_cached_version(0)


@pytest.fixture(autouse=True)
def _reset_totp_step():
    """core/mfa_challenge.py's TOTP anti-replay tracker is a single
    process-global int (correct for the real app — exactly one parent
    TOTP secret is ever active) — but this file enrolls a FRESH secret per
    test, and two tests landing in the same 30s wall-clock window would
    otherwise collide purely on timestep, unrelated to which secret each
    test actually used."""
    import core.mfa_challenge as mfa_challenge_module
    mfa_challenge_module._last_totp_step = None
    yield
    mfa_challenge_module._last_totp_step = None


def _fake_request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 12345), "headers": [(b"user-agent", b"pytest")]})


async def _enroll_totp(db_session) -> pyotp.TOTP:
    secret, _ = await mfa_service.enroll_totp(db_session)
    totp = pyotp.TOTP(secret)
    await mfa_service.confirm_totp(db_session, totp.now())
    return totp


# ── GET /auth/recovery/methods ───────────────────────────────────────────────

async def test_methods_reports_nothing_enrolled_by_default(db_session):
    result = await recovery_methods(db_session)
    assert result == {"recovery_code": False, "totp": False, "webauthn": False, "recovery_possible": False}


async def test_methods_reports_recovery_possible_once_two_are_enrolled(db_session):
    await parent_recovery.enroll_recovery_code(db_session)
    await _enroll_totp(db_session)
    result = await recovery_methods(db_session)
    assert result["recovery_code"] is True
    assert result["totp"] is True
    assert result["recovery_possible"] is True


async def test_methods_reports_not_possible_with_only_one_enrolled(db_session):
    await parent_recovery.enroll_recovery_code(db_session)
    result = await recovery_methods(db_session)
    assert result["recovery_possible"] is False


# ── POST /auth/recovery/verify ───────────────────────────────────────────────

async def test_verify_fails_with_only_one_correct_factor(db_session):
    code = await parent_recovery.enroll_recovery_code(db_session)
    await _enroll_totp(db_session)

    with pytest.raises(HTTPException) as exc_info:
        await verify(RecoveryVerifyRequest(recovery_code=code), _fake_request(), db_session)
    assert exc_info.value.status_code == 401


async def test_verify_succeeds_with_recovery_code_and_totp(db_session):
    code = await parent_recovery.enroll_recovery_code(db_session)
    totp = await _enroll_totp(db_session)

    result = await verify(
        RecoveryVerifyRequest(recovery_code=code, totp_code=totp.now()),
        _fake_request(), db_session,
    )
    payload = decode_token(result["recovery_token"])
    assert payload["role"] == "parent_recovery"


async def test_verify_fails_with_wrong_recovery_code_even_if_totp_is_correct(db_session):
    await parent_recovery.enroll_recovery_code(db_session)
    totp = await _enroll_totp(db_session)

    with pytest.raises(HTTPException) as exc_info:
        await verify(
            RecoveryVerifyRequest(recovery_code="WRONG-CODE-VALU-EHERE", totp_code=totp.now()),
            _fake_request(), db_session,
        )
    assert exc_info.value.status_code == 401


async def test_verify_with_no_factors_submitted_fails(db_session):
    await parent_recovery.enroll_recovery_code(db_session)
    await _enroll_totp(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await verify(RecoveryVerifyRequest(), _fake_request(), db_session)
    assert exc_info.value.status_code == 401


# ── POST /auth/recovery/reset-password ───────────────────────────────────────

async def test_reset_password_requires_a_recovery_token(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await require_parent_recovery(_fake_request(), credentials=_bearer_credentials(""))
    assert exc_info.value.status_code in (401, 403)


async def test_reset_password_sets_a_new_password_and_bumps_credentials_version(db_session):
    code = await parent_recovery.enroll_recovery_code(db_session)
    totp = await _enroll_totp(db_session)

    verify_result = await verify(
        RecoveryVerifyRequest(recovery_code=code, totp_code=totp.now()),
        _fake_request(), db_session,
    )
    recovery_payload = decode_token(verify_result["recovery_token"])

    v_before = parent_credential.current_credentials_version()
    result = await reset_password(
        ChangePasswordRecoveryRequest(new_password="a-brand-new-strong-password"),
        _fake_request(), db_session, recovery_payload,
    )
    assert result == {"success": True}
    assert parent_credential.current_credentials_version() == v_before + 1
    assert await parent_credential.verify_parent_password(db_session, "a-brand-new-strong-password") is True


async def test_reset_password_rejects_a_too_short_new_password(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await reset_password(
            ChangePasswordRecoveryRequest(new_password="short"),
            _fake_request(), db_session, {"role": "parent_recovery"},
        )
    assert exc_info.value.status_code == 400


def _bearer_credentials(token: str):
    from fastapi.security import HTTPAuthorizationCredentials
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
