"""
Router-level tests for GET /diagnostic/{student_name}/summary — the
parent-facing counterpart to the demo's GET /diagnostic/summary
(tests/test_diagnostic_router.py). Real in-memory SQLite via aiosqlite,
same fixture as tests/diagnostic/test_facade_persisted.py — not a mock.
Called directly (same pattern test_diagnostic_router.py already uses)
rather than through a full TestClient, since require_parent's own
JWT/fingerprint plumbing isn't what's under test here.
"""

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from core.config import settings
from core.database import Base
from routers.diagnostic import get_student_mastery_summary
from services.diagnostic import process_evidence


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        from core.encryption import initialize_encryption
        await initialize_encryption(settings.master_secret, session)
        yield session

    await engine.dispose()


def _fake_request() -> Request:
    scope = {
        "type": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [(b"user-agent", b"pytest")],
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_404s_before_any_evidence(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await get_student_mastery_summary(
            "Nobody", _fake_request(), auth={"role": "parent"}, db=db_session,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_returns_the_real_persisted_summary(db_session):
    await process_evidence(db_session, "Emma", "probe.cc.rote_count_20", "correct", 1.0, "K-2")

    summary = await get_student_mastery_summary(
        "Emma", _fake_request(), auth={"role": "parent"}, db=db_session,
    )
    assert summary.student_name == "Emma"
    assert summary.evidence_count == 1


@pytest.mark.asyncio
async def test_reflects_evidence_accumulated_across_multiple_prior_sessions(db_session):
    """Unlike the demo's single-session vector, this must reflect the
    WHOLE persisted history for the student, not just "this session"."""
    for _ in range(3):
        await process_evidence(db_session, "Liam", "probe.cc.rote_count_20", "correct", 1.0, "K-2")

    summary = await get_student_mastery_summary(
        "Liam", _fake_request(), auth={"role": "parent"}, db=db_session,
    )
    assert summary.evidence_count == 3
