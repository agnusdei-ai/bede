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
from services.diagnostic.composition import process_assessment
from services.diagnostic.phonics import process_evidence as process_phonics_evidence


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


# ── subject_area dispatch (composition mastery — services.diagnostic.composition) ──

_SCORES = {"completeness": 4, "sequence": 3, "detail": 4, "language_quality": 5, "synthesis": 3}


@pytest.mark.asyncio
async def test_subject_area_defaults_to_mathematics(db_session):
    """No subject_area passed at all — must behave exactly as before this
    param existed, matching every pre-existing call site/test above."""
    await process_evidence(db_session, "Emma", "probe.cc.rote_count_20", "correct", 1.0, "K-2")

    summary = await get_student_mastery_summary(
        "Emma", _fake_request(), auth={"role": "parent"}, db=db_session,
    )
    assert summary.subject_area == "mathematics"


@pytest.mark.asyncio
async def test_subject_area_composition_returns_the_composition_engines_summary(db_session):
    await process_assessment(db_session, "Grace", _SCORES)

    summary = await get_student_mastery_summary(
        "Grace", _fake_request(), subject_area="composition", auth={"role": "parent"}, db=db_session,
    )
    assert summary.subject_area == "composition"
    assert summary.evidence_count == 1
    assert len(summary.domains) == 5


@pytest.mark.asyncio
async def test_math_and_composition_summaries_are_independent_for_the_same_student(db_session):
    await process_evidence(db_session, "Oliver", "probe.cc.rote_count_20", "correct", 1.0, "K-2")
    await process_assessment(db_session, "Oliver", _SCORES)

    math_summary = await get_student_mastery_summary(
        "Oliver", _fake_request(), subject_area="mathematics", auth={"role": "parent"}, db=db_session,
    )
    composition_summary = await get_student_mastery_summary(
        "Oliver", _fake_request(), subject_area="composition", auth={"role": "parent"}, db=db_session,
    )
    assert math_summary.subject_area == "mathematics"
    assert composition_summary.subject_area == "composition"
    assert math_summary.evidence_count == 1
    assert composition_summary.evidence_count == 1


@pytest.mark.asyncio
async def test_composition_404s_before_any_narration_assessed(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await get_student_mastery_summary(
            "Nobody", _fake_request(), subject_area="composition", auth={"role": "parent"}, db=db_session,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_unrecognized_subject_area_404s_rather_than_erroring(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await get_student_mastery_summary(
            "Emma", _fake_request(), subject_area="astrology", auth={"role": "parent"}, db=db_session,
        )
    assert exc_info.value.status_code == 404


# ── subject_area dispatch (phonics — services.diagnostic.phonics) ───────────


@pytest.mark.asyncio
async def test_subject_area_phonics_returns_the_phonics_engines_summary(db_session):
    await process_phonics_evidence(db_session, "Wren", "letter_sound", "correct")

    summary = await get_student_mastery_summary(
        "Wren", _fake_request(), subject_area="phonics", auth={"role": "parent"}, db=db_session,
    )
    assert summary.subject_area == "phonics"
    assert summary.evidence_count == 1
    assert len(summary.domains) == 6


@pytest.mark.asyncio
async def test_phonics_404s_before_any_evidence_recorded(db_session):
    with pytest.raises(HTTPException) as exc_info:
        await get_student_mastery_summary(
            "Nobody", _fake_request(), subject_area="phonics", auth={"role": "parent"}, db=db_session,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_math_composition_and_phonics_summaries_are_independent_for_the_same_student(db_session):
    await process_evidence(db_session, "Ethan", "probe.cc.rote_count_20", "correct", 1.0, "K-2")
    await process_assessment(db_session, "Ethan", _SCORES)
    await process_phonics_evidence(db_session, "Ethan", "letter_sound", "correct")

    math_summary = await get_student_mastery_summary(
        "Ethan", _fake_request(), subject_area="mathematics", auth={"role": "parent"}, db=db_session,
    )
    composition_summary = await get_student_mastery_summary(
        "Ethan", _fake_request(), subject_area="composition", auth={"role": "parent"}, db=db_session,
    )
    phonics_summary = await get_student_mastery_summary(
        "Ethan", _fake_request(), subject_area="phonics", auth={"role": "parent"}, db=db_session,
    )
    assert math_summary.subject_area == "mathematics"
    assert composition_summary.subject_area == "composition"
    assert phonics_summary.subject_area == "phonics"
    assert math_summary.evidence_count == 1
    assert composition_summary.evidence_count == 1
    assert phonics_summary.evidence_count == 1
