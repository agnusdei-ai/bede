"""
Tests for services/student_deletion.py — the comprehensive per-student
delete that closes a real COPPA-relevant gap: DELETE /pod/configs/{student}
used to only remove the StudentConfig row, silently leaving narration
history, learner profile, mastery tracking, session transcripts, usage
events, and voice enrollment behind forever with no way for a parent to
actually remove them (and no frontend UI ever called the deletion
endpoints that did exist, before this change).
"""
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import (
    ApiUsageEvent,
    Base,
    DiagnosticEvidenceLog,
    LearnerBehaviorCheck,
    LearnerProfile,
    MasteryProfile,
    NarrationAssessment,
    SessionTranscript,
    StudentConfig,
    VoiceProfile,
)
from routers.pod import delete_student_config
from services.student_deletion import delete_all_student_data


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
    return Request({"type": "http", "client": ("127.0.0.1", 12345), "headers": [(b"user-agent", b"pytest")]})


_next_id = iter(range(1, 100_000))


async def _seed_all_tables(db, student_name: str):
    from core.encryption import encrypt_json

    now = datetime.now(timezone.utc)
    db.add(StudentConfig(student_name=student_name, config_enc=encrypt_json({"a": 1})))
    db.add(VoiceProfile(student_name=student_name, profile_enc=encrypt_json({"a": 1})))
    # NarrationAssessment/SessionTranscript use a plain (non-SQLite-variant)
    # BigInteger PK, so SQLite won't autoincrement it for us the way the
    # other bigint-PK tables here do — supply an explicit id.
    db.add(NarrationAssessment(
        id=next(_next_id), student_name=student_name, subject="mathematics", session_date=now,
        assessment_enc=encrypt_json({"a": 1}),
    ))
    db.add(LearnerProfile(student_name=student_name, session_count=3, profile_enc=encrypt_json({"a": 1})))
    db.add(LearnerBehaviorCheck(student_name=student_name, count_enc=encrypt_json({"count": 2})))
    db.add(MasteryProfile(
        student_name=student_name, subject_area="mathematics",
        evidence_count=1, profile_enc=encrypt_json({"a": 1}),
    ))
    db.add(DiagnosticEvidenceLog(
        student_name=student_name, subject_area="mathematics",
        observed_at=now, delta_enc=encrypt_json({"a": 1}),
    ))
    db.add(SessionTranscript(
        id=next(_next_id), student_name=student_name, session_date=now, subjects="mathematics",
        duration_minutes=20, transcript_enc=encrypt_json({"a": 1}),
    ))
    db.add(ApiUsageEvent(student_name=student_name, model="claude-sonnet-4-6", input_tokens=10, output_tokens=5))
    await db.commit()


async def _row_counts_for(db, student_name: str) -> dict:
    counts = {}
    for label, model in (
        ("student_config", StudentConfig),
        ("voice_profile", VoiceProfile),
        ("narration_assessments", NarrationAssessment),
        ("learner_profile", LearnerProfile),
        ("learner_behavior_check", LearnerBehaviorCheck),
        ("mastery_profiles", MasteryProfile),
        ("diagnostic_evidence_log", DiagnosticEvidenceLog),
        ("session_transcripts", SessionTranscript),
        ("api_usage_events", ApiUsageEvent),
    ):
        result = await db.execute(select(model).where(model.student_name == student_name))
        counts[label] = len(result.scalars().all())
    return counts


# ── services.student_deletion.delete_all_student_data ────────────────────────

@pytest.mark.asyncio
async def test_deletes_every_row_across_all_nine_tables(db_session):
    await _seed_all_tables(db_session, "Emma")
    before = await _row_counts_for(db_session, "Emma")
    assert all(n > 0 for n in before.values()), f"seeding didn't actually populate every table: {before}"

    counts = await delete_all_student_data(db_session, "Emma")

    after = await _row_counts_for(db_session, "Emma")
    assert all(n == 0 for n in after.values()), f"some rows survived deletion: {after}"
    assert counts == before


@pytest.mark.asyncio
async def test_does_not_touch_a_different_students_data(db_session):
    await _seed_all_tables(db_session, "Emma")
    await _seed_all_tables(db_session, "Liam")

    await delete_all_student_data(db_session, "Emma")

    after_liam = await _row_counts_for(db_session, "Liam")
    assert all(n > 0 for n in after_liam.values())


@pytest.mark.asyncio
async def test_never_touches_sandbox_api_usage_rows_with_no_student(db_session):
    """ApiUsageEvent.student_name is nullable for parent-sandbox turns —
    deleting a real student must never sweep those up."""
    db_session.add(ApiUsageEvent(student_name=None, model="claude-haiku-4-5-20251001", input_tokens=5, output_tokens=5))
    await db_session.commit()

    await _seed_all_tables(db_session, "Emma")
    await delete_all_student_data(db_session, "Emma")

    result = await db_session.execute(select(ApiUsageEvent).where(ApiUsageEvent.student_name.is_(None)))
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_is_a_safe_no_op_for_a_student_with_no_data(db_session):
    counts = await delete_all_student_data(db_session, "Nobody")
    assert all(n == 0 for n in counts.values())


# ── DELETE /pod/configs/{student_name} route ──────────────────────────────────

@pytest.mark.asyncio
async def test_route_deletes_all_data_and_is_idempotent(db_session):
    await _seed_all_tables(db_session, "Emma")

    await delete_student_config("Emma", _fake_request(), _={"role": "parent"}, db=db_session)
    after = await _row_counts_for(db_session, "Emma")
    assert all(n == 0 for n in after.values())

    # Calling again for an already-deleted (or never-existed) student must
    # not raise — the end state (no data) is identical either way.
    await delete_student_config("Emma", _fake_request(), _={"role": "parent"}, db=db_session)
