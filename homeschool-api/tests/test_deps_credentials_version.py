"""
core/deps.py's credentials_version ('cv') check — the mechanism that makes
changing a parent's password actually END every other outstanding
session, including a stolen token an attacker might be holding, rather
than just adding a new valid session alongside it. See
core/parent_credential.py, docs/SECURITY.md's "Closed gaps".
"""
import pytest
import pytest_asyncio
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from core import parent_credential
from core.deps import require_auth
from core.middleware import compute_fingerprint
from core.security import create_access_token

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


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _parent_token(cv: int | None) -> str:
    fp = compute_fingerprint("127.0.0.1", "pytest")
    payload = {"sub": "parent", "role": "parent"}
    if cv is not None:
        payload["cv"] = cv
    return create_access_token(payload, fingerprint=fp)


async def test_token_with_current_cv_is_accepted(db_session):
    token = _parent_token(cv=0)  # cache starts at 0 in a fresh process/test
    payload = await require_auth(_fake_request(), _bearer(token))
    assert payload["role"] == "parent"


async def test_token_becomes_invalid_after_a_password_change(db_session):
    token = _parent_token(cv=0)
    await require_auth(_fake_request(), _bearer(token))  # valid before the change

    await parent_credential.set_parent_password_override(db_session, "a-new-strong-password")

    with pytest.raises(HTTPException) as exc_info:
        await require_auth(_fake_request(), _bearer(token))
    assert exc_info.value.status_code == 401


async def test_a_freshly_issued_token_after_the_change_works(db_session):
    await parent_credential.set_parent_password_override(db_session, "a-new-strong-password")
    new_token = _parent_token(cv=parent_credential.current_credentials_version())
    payload = await require_auth(_fake_request(), _bearer(new_token))
    assert payload["role"] == "parent"


async def test_child_tokens_are_never_subject_to_the_cv_check(db_session):
    """Only parent/parent_pending tokens carry 'cv' at all — a child token
    (which never has the claim) must be completely unaffected by a parent
    password change."""
    fp = compute_fingerprint("127.0.0.1", "pytest")
    child_token = create_access_token({"sub": "child", "role": "child"}, fingerprint=fp)

    await parent_credential.set_parent_password_override(db_session, "a-new-strong-password")

    payload = await require_auth(_fake_request(), _bearer(child_token))
    assert payload["role"] == "child"


async def test_a_token_issued_before_any_override_ever_existed_still_works(db_session):
    """cv=0 (the pre-override default) must remain valid until the FIRST
    password change — a deployment that's never used the in-app password
    change/recovery feature at all must see zero behavior change."""
    token = _parent_token(cv=0)
    payload = await require_auth(_fake_request(), _bearer(token))
    assert payload["role"] == "parent"
