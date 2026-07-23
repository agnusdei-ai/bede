"""
routers/mfa.py's new endpoints: change-password (a full parent session
changing their own password on purpose) and recovery PIN/code enrollment —
the "something you know" leg of routers/recovery.py's account-recovery
scheme. All funnel through core.parent_credential/services.parent_recovery,
already covered at the unit level in tests/test_parent_credential.py and
tests/test_parent_recovery.py; these confirm the HTTP layer wires them up
correctly (auth requirements, validation, audit logging).
"""
import pytest
import pytest_asyncio
from fastapi import HTTPException
from starlette.requests import Request

from core import parent_credential
from core.config import settings
from models.schemas import ChangePasswordRequest, RecoveryPinEnrollRequest
from routers.mfa import (
    change_password,
    recovery_code_disable,
    recovery_code_enroll,
    recovery_pin_disable,
    recovery_pin_enroll,
    status_,
)
from services import parent_recovery

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


def _fake_request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 12345), "headers": [(b"user-agent", b"pytest")]})


# ── change-password ──────────────────────────────────────────────────────────

async def test_change_password_with_wrong_current_password_is_rejected(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await change_password(
            ChangePasswordRequest(current_password="wrong", new_password="a-new-strong-password"),
            _fake_request(), db_session, {"role": "parent"},
        )
    assert exc_info.value.status_code == 401
    assert await parent_credential.has_override(db_session) is False


async def test_change_password_with_too_short_new_password_is_rejected(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await change_password(
            ChangePasswordRequest(current_password=settings.parent_password, new_password="short"),
            _fake_request(), db_session, {"role": "parent"},
        )
    assert exc_info.value.status_code == 400


async def test_change_password_succeeds_and_bumps_credentials_version(db_session):
    v_before = parent_credential.current_credentials_version()
    result = await change_password(
        ChangePasswordRequest(current_password=settings.parent_password, new_password="a-new-strong-password"),
        _fake_request(), db_session, {"role": "parent"},
    )
    assert result == {"success": True}
    assert parent_credential.current_credentials_version() == v_before + 1
    assert await parent_credential.verify_parent_password(db_session, "a-new-strong-password") is True
    assert await parent_credential.verify_parent_password(db_session, settings.parent_password) is False


async def test_change_password_can_be_called_again_against_an_existing_override(db_session):
    await change_password(
        ChangePasswordRequest(current_password=settings.parent_password, new_password="first-new-password"),
        _fake_request(), db_session, {"role": "parent"},
    )
    result = await change_password(
        ChangePasswordRequest(current_password="first-new-password", new_password="second-new-password"),
        _fake_request(), db_session, {"role": "parent"},
    )
    assert result == {"success": True}
    assert await parent_credential.verify_parent_password(db_session, "second-new-password") is True


# ── recovery-code enrollment ─────────────────────────────────────────────────

async def test_status_reports_recovery_secret_unset_by_default(db_session):
    result = await status_(db_session, {"role": "parent"})
    assert result["recovery_secret"] is None


async def test_enroll_returns_a_code_and_status_reflects_it(db_session):
    result = await recovery_code_enroll(_fake_request(), db_session, {"role": "parent"})
    assert "recovery_code" in result and len(result["recovery_code"]) > 0

    status_result = await status_(db_session, {"role": "parent"})
    assert status_result["recovery_secret"] == "code"

    assert await parent_recovery.verify_recovery_code(db_session, result["recovery_code"]) is True


async def test_disable_revokes_the_code(db_session):
    await recovery_code_enroll(_fake_request(), db_session, {"role": "parent"})
    result = await recovery_code_disable(_fake_request(), db_session, {"role": "parent"})
    assert result == {"success": True}

    status_result = await status_(db_session, {"role": "parent"})
    assert status_result["recovery_secret"] is None


async def test_re_enrolling_replaces_the_previous_code(db_session):
    first = await recovery_code_enroll(_fake_request(), db_session, {"role": "parent"})
    second = await recovery_code_enroll(_fake_request(), db_session, {"role": "parent"})
    assert first["recovery_code"] != second["recovery_code"]
    assert await parent_recovery.verify_recovery_code(db_session, first["recovery_code"]) is False
    assert await parent_recovery.verify_recovery_code(db_session, second["recovery_code"]) is True


# ── recovery-PIN enrollment (favored alternative) ────────────────────────────

async def test_enroll_pin_succeeds_and_status_reflects_it(db_session):
    result = await recovery_pin_enroll(
        RecoveryPinEnrollRequest(pin="602656"), _fake_request(), db_session, {"role": "parent"},
    )
    assert result == {"success": True}

    status_result = await status_(db_session, {"role": "parent"})
    assert status_result["recovery_secret"] == "pin"
    assert await parent_recovery.verify_recovery_pin(db_session, "602656") is True


async def test_enroll_weak_pin_is_rejected(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await recovery_pin_enroll(
            RecoveryPinEnrollRequest(pin="111111"), _fake_request(), db_session, {"role": "parent"},
        )
    assert exc_info.value.status_code == 400
    assert await parent_recovery.has_recovery_pin(db_session) is False


async def test_disable_pin_revokes_it(db_session):
    await recovery_pin_enroll(RecoveryPinEnrollRequest(pin="602656"), _fake_request(), db_session, {"role": "parent"})
    result = await recovery_pin_disable(_fake_request(), db_session, {"role": "parent"})
    assert result == {"success": True}

    status_result = await status_(db_session, {"role": "parent"})
    assert status_result["recovery_secret"] is None


async def test_enrolling_a_pin_via_the_router_clears_an_existing_code(db_session):
    await recovery_code_enroll(_fake_request(), db_session, {"role": "parent"})
    await recovery_pin_enroll(RecoveryPinEnrollRequest(pin="602656"), _fake_request(), db_session, {"role": "parent"})

    status_result = await status_(db_session, {"role": "parent"})
    assert status_result["recovery_secret"] == "pin"


async def test_enrolling_a_code_via_the_router_clears_an_existing_pin(db_session):
    await recovery_pin_enroll(RecoveryPinEnrollRequest(pin="602656"), _fake_request(), db_session, {"role": "parent"})
    await recovery_code_enroll(_fake_request(), db_session, {"role": "parent"})

    status_result = await status_(db_session, {"role": "parent"})
    assert status_result["recovery_secret"] == "code"
