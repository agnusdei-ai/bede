"""
Router-level tests for the usage fields on GET /admin/status and the new
GET /admin/usage/{student_name} — see core/api_usage.py. Real in-memory
SQLite via the demo_db fixture (tests/conftest.py), which also
monkeypatches core.database.AsyncSessionLocal so record_usage's
self-contained writes land in the same isolated engine these tests read
from. Called directly (same pattern as tests/test_diagnostic_router.py)
rather than through a full TestClient, since require_parent's own
JWT/fingerprint plumbing isn't what's under test here.
"""

import pytest
import pytest_asyncio

from core.api_usage import record_usage
from routers.admin import student_usage, system_status

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


@pytest_asyncio.fixture
async def db_session(demo_db):
    async with demo_db() as session:
        yield session


async def test_system_status_includes_a_zeroed_usage_summary_with_nothing_recorded(db_session):
    status = await system_status(db=db_session, _={"role": "parent"})
    assert status["usage"]["total_input_tokens"] == 0
    assert status["usage"]["estimated_cost_usd"] == 0


async def test_system_status_usage_reflects_recorded_calls_across_all_students(db_session):
    await record_usage("Emma", "claude-sonnet-4-6", input_tokens=1000, output_tokens=100)
    await record_usage("Liam", "claude-sonnet-4-6", input_tokens=2000, output_tokens=200)

    status = await system_status(db=db_session, _={"role": "parent"})
    assert status["usage"]["total_input_tokens"] == 3000
    assert status["usage"]["total_calls"] == 2


async def test_student_usage_endpoint_returns_zeroed_summary_before_any_calls(db_session):
    summary = await student_usage("Nobody", db=db_session, _={"role": "parent"})
    assert summary.student_name == "Nobody"
    assert summary.total_input_tokens == 0
    assert summary.by_model == []


async def test_student_usage_endpoint_only_reflects_that_students_own_calls(db_session):
    await record_usage("Emma", "claude-sonnet-4-6", input_tokens=1000, output_tokens=100)
    await record_usage("Liam", "claude-sonnet-4-6", input_tokens=9000, output_tokens=900)

    emma_summary = await student_usage("Emma", db=db_session, _={"role": "parent"})
    assert emma_summary.total_input_tokens == 1000
    assert emma_summary.estimated_cost_usd > 0
