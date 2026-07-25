"""
_record_phonics_evidence (services/ai_service.py) — the dispatch/gating layer
between record_phonics_evidence tool calls and services/diagnostic/phonics.py.
Mirrors tests/test_record_skill_evidence.py's structure, adapted for phonics'
narrower shape: no demo backend, no confidence field, and a second gate
(K-2 language_arts only) baked in as a code-level backstop to the prompt-level
gate in _phonics_checkin_note.
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
from services.ai_service import TUTOR_TOOLS, _record_phonics_evidence


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
    defaults = dict(student_name="Wren", grade="1", grade_stage=GradeStage.foundations)
    defaults.update(overrides)
    return SessionConfig(**defaults)


def test_record_phonics_evidence_tool_is_registered_with_the_right_schema():
    tool = next((t for t in TUTOR_TOOLS if t["name"] == "record_phonics_evidence"), None)
    assert tool is not None
    assert tool["input_schema"]["required"] == ["domain", "outcome"]
    assert set(tool["input_schema"]["properties"]["outcome"]["enum"]) == {
        "correct", "partial", "incorrect", "hint_dependent",
    }
    assert "letter_sound" in tool["input_schema"]["properties"]["domain"]["enum"]


@pytest.mark.asyncio
async def test_returns_none_under_every_condition_proving_no_sse_chunk_is_possible():
    """_record_phonics_evidence has no return value at all (None always) —
    the caller in stream_tutor_response never yields anything for this
    branch, so there is no code path that could emit an SSE chunk."""
    tool_input = {"domain": "letter_sound", "outcome": "correct"}
    assert await _record_phonics_evidence(None, _config(), Subject.language_arts, tool_input) is None
    assert await _record_phonics_evidence(None, _config(), Subject.language_arts, {"outcome": "bad"}) is None


@pytest.mark.asyncio
async def test_wrong_subject_never_reaches_the_backend(db_session, monkeypatch):
    mock_process_evidence = AsyncMock()
    monkeypatch.setattr("services.diagnostic.phonics.process_evidence", mock_process_evidence)

    await _record_phonics_evidence(
        db_session, _config(), Subject.mathematics,
        {"domain": "letter_sound", "outcome": "correct"},
    )

    mock_process_evidence.assert_not_called()
    rows = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Wren")
    )).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_wrong_grade_stage_never_reaches_the_backend(db_session, monkeypatch):
    mock_process_evidence = AsyncMock()
    monkeypatch.setattr("services.diagnostic.phonics.process_evidence", mock_process_evidence)

    await _record_phonics_evidence(
        db_session, _config(grade="5", grade_stage=GradeStage.core_mastery), Subject.language_arts,
        {"domain": "letter_sound", "outcome": "correct"},
    )

    mock_process_evidence.assert_not_called()
    rows = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Wren")
    )).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_db_none_writes_nothing():
    """No demo backend exists for phonics (unlike math's record_skill_evidence)
    — db=None is the true no-op default, not an error."""
    await _record_phonics_evidence(
        None, _config(), Subject.language_arts,
        {"domain": "letter_sound", "outcome": "correct"},
    )  # no exception raised is the assertion


@pytest.mark.asyncio
async def test_malformed_tool_input_is_logged_and_swallowed_not_raised(db_session):
    """Mirrors _record_skill_evidence's contract: a diagnostic-recording
    failure must never propagate and break the child's tutoring turn."""
    await _record_phonics_evidence(
        db_session, _config(), Subject.language_arts,
        {"domain": "letter_sound", "outcome": "definitely-not-valid"},
    )  # no exception raised is the assertion

    rows = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Wren")
    )).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_a_hallucinated_but_well_formed_domain_is_a_safe_no_op(db_session):
    """domain is a plain str field (Field(max_length=40), not a Literal), so
    an unregistered-but-plausible domain passes RecordPhonicsEvidenceInput
    validation cleanly and only becomes a no-op two layers deeper, in
    phonics.apply_evidence(). Confirming that chain holds end-to-end,
    mirroring test_record_skill_evidence.py's equivalent probe_id test."""
    await _record_phonics_evidence(
        db_session, _config(), Subject.language_arts,
        {"domain": "a_plausible_but_made_up_domain", "outcome": "correct"},
    )

    rows = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Wren")
    )).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_valid_phonics_evidence_genuinely_persists_end_to_end_via_db(db_session):
    await _record_phonics_evidence(
        db_session, _config(student_name="Grace"), Subject.language_arts,
        {"domain": "cvc_blending", "outcome": "correct"},
    )

    row = (await db_session.execute(
        select(MasteryProfile).where(
            MasteryProfile.student_name == "Grace", MasteryProfile.subject_area == "phonics",
        )
    )).scalar_one_or_none()
    assert row is not None
    assert row.evidence_count == 1


@pytest.mark.asyncio
async def test_second_valid_call_accumulates_on_the_same_row(db_session):
    await _record_phonics_evidence(
        db_session, _config(student_name="Noah"), Subject.language_arts,
        {"domain": "letter_sound", "outcome": "correct"},
    )
    await _record_phonics_evidence(
        db_session, _config(student_name="Noah"), Subject.language_arts,
        {"domain": "sight_words", "outcome": "partial"},
    )

    rows = (await db_session.execute(
        select(MasteryProfile).where(
            MasteryProfile.student_name == "Noah", MasteryProfile.subject_area == "phonics",
        )
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].evidence_count == 2
