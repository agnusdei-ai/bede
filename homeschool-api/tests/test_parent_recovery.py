"""
services/parent_recovery.py — the recovery code, one of the >=2 factors
routers/recovery.py's account-recovery flow requires.
"""
import pytest
import pytest_asyncio

from services import parent_recovery

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


@pytest_asyncio.fixture
async def db_session(demo_db):
    async with demo_db() as session:
        yield session


async def test_no_code_enrolled_by_default(db_session):
    assert await parent_recovery.has_recovery_code(db_session) is False
    assert await parent_recovery.verify_recovery_code(db_session, "ANYTHING") is False


async def test_enroll_returns_a_verifiable_code(db_session):
    code = await parent_recovery.enroll_recovery_code(db_session)
    assert await parent_recovery.has_recovery_code(db_session) is True
    assert await parent_recovery.verify_recovery_code(db_session, code) is True


async def test_enrolled_code_has_the_expected_shape():
    """Not DB-dependent — checks the generator directly via enroll's
    return value shape (4 groups of 5 from the safe alphabet, dash-joined)."""
    code = parent_recovery._generate_code()
    groups = code.split("-")
    assert len(groups) == 4
    assert all(len(g) == 5 for g in groups)
    assert all(c in parent_recovery._ALPHABET for g in groups for c in g)


async def test_wrong_code_is_rejected(db_session):
    await parent_recovery.enroll_recovery_code(db_session)
    assert await parent_recovery.verify_recovery_code(db_session, "WRONG-CODE-VALU-EHERE") is False


async def test_verify_is_case_insensitive_and_trims_whitespace(db_session):
    code = await parent_recovery.enroll_recovery_code(db_session)
    assert await parent_recovery.verify_recovery_code(db_session, f"  {code.lower()}  ") is True


async def test_re_enrolling_invalidates_the_previous_code(db_session):
    old_code = await parent_recovery.enroll_recovery_code(db_session)
    new_code = await parent_recovery.enroll_recovery_code(db_session)
    assert old_code != new_code
    assert await parent_recovery.verify_recovery_code(db_session, old_code) is False
    assert await parent_recovery.verify_recovery_code(db_session, new_code) is True


async def test_revoke_removes_the_code(db_session):
    code = await parent_recovery.enroll_recovery_code(db_session)
    assert await parent_recovery.revoke_recovery_code(db_session) is True
    assert await parent_recovery.has_recovery_code(db_session) is False
    assert await parent_recovery.verify_recovery_code(db_session, code) is False


async def test_revoke_with_nothing_enrolled_returns_false(db_session):
    assert await parent_recovery.revoke_recovery_code(db_session) is False


async def test_empty_submitted_code_never_verifies(db_session):
    await parent_recovery.enroll_recovery_code(db_session)
    assert await parent_recovery.verify_recovery_code(db_session, "") is False
