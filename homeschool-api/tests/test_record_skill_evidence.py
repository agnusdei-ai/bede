"""
Real check for Diagnostic build-loop unit 3.1 (record_skill_evidence tool +
_record_skill_evidence handler in services/ai_service.py) — see
docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md.

Originally built against a _dispatch_completed_tool_call/_stream_tutor_events
split that no longer exists on main (reverted alongside the BYOK feature by
a concurrent session — see the unit 3.1 decisions log for the full
reconciliation). Rewritten to test _record_skill_evidence directly, since
that's now the actual integration point the inline dispatch in
stream_tutor_response's content_block_stop handling calls.

_record_skill_evidence unifies two backends discovered to already coexist
on main once this session's Phase 3 work and a concurrent session's
demo-only mastery preview were reconciled: demo_code routes to the
in-memory, single-session preview (services/diagnostic_demo.py); db routes
to the real, persistent parent/child path
(services.diagnostic.process_evidence). Verified here: both routes work
correctly in isolation, neither is ever called when it shouldn't be (the
other backend's guard, a non-math subject, malformed/hallucinated input),
and — since _record_skill_evidence itself returns nothing and emits no SSE
chunk at either call site — the child's stream is untouched regardless of
outcome.
"""

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import core.demo_code_session as demo_code_session
from core.config import settings
from core.database import Base, MasteryProfile
from models.schemas import GradeStage, SessionConfig, Subject
from services.ai_service import TUTOR_TOOLS, _record_skill_evidence


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


def setup_function():
    demo_code_session._codes = {}


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
async def test_returns_none_under_every_condition_proving_no_sse_chunk_is_possible():
    """_record_skill_evidence has no return value at all (None always) —
    the caller in stream_tutor_response never yields anything for this
    branch, so there is no code path that could emit an SSE chunk."""
    tool_input = {"probe_id": "probe.cc.rote_count_20", "outcome": "correct"}
    assert await _record_skill_evidence(None, None, _config(), Subject.mathematics, tool_input) is None
    assert await _record_skill_evidence(None, "fake-code", _config(), Subject.mathematics, tool_input) is None
    assert await _record_skill_evidence(None, None, _config(), Subject.mathematics, {"outcome": "bad"}) is None


@pytest.mark.asyncio
async def test_non_math_subject_reaches_neither_backend(db_session, monkeypatch):
    mock_process_evidence = AsyncMock()
    mock_demo = AsyncMock()
    monkeypatch.setattr("services.diagnostic.process_evidence", mock_process_evidence)
    monkeypatch.setattr("services.diagnostic_demo.record_skill_evidence_demo", mock_demo)

    code = demo_code_session.generate_code("Sam", "3")
    await _record_skill_evidence(
        db_session, None, _config(), Subject.history,
        {"probe_id": "probe.cc.rote_count_20", "outcome": "correct"},
    )
    await _record_skill_evidence(
        None, code, _config(), Subject.history,
        {"probe_id": "probe.cc.rote_count_20", "outcome": "correct"},
    )

    mock_process_evidence.assert_not_called()
    mock_demo.assert_not_called()


@pytest.mark.asyncio
async def test_demo_code_routes_to_the_demo_backend_only(db_session, monkeypatch):
    """demo_code set (db irrelevant/None per routers/tutor.py's contract)
    must reach the in-memory demo adapter, never the real db path."""
    mock_process_evidence = AsyncMock()
    monkeypatch.setattr("services.diagnostic.process_evidence", mock_process_evidence)

    code = demo_code_session.generate_code("Sam", "3")
    await _record_skill_evidence(
        None, code, _config(student_name="Sam", grade="3", grade_stage=GradeStage.core_mastery),
        Subject.mathematics,
        {"probe_id": "probe.oa.multiplication_facts", "outcome": "correct", "confidence": 1.0},
    )

    mock_process_evidence.assert_not_called()
    assert demo_code_session.get_mastery_vector(code) is not None


@pytest.mark.asyncio
async def test_demo_backend_never_writes_for_a_different_code():
    code_a = demo_code_session.generate_code("Sam", "3")
    code_b = demo_code_session.generate_code("Alex", "3")
    await _record_skill_evidence(
        None, code_a, _config(student_name="Sam", grade="3", grade_stage=GradeStage.core_mastery),
        Subject.mathematics,
        {"probe_id": "probe.oa.multiplication_facts", "outcome": "correct"},
    )
    assert demo_code_session.get_mastery_vector(code_a) is not None
    assert demo_code_session.get_mastery_vector(code_b) is None


@pytest.mark.asyncio
async def test_db_none_and_demo_code_none_writes_nothing(monkeypatch):
    """Neither backend set (shouldn't happen per routers/tutor.py's
    contract, but this is the true no-op default, not an error)."""
    mock_process_evidence = AsyncMock()
    monkeypatch.setattr("services.diagnostic.process_evidence", mock_process_evidence)

    await _record_skill_evidence(
        None, None, _config(), Subject.mathematics,
        {"probe_id": "probe.cc.rote_count_20", "outcome": "correct"},
    )

    mock_process_evidence.assert_not_called()


@pytest.mark.asyncio
async def test_malformed_tool_input_is_logged_and_swallowed_not_raised(db_session):
    """Mirrors _save_assessment's contract: a diagnostic-recording failure
    must never propagate and break the child's tutoring turn."""
    await _record_skill_evidence(
        db_session, None, _config(), Subject.mathematics,
        {"probe_id": "probe.cc.rote_count_20", "outcome": "definitely-not-valid"},
    )  # no exception raised is the assertion

    rows = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Emma")
    )).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_a_hallucinated_but_well_formed_probe_id_is_a_safe_no_op(db_session):
    """Unlike a malformed outcome (caught by Pydantic validation before it
    ever reaches process_evidence), a syntactically valid but unregistered
    probe_id — a real risk since no subject-context probe_id list existed
    until this same reconciliation — passes RecordSkillEvidenceInput
    validation cleanly and only becomes a no-op two layers deeper, in
    qmatrix.q_row(). Confirming that chain actually holds end-to-end."""
    await _record_skill_evidence(
        db_session, None, _config(), Subject.mathematics,
        {"probe_id": "probe.a_plausible_but_made_up_skill", "outcome": "correct"},
    )

    rows = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Emma")
    )).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_valid_math_evidence_genuinely_persists_end_to_end_via_db(db_session):
    await _record_skill_evidence(
        db_session, None, _config(student_name="Liam"), Subject.mathematics,
        {"probe_id": "probe.cc.rote_count_20", "outcome": "correct", "confidence": 1.0},
    )

    row = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Liam")
    )).scalar_one_or_none()
    assert row is not None
    assert row.evidence_count == 1
