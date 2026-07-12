"""
Real check for Diagnostic build-loop unit 2.2 (services/diagnostic's
db-backed process_evidence: load->update->encrypt->store round trip) —
see docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md.

A live Postgres was still unreachable in this sandbox for this unit too
(the Docker daemon itself did come up this session, unlike unit 2.1 —
but pulling any image from Docker Hub is blocked by the org's egress
policy at the proxy layer, confirmed via a 403 on
production.cloudfront.docker.com — a genuine, different limitation than
2.1's "no daemon" one, not something to route around per the sandbox's
own instructions).

What IS verified here, for real: a genuine AsyncSession backed by a real
(throwaway, in-memory) SQLite database via the aiosqlite async driver —
not a mock, not a sync engine standing in for async behavior like unit
2.1 used. core.encryption.initialize_encryption() runs for real against
this engine (generating and wrapping a real DATA_KEY), so every
encrypt_json/decrypt_json call in these tests is real AES-256-GCM, not
stubbed. What this does NOT prove: Postgres/asyncpg-specific SQL dialect
behavior (e.g. asyncpg's exact type coercion) — the same caveat 2.1
documented, still open for whenever a live Postgres becomes reachable.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, DiagnosticEvidenceLog, MasteryProfile
from core.encryption import decrypt_json
from services.diagnostic import apply_evidence, process_evidence


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
async def test_first_call_cold_starts_and_persists_a_mastery_profile_row(db_session):
    from sqlalchemy import select

    await process_evidence(
        db_session, "Emma", "probe.cc.rote_count_20", "correct", 1.0, "K-2",
    )

    row = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Emma")
    )).scalar_one_or_none()

    assert row is not None
    assert row.subject_area == "mathematics"
    assert row.evidence_count == 1


@pytest.mark.asyncio
async def test_persisted_vector_matches_the_in_memory_computation_exactly(db_session):
    """The acceptance criterion from the progress tracker: decrypt == in-memory."""
    from services.diagnostic.mastery import new_vector

    cold_start = new_vector("K-2")
    expected_vector, _ = await apply_evidence(cold_start, "probe.cc.rote_count_20", "correct", 1.0)

    persisted_vector = await process_evidence(
        db_session, "Liam", "probe.cc.rote_count_20", "correct", 1.0, "K-2",
    )

    assert persisted_vector == expected_vector

    from sqlalchemy import select
    row = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Liam")
    )).scalar_one_or_none()
    assert decrypt_json(row.profile_enc) == expected_vector


@pytest.mark.asyncio
async def test_second_call_loads_and_updates_the_existing_row_not_a_new_one(db_session):
    from sqlalchemy import select

    await process_evidence(db_session, "Noah", "probe.cc.rote_count_20", "correct", 1.0, "K-2")
    await process_evidence(db_session, "Noah", "probe.cc.rote_count_20", "correct", 1.0, "K-2")

    rows = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Noah")
    )).scalars().all()

    assert len(rows) == 1
    assert rows[0].evidence_count == 2


@pytest.mark.asyncio
async def test_unknown_probe_id_is_a_true_no_op_no_row_created(db_session):
    from sqlalchemy import select

    result_vector = await process_evidence(
        db_session, "Ava", "not.a.real.probe", "correct", 1.0, "K-2",
    )

    row = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Ava")
    )).scalar_one_or_none()

    assert row is None
    assert result_vector is not None  # cold-start vector still returned to the caller


@pytest.mark.asyncio
async def test_corrupted_existing_row_degrades_to_cold_start_instead_of_raising(db_session):
    """Mirrors ai_service.py's _save_assessment defensiveness: a row that
    fails to decrypt (wrong key, truncated blob, bit rot) must not crash
    the caller — and must not collide with the existing PK on the
    self-healing write that follows (see the None-vs-existing-row
    distinction in process_evidence's own try/except)."""
    from sqlalchemy import select

    db_session.add(MasteryProfile(
        student_name="Zoe", subject_area="mathematics",
        evidence_count=3, profile_enc=b"not a valid SAGE envelope",
    ))
    await db_session.commit()

    result_vector = await process_evidence(
        db_session, "Zoe", "probe.cc.rote_count_20", "correct", 1.0, "K-2",
    )
    assert result_vector["cc.rote_count_20"] > 0.5  # apply_evidence still ran on a cold-start vector

    rows = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Zoe")
    )).scalars().all()
    assert len(rows) == 1  # updated in place, not a duplicate PK row
    assert decrypt_json(rows[0].profile_enc) == result_vector


@pytest.mark.asyncio
async def test_evidence_log_stays_empty_when_flag_is_off_by_default(db_session):
    from sqlalchemy import select

    assert settings.diagnostic_evidence_log_enabled is False

    await process_evidence(db_session, "Sophia", "probe.cc.rote_count_20", "correct", 1.0, "K-2")

    rows = (await db_session.execute(select(DiagnosticEvidenceLog))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_evidence_log_gets_exactly_one_row_per_call_when_flag_is_on(db_session, monkeypatch):
    from sqlalchemy import select

    monkeypatch.setattr(settings, "diagnostic_evidence_log_enabled", True)

    await process_evidence(db_session, "Oliver", "probe.cc.rote_count_20", "correct", 1.0, "K-2")

    rows = (await db_session.execute(select(DiagnosticEvidenceLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].student_name == "Oliver"

    deltas = decrypt_json(rows[0].delta_enc)
    assert isinstance(deltas, list)
    assert len(deltas) == 1
    assert deltas[0]["skill_id"] == "cc.rote_count_20"
    assert deltas[0]["probe_id"] == "probe.cc.rote_count_20"
    assert "prior" in deltas[0] and "posterior" in deltas[0]


@pytest.mark.asyncio
async def test_evidence_log_row_never_contains_the_raw_outcome_or_confidence(db_session, monkeypatch):
    """The whole point of §5.3's delta-only design: no raw evidence, ever."""
    from sqlalchemy import select

    monkeypatch.setattr(settings, "diagnostic_evidence_log_enabled", True)

    await process_evidence(db_session, "Mia", "probe.cc.rote_count_20", "correct", 1.0, "K-2")

    row = (await db_session.execute(select(DiagnosticEvidenceLog))).scalar_one()
    deltas = decrypt_json(row.delta_enc)
    for delta in deltas:
        assert set(delta.keys()) == {"skill_id", "prior", "posterior", "probe_id", "model_used"}


@pytest.mark.asyncio
async def test_different_subject_areas_are_independent_rows_for_the_same_student(db_session):
    from sqlalchemy import select

    await process_evidence(db_session, "Ethan", "probe.cc.rote_count_20", "correct", 1.0, "K-2")
    await process_evidence(
        db_session, "Ethan", "probe.cc.rote_count_20", "correct", 1.0, "K-2",
        subject_area="reading",
    )

    rows = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Ethan")
    )).scalars().all()

    assert {row.subject_area for row in rows} == {"mathematics", "reading"}
