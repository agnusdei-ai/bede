"""
core/parent_credential.py — the DB-backed PARENT_PASSWORD override that
mirrors core/license_state.py's "DB value wins over env, live, no
restart" precedent, plus the credentials_version cache core/deps.py checks
on every parent/parent_pending request.
"""
import pytest
import pytest_asyncio

from core import parent_credential
from core.config import settings

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


@pytest_asyncio.fixture
async def db_session(demo_db):
    async with demo_db() as session:
        yield session


@pytest.fixture(autouse=True)
def _reset_cache():
    """Module-level cached version would otherwise leak between tests."""
    parent_credential._set_cached_version(0)
    yield
    parent_credential._set_cached_version(0)


async def test_no_override_falls_back_to_env_password(db_session):
    assert await parent_credential.verify_parent_password(db_session, settings.parent_password) is True
    assert await parent_credential.verify_parent_password(db_session, "wrong") is False


async def test_setting_an_override_makes_the_env_password_stop_working(db_session):
    await parent_credential.set_parent_password_override(db_session, "a-new-strong-password")
    assert await parent_credential.verify_parent_password(db_session, settings.parent_password) is False
    assert await parent_credential.verify_parent_password(db_session, "a-new-strong-password") is True


async def test_set_override_bumps_credentials_version(db_session):
    v1 = await parent_credential.set_parent_password_override(db_session, "first-password")
    v2 = await parent_credential.set_parent_password_override(db_session, "second-password")
    assert v2 == v1 + 1


async def test_set_override_updates_the_in_process_cache_immediately(db_session):
    assert parent_credential.current_credentials_version() == 0
    new_version = await parent_credential.set_parent_password_override(db_session, "a-password")
    assert parent_credential.current_credentials_version() == new_version


async def test_refresh_from_db_syncs_the_cache_to_an_existing_override(db_session):
    await parent_credential.set_parent_password_override(db_session, "a-password")
    parent_credential._set_cached_version(0)  # simulate a fresh process that hasn't synced yet
    await parent_credential.refresh_from_db(db_session)
    assert parent_credential.current_credentials_version() != 0


async def test_refresh_from_db_with_no_override_is_zero(db_session):
    await parent_credential.refresh_from_db(db_session)
    assert parent_credential.current_credentials_version() == 0


async def test_has_override_reflects_whether_a_password_was_ever_set(db_session):
    assert await parent_credential.has_override(db_session) is False
    await parent_credential.set_parent_password_override(db_session, "a-password")
    assert await parent_credential.has_override(db_session) is True
