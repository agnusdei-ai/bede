"""
_record_language_evidence (services/ai_service.py) — the dispatch/gating layer
between record_language_evidence tool calls and services/diagnostic/
language_exposure.py. Mirrors tests/test_record_phonics_evidence.py's
structure, adapted for language exposure's three-subject gate (History,
Saints, Art & Music) with no grade-stage restriction (unlike phonics' K-2-only
gate).
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
from services.ai_service import TUTOR_TOOLS, _record_language_evidence


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


def test_record_language_evidence_tool_is_registered_with_the_right_schema():
    tool = next((t for t in TUTOR_TOOLS if t["name"] == "record_language_evidence"), None)
    assert tool is not None
    assert tool["input_schema"]["required"] == ["language", "outcome"]
    assert set(tool["input_schema"]["properties"]["outcome"]["enum"]) == {
        "correct", "partial", "incorrect", "hint_dependent",
    }
    assert "latin" in tool["input_schema"]["properties"]["language"]["enum"]


@pytest.mark.asyncio
async def test_returns_none_under_every_condition_proving_no_sse_chunk_is_possible():
    tool_input = {"language": "latin", "outcome": "correct"}
    assert await _record_language_evidence(None, _config(), Subject.history, tool_input) is None
    assert await _record_language_evidence(None, _config(), Subject.history, {"outcome": "bad"}) is None


@pytest.mark.asyncio
async def test_wrong_subject_never_reaches_the_backend(db_session, monkeypatch):
    mock_process_evidence = AsyncMock()
    monkeypatch.setattr("services.diagnostic.language_exposure.process_evidence", mock_process_evidence)

    await _record_language_evidence(
        db_session, _config(), Subject.mathematics,
        {"language": "latin", "outcome": "correct"},
    )

    mock_process_evidence.assert_not_called()
    rows = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Wren")
    )).scalars().all()
    assert rows == []


@pytest.mark.asyncio
@pytest.mark.parametrize("subject", [Subject.history, Subject.saints, Subject.art_music])
async def test_every_gated_subject_reaches_the_backend(db_session, subject):
    await _record_language_evidence(
        db_session, _config(student_name="Multi"), subject,
        {"language": "latin", "outcome": "correct"},
    )
    row = (await db_session.execute(
        select(MasteryProfile).where(
            MasteryProfile.student_name == "Multi", MasteryProfile.subject_area == "language_exposure",
        )
    )).scalar_one_or_none()
    assert row is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", [GradeStage.foundations, GradeStage.core_mastery, GradeStage.independent])
async def test_every_grade_stage_reaches_the_backend(db_session, stage):
    """Unlike phonics (K-2 only), language exposure applies to every grade
    stage — confirming no stage-based gate accidentally crept in."""
    await _record_language_evidence(
        db_session, _config(student_name="AllStages", grade_stage=stage), Subject.history,
        {"language": "latin", "outcome": "correct"},
    )
    row = (await db_session.execute(
        select(MasteryProfile).where(
            MasteryProfile.student_name == "AllStages", MasteryProfile.subject_area == "language_exposure",
        )
    )).scalar_one_or_none()
    assert row is not None


@pytest.mark.asyncio
async def test_db_none_writes_nothing():
    """No demo backend exists for language exposure (unlike math's
    record_skill_evidence) — db=None is the true no-op default."""
    await _record_language_evidence(
        None, _config(), Subject.history,
        {"language": "latin", "outcome": "correct"},
    )  # no exception raised is the assertion


@pytest.mark.asyncio
async def test_malformed_tool_input_is_logged_and_swallowed_not_raised(db_session):
    await _record_language_evidence(
        db_session, _config(), Subject.history,
        {"language": "latin", "outcome": "definitely-not-valid"},
    )  # no exception raised is the assertion

    rows = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Wren")
    )).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_a_hallucinated_but_well_formed_language_is_a_safe_no_op(db_session):
    """language is a plain str field (Field(max_length=40), not a Literal),
    so an unregistered-but-plausible language passes RecordLanguageEvidenceInput
    validation cleanly and only becomes a no-op two layers deeper, in
    language_exposure.apply_evidence()."""
    await _record_language_evidence(
        db_session, _config(), Subject.history,
        {"language": "a_plausible_but_made_up_language", "outcome": "correct"},
    )

    rows = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Wren")
    )).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_valid_language_evidence_genuinely_persists_end_to_end_via_db(db_session):
    await _record_language_evidence(
        db_session, _config(student_name="Grace"), Subject.saints,
        {"language": "spanish", "outcome": "correct"},
    )

    row = (await db_session.execute(
        select(MasteryProfile).where(
            MasteryProfile.student_name == "Grace", MasteryProfile.subject_area == "language_exposure",
        )
    )).scalar_one_or_none()
    assert row is not None
    assert row.evidence_count == 1


@pytest.mark.asyncio
async def test_second_valid_call_accumulates_on_the_same_row_across_subjects(db_session):
    """A History check-in and a later Art & Music check-in for the same
    student both accumulate onto one language_exposure row."""
    await _record_language_evidence(
        db_session, _config(student_name="Noah"), Subject.history,
        {"language": "latin", "outcome": "correct"},
    )
    await _record_language_evidence(
        db_session, _config(student_name="Noah"), Subject.art_music,
        {"language": "italian", "outcome": "partial"},
    )

    rows = (await db_session.execute(
        select(MasteryProfile).where(
            MasteryProfile.student_name == "Noah", MasteryProfile.subject_area == "language_exposure",
        )
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].evidence_count == 2


# ── The classical-language subjects' narrower gate ───────────────────────
#
# Latin and Greek (services/latin_catalog.py, services/greek_catalog.py)
# record evidence too, but unlike the three opportunistic subjects above,
# each may only ever claim a reading on its OWN language — a Latin lesson
# has no business producing evidence about German, and a Greek lesson none
# about Latin.

@pytest.mark.asyncio
@pytest.mark.parametrize("subject,language", [
    (Subject.latin, "latin"),
    (Subject.greek, "greek"),
])
async def test_classical_subject_records_its_own_language(db_session, subject, language):
    await _record_language_evidence(
        db_session, _config(student_name=f"Own{language}"), subject,
        {"language": language, "outcome": "correct"},
    )
    row = (await db_session.execute(
        select(MasteryProfile).where(
            MasteryProfile.student_name == f"Own{language}",
            MasteryProfile.subject_area == "language_exposure",
        )
    )).scalar_one_or_none()
    assert row is not None, f"the {subject.value} subject should feed the {language} domain"


@pytest.mark.asyncio
@pytest.mark.parametrize("subject,wrong_language", [
    (Subject.latin, "greek"),
    (Subject.greek, "latin"),
])
async def test_classical_subjects_do_not_claim_each_others_language(
    db_session, subject, wrong_language, monkeypatch,
):
    """
    The pair that matters most now that both exist: a Greek session must
    not quietly record Latin evidence, or a parent reading the Progress
    page would see growth in a subject the child never sat.
    """
    mock_process_evidence = AsyncMock()
    monkeypatch.setattr("services.diagnostic.language_exposure.process_evidence", mock_process_evidence)

    await _record_language_evidence(
        db_session, _config(student_name="CrossTalk"), subject,
        {"language": wrong_language, "outcome": "correct"},
    )

    mock_process_evidence.assert_not_called()


@pytest.mark.asyncio
async def test_latin_subject_records_latin_evidence(db_session):
    await _record_language_evidence(
        db_session, _config(student_name="Cato"), Subject.latin,
        {"language": "latin", "outcome": "correct"},
    )
    row = (await db_session.execute(
        select(MasteryProfile).where(
            MasteryProfile.student_name == "Cato",
            MasteryProfile.subject_area == "language_exposure",
        )
    )).scalar_one_or_none()
    assert row is not None, "the Latin subject should feed the language_exposure latin domain"


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["german", "french", "greek", "italian", "spanish"])
async def test_latin_subject_refuses_evidence_for_any_other_language(db_session, language, monkeypatch):
    mock_process_evidence = AsyncMock()
    monkeypatch.setattr("services.diagnostic.language_exposure.process_evidence", mock_process_evidence)

    await _record_language_evidence(
        db_session, _config(student_name="Cato"), Subject.latin,
        {"language": language, "outcome": "correct"},
    )

    mock_process_evidence.assert_not_called()
    rows = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Cato")
    )).scalars().all()
    assert rows == [], f"a Latin session must not record a reading on {language}"


@pytest.mark.asyncio
async def test_opportunistic_subjects_keep_accepting_every_language(db_session):
    """
    The narrower Latin gate must not have narrowed the three existing
    subjects along with it — an Art & Music session legitimately produces
    Italian evidence.
    """
    await _record_language_evidence(
        db_session, _config(student_name="Vivaldi"), Subject.art_music,
        {"language": "italian", "outcome": "correct"},
    )
    row = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Vivaldi")
    )).scalar_one_or_none()
    assert row is not None
