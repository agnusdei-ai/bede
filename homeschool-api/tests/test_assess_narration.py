"""
Real check that assess_narration's server-side handler (_save_assessment,
services/ai_service.py) does two things on every call, not just one: saves
the raw rubric scores to NarrationAssessment (already-shipped behavior) AND
feeds those same scores into the composition mastery rollup
(services/diagnostic/composition.py — see that module's own docstring).
Direct-function-call style, same convention test_record_skill_evidence.py
uses for _record_skill_evidence.
"""
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, MasteryProfile, NarrationAssessment
from core.encryption import decrypt_json, student_aad
from core import student_keys
from models.schemas import Subject
from services.ai_service import _save_assessment


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


_SCORES = {
    "completeness": 4, "sequence": 3, "detail": 4, "language_quality": 5, "synthesis": 3,
    "adaptive_signal": "advance", "bede_observation": "Told the story back with real detail.",
}


@pytest.mark.asyncio
async def test_save_assessment_writes_both_the_raw_row_and_the_composition_rollup(db_session):
    result = await _save_assessment(db_session, "Emma", Subject.living_books, _SCORES)

    assert result is not None  # unchanged existing contract (SSE assessment event)

    narration_row = (await db_session.execute(
        select(NarrationAssessment).where(NarrationAssessment.student_name == "Emma")
    )).scalar_one_or_none()
    assert narration_row is not None

    mastery_row = (await db_session.execute(
        select(MasteryProfile).where(
            MasteryProfile.student_name == "Emma", MasteryProfile.subject_area == "composition",
        )
    )).scalar_one_or_none()
    assert mastery_row is not None
    assert mastery_row.evidence_count == 1
    vector = decrypt_json(
        mastery_row.profile_enc,
        student_aad("mastery_profiles", "profile_enc", mastery_row.student_name, mastery_row.subject_area),
        await student_keys.get_existing(db_session, mastery_row.student_name),
    )
    assert vector["language_quality"] > 0.5  # the 5-of-5 score nudged this domain up


@pytest.mark.asyncio
async def test_second_narration_accumulates_a_second_composition_observation(db_session):
    await _save_assessment(db_session, "Noah", Subject.history, _SCORES)
    await _save_assessment(db_session, "Noah", Subject.mathematics, _SCORES)

    mastery_row = (await db_session.execute(
        select(MasteryProfile).where(
            MasteryProfile.student_name == "Noah", MasteryProfile.subject_area == "composition",
        )
    )).scalar_one_or_none()
    assert mastery_row.evidence_count == 2


@pytest.mark.asyncio
async def test_a_broken_composition_update_never_loses_the_narration_assessment(db_session):
    """Best-effort by design (see _save_assessment's own comment) — a bug in
    the newer composition path must never regress the narration-assessment
    save that's been shipping since before it existed."""
    with patch(
        "services.diagnostic.composition.process_assessment",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result = await _save_assessment(db_session, "Ava", Subject.science, _SCORES)

    assert result is not None
    narration_row = (await db_session.execute(
        select(NarrationAssessment).where(NarrationAssessment.student_name == "Ava")
    )).scalar_one_or_none()
    assert narration_row is not None
