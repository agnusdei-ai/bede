"""
Real check for Diagnostic build-loop unit 3.1 (record_skill_evidence tool +
_record_skill_evidence handler + _dispatch_completed_tool_call branch in
services/ai_service.py) — see docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md.

Acceptance criteria from the progress tracker: "child SSE byte-identical;
demo writes nothing." Verified here: _dispatch_completed_tool_call returns
(None, None) for this tool under every condition (proving no SSE chunk is
ever emitted — the child's stream is untouched regardless of whether the
evidence write succeeds, fails, or is skipped), db=None (the demo role)
never calls process_evidence, a non-math subject never calls it either, and
a real math-subject call genuinely persists a MasteryProfile row end to end
against the same real async SQLite engine unit 2.2's tests use.
"""

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, MasteryProfile
from models.schemas import GradeStage, SessionConfig, Subject
from services.ai_service import TUTOR_TOOLS, _dispatch_completed_tool_call


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


def _config(**overrides):
    defaults = dict(student_name="Emma", grade="1", grade_stage=GradeStage.foundations)
    defaults.update(overrides)
    return SessionConfig(**defaults)


def test_record_skill_evidence_tool_is_registered_with_the_right_schema():
    tool = next((t for t in TUTOR_TOOLS if t["name"] == "record_skill_evidence"), None)
    assert tool is not None
    assert tool["input_schema"]["required"] == ["probe_id", "outcome"]
    assert set(tool["input_schema"]["properties"]["outcome"]["enum"]) == {
        "correct", "partial", "incorrect", "hint_dependent",
    }


@pytest.mark.asyncio
async def test_dispatch_never_emits_an_sse_chunk_for_record_skill_evidence(db_session):
    """The core silence guarantee: regardless of db state, subject, or
    whether the tool input is even valid, the child's stream sees nothing."""
    tool_input = {"probe_id": "probe.cc.rote_count_20", "outcome": "correct"}

    result_with_db = await _dispatch_completed_tool_call(
        "record_skill_evidence", tool_input, db_session, _config(), Subject.mathematics,
    )
    assert result_with_db == (None, None)

    result_no_db = await _dispatch_completed_tool_call(
        "record_skill_evidence", tool_input, None, _config(), Subject.mathematics,
    )
    assert result_no_db == (None, None)

    result_bad_input = await _dispatch_completed_tool_call(
        "record_skill_evidence", {"outcome": "not-a-real-outcome"}, db_session, _config(), Subject.mathematics,
    )
    assert result_bad_input == (None, None)


@pytest.mark.asyncio
async def test_demo_role_db_none_writes_nothing(monkeypatch):
    """demo_code role sets db=None in routers/tutor.py — this must never
    reach process_evidence at all, not just fail silently after calling it."""
    mock_process_evidence = AsyncMock()
    monkeypatch.setattr("services.diagnostic.process_evidence", mock_process_evidence)

    await _dispatch_completed_tool_call(
        "record_skill_evidence",
        {"probe_id": "probe.cc.rote_count_20", "outcome": "correct"},
        None, _config(), Subject.mathematics,
    )

    mock_process_evidence.assert_not_called()


@pytest.mark.asyncio
async def test_non_math_subject_writes_nothing(db_session, monkeypatch):
    mock_process_evidence = AsyncMock()
    monkeypatch.setattr("services.diagnostic.process_evidence", mock_process_evidence)

    await _dispatch_completed_tool_call(
        "record_skill_evidence",
        {"probe_id": "probe.cc.rote_count_20", "outcome": "correct"},
        db_session, _config(), Subject.history,
    )

    mock_process_evidence.assert_not_called()


@pytest.mark.asyncio
async def test_malformed_tool_input_is_logged_and_swallowed_not_raised(db_session):
    """Mirrors _save_assessment's contract: a diagnostic-recording failure
    must never propagate and break the child's tutoring turn."""
    await _dispatch_completed_tool_call(
        "record_skill_evidence",
        {"probe_id": "probe.cc.rote_count_20", "outcome": "definitely-not-valid"},
        db_session, _config(), Subject.mathematics,
    )  # no exception raised is the assertion

    rows = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Emma")
    )).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_a_hallucinated_but_well_formed_probe_id_is_a_safe_no_op(db_session):
    """Unlike a malformed outcome (caught by Pydantic validation before it
    ever reaches process_evidence), a syntactically valid but unregistered
    probe_id — the more realistic risk once this tool ships, since no
    subject-context probe_id list exists yet (that's unit 3.2) — passes
    RecordSkillEvidenceInput validation cleanly and only becomes a no-op
    two layers deeper, in qmatrix.q_row(). Confirming that chain actually
    holds end-to-end, not just trusting it by inspection."""
    result = await _dispatch_completed_tool_call(
        "record_skill_evidence",
        {"probe_id": "probe.a_plausible_but_made_up_skill", "outcome": "correct"},
        db_session, _config(), Subject.mathematics,
    )
    assert result == (None, None)

    rows = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Emma")
    )).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_valid_math_evidence_genuinely_persists_end_to_end(db_session):
    await _dispatch_completed_tool_call(
        "record_skill_evidence",
        {"probe_id": "probe.cc.rote_count_20", "outcome": "correct", "confidence": 1.0},
        db_session, _config(student_name="Liam"), Subject.mathematics,
    )

    row = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Liam")
    )).scalar_one_or_none()
    assert row is not None
    assert row.evidence_count == 1
