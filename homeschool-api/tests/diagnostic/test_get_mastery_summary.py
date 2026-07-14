"""
Real check for services.diagnostic.get_mastery_summary — the production
counterpart to services/diagnostic_demo.py's get_mastery_summary_demo,
reading a student's REAL, persisted mastery_profiles row instead of a
demo code's ephemeral single-session vector. Same db_session fixture as
tests/diagnostic/test_facade_persisted.py (real in-memory SQLite via
aiosqlite, real AES-256-GCM encryption) — not a mock.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base
from services.diagnostic import get_mastery_summary, process_evidence
from services.diagnostic.mastery import CALIBRATION_THRESHOLD


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


@pytest.mark.asyncio
async def test_returns_none_when_no_evidence_exists_yet(db_session):
    assert await get_mastery_summary(db_session, "Nobody") is None


@pytest.mark.asyncio
async def test_returns_the_same_shape_as_the_demo_summary(db_session):
    await process_evidence(db_session, "Emma", "probe.cc.rote_count_20", "correct", 1.0, "K-2")

    summary = await get_mastery_summary(db_session, "Emma")

    assert summary["student_name"] == "Emma"
    assert summary["subject_area"] == "mathematics"
    assert summary["evidence_count"] == 1
    assert isinstance(summary["domains"], list) and summary["domains"]
    assert "gaps" in summary and "next_steps" in summary
    assert "updated_at" in summary


@pytest.mark.asyncio
async def test_calibration_true_below_threshold_false_at_or_above(db_session):
    for _ in range(CALIBRATION_THRESHOLD - 1):
        await process_evidence(db_session, "Liam", "probe.cc.rote_count_20", "correct", 1.0, "K-2")
    below = await get_mastery_summary(db_session, "Liam")
    assert below["evidence_count"] == CALIBRATION_THRESHOLD - 1
    assert below["calibration"] is True

    await process_evidence(db_session, "Liam", "probe.cc.rote_count_20", "correct", 1.0, "K-2")
    at_threshold = await get_mastery_summary(db_session, "Liam")
    assert at_threshold["evidence_count"] == CALIBRATION_THRESHOLD
    assert at_threshold["calibration"] is False


@pytest.mark.asyncio
async def test_evidence_accumulates_across_calls_not_reset_per_summary_read(db_session):
    await process_evidence(db_session, "Noah", "probe.cc.rote_count_20", "correct", 1.0, "K-2")
    first = await get_mastery_summary(db_session, "Noah")
    assert first["evidence_count"] == 1

    await process_evidence(db_session, "Noah", "probe.cc.rote_count_20", "correct", 1.0, "K-2")
    second = await get_mastery_summary(db_session, "Noah")
    assert second["evidence_count"] == 2


@pytest.mark.asyncio
async def test_different_students_are_fully_independent(db_session):
    await process_evidence(db_session, "Ava", "probe.cc.rote_count_20", "correct", 1.0, "K-2")

    assert await get_mastery_summary(db_session, "Ava") is not None
    assert await get_mastery_summary(db_session, "Zoe") is None


@pytest.mark.asyncio
async def test_a_gap_probability_is_reflected_in_the_gaps_list(db_session):
    await process_evidence(db_session, "Sophia", "probe.cc.rote_count_20", "incorrect", 1.0, "K-2")

    summary = await get_mastery_summary(db_session, "Sophia")
    gap_ids = {s["skill_id"] for s in summary["gaps"]}
    assert "cc.rote_count_20" in gap_ids
