"""
routers/auth.py's login() — the wiring added for account lockout,
password-override precedence, and credentials_version (cv) claim
embedding. See core/parent_lockout.py, core/parent_credential.py.

Called directly (not through a full TestClient), same pattern as
tests/test_auth_logout.py and tests/test_moderation_router.py.
"""
import pytest
import pytest_asyncio
from fastapi import HTTPException
from starlette.requests import Request

from core import parent_credential, parent_lockout
from core.config import settings
from core.security import decode_token
from routers.auth import login
from models.schemas import LoginRequest

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


async def test_correct_password_succeeds_and_embeds_cv(db_session):
    resp = await login(LoginRequest(role="parent", credential=settings.parent_password), _fake_request(), db_session)
    assert resp.role == "parent"
    payload = decode_token(resp.access_token)
    assert payload["cv"] == 0  # no override ever set — cache starts at 0


async def test_wrong_password_rejected_and_does_not_lock_out_immediately(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await login(LoginRequest(role="parent", credential="wrong"), _fake_request(), db_session)
    assert exc_info.value.status_code == 401
    assert await parent_lockout.check_locked(db_session) is None


async def test_repeated_failures_lock_out_the_parent_role(db_session):
    for _ in range(parent_lockout.FAILURE_THRESHOLD):
        with pytest.raises(HTTPException):
            await login(LoginRequest(role="parent", credential="wrong"), _fake_request(), db_session)

    with pytest.raises(HTTPException) as exc_info:
        await login(LoginRequest(role="parent", credential=settings.parent_password), _fake_request(), db_session)
    assert exc_info.value.status_code == 429


async def test_successful_login_clears_prior_failures(db_session):
    for _ in range(parent_lockout.FAILURE_THRESHOLD - 1):
        with pytest.raises(HTTPException):
            await login(LoginRequest(role="parent", credential="wrong"), _fake_request(), db_session)

    resp = await login(LoginRequest(role="parent", credential=settings.parent_password), _fake_request(), db_session)
    assert resp.role == "parent"

    # Locked-out threshold now needs a fresh full count, not just 1 more.
    for _ in range(parent_lockout.FAILURE_THRESHOLD - 1):
        with pytest.raises(HTTPException) as exc_info:
            await login(LoginRequest(role="parent", credential="wrong"), _fake_request(), db_session)
        assert exc_info.value.status_code == 401  # not yet 429


async def test_password_override_wins_over_env_at_login(db_session):
    await parent_credential.set_parent_password_override(db_session, "a-new-strong-password")

    with pytest.raises(HTTPException) as exc_info:
        await login(LoginRequest(role="parent", credential=settings.parent_password), _fake_request(), db_session)
    assert exc_info.value.status_code == 401

    resp = await login(LoginRequest(role="parent", credential="a-new-strong-password"), _fake_request(), db_session)
    assert resp.role == "parent"


async def test_child_and_demo_roles_are_unaffected_by_parent_lockout(db_session):
    """Lockout is role-scoped to parent only — repeated parent failures
    must never block a child login."""
    for _ in range(parent_lockout.FAILURE_THRESHOLD):
        with pytest.raises(HTTPException):
            await login(LoginRequest(role="parent", credential="wrong"), _fake_request(), db_session)

    resp = await login(LoginRequest(role="child", credential=settings.child_pin), _fake_request(), db_session)
    assert resp.role == "child"
    payload = decode_token(resp.access_token)
    assert "cv" not in payload  # only parent/parent_pending tokens ever carry cv
