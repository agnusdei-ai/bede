"""Router-level tests for GET /diagnostic/{student_name}/plan.

Real in-memory SQLite via aiosqlite, same fixture as
test_diagnostic_parent_router.py — a real encrypted config written and read
back, not a mock, because the thing most likely to break here is the AAD
agreement between this route and routers/pod.py's own encryption.

The planner's rules are tested in tests/test_lesson_planner.py. This file
covers the seam: does the route load the right signals and hand back a plan
that still honours them.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, LessonBookmark, StudentConfig
from core.encryption import encrypt_json
from models.schemas import GradeStage, LessonResume, SessionConfig, Subject
from routers.diagnostic import get_session_plan
from routers.pod import _config_aad


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


async def _save_config(db, config: SessionConfig):
    db.add(
        StudentConfig(
            student_name=config.student_name,
            config_enc=encrypt_json(config.model_dump(mode="json"), _config_aad(config.student_name)),
        )
    )
    await db.commit()


async def _save_bookmark(db, student: str, subject: Subject, days_ago: float):
    db.add(
        LessonBookmark(
            student_name=student,
            subject=subject.value,
            bookmark_enc=encrypt_json({"note": "we stopped here"}),
            updated_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )
    )
    await db.commit()


def _config(**kwargs) -> SessionConfig:
    base = dict(
        student_name="Ada",
        grade="4",
        grade_stage=GradeStage.core_mastery,
        subjects=[Subject.history, Subject.mathematics, Subject.morning_time],
    )
    base.update(kwargs)
    return SessionConfig(**base)


@pytest.mark.asyncio
async def test_404s_for_a_student_with_no_config(db_session):
    with pytest.raises(HTTPException) as exc:
        await get_session_plan("Nobody", auth={}, db=db_session)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_returns_a_plan_over_the_parents_own_subjects(db_session):
    config = _config()
    await _save_config(db_session, config)

    result = await get_session_plan("Ada", auth={}, db=db_session)

    planned = [entry["subject"] for entry in result["subjects"]]
    assert sorted(planned) == sorted(s.value for s in config.subjects)
    assert result["student_name"] == "Ada"


@pytest.mark.asyncio
async def test_the_plan_is_advertised_as_advisory(db_session):
    """The route reports an ordering; it does not apply one. A client that
    silently rearranged a parent's day without saying so would be making a
    curriculum decision on their behalf."""
    await _save_config(db_session, _config())
    result = await get_session_plan("Ada", auth={}, db=db_session)
    assert result["advisory"] is True


@pytest.mark.asyncio
async def test_every_entry_carries_a_reason(db_session):
    await _save_config(db_session, _config())
    result = await get_session_plan("Ada", auth={}, db=db_session)
    assert all(entry["reason"].strip() for entry in result["subjects"])


@pytest.mark.asyncio
async def test_morning_time_leads(db_session):
    await _save_config(db_session, _config())
    result = await get_session_plan("Ada", auth={}, db=db_session)
    assert result["subjects"][0]["subject"] == Subject.morning_time.value


@pytest.mark.asyncio
async def test_a_parents_resume_note_is_read_from_the_stored_config(db_session):
    """The seam most worth testing: the note is written by routers/pod.py,
    encrypted, and has to survive the round trip into a planning signal."""
    await _save_config(
        db_session,
        _config(
            lesson_resume=[
                LessonResume(subject=Subject.history, stopped_at="the fall of Rome")
            ]
        ),
    )
    result = await get_session_plan("Ada", auth={}, db=db_session)

    # history is ordinary; a resume note should lift it above demanding maths.
    after_morning_time = [e["subject"] for e in result["subjects"]][1:]
    assert after_morning_time[0] == Subject.history.value


@pytest.mark.asyncio
async def test_a_stale_bookmark_makes_a_subject_stale(db_session):
    await _save_config(
        db_session,
        _config(subjects=[Subject.art_music, Subject.history]),
    )
    await _save_bookmark(db_session, "Ada", Subject.art_music, days_ago=1)
    await _save_bookmark(db_session, "Ada", Subject.history, days_ago=40)

    result = await get_session_plan("Ada", auth={}, db=db_session)
    assert result["subjects"][0]["subject"] == Subject.history.value


@pytest.mark.asyncio
async def test_a_bookmark_for_an_unknown_subject_is_ignored_not_fatal(db_session):
    """A subject removed from the enum leaves rows behind. That is not a
    signal, and it is certainly not a reason to fail a parent's request."""
    await _save_config(db_session, _config())
    db_session.add(
        LessonBookmark(
            student_name="Ada",
            subject="astrology",
            bookmark_enc=encrypt_json({"note": "n/a"}),
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    result = await get_session_plan("Ada", auth={}, db=db_session)
    assert len(result["subjects"]) == 3


@pytest.mark.asyncio
async def test_faith_subjects_are_not_reordered_by_staleness(db_session):
    """The constitutional rule, verified through the real route rather than
    only against the pure function: a long-untouched Scripture block must not
    be promoted, because that is a measurement of spiritual engagement
    expressed as a timetable."""
    await _save_config(
        db_session,
        _config(subjects=[Subject.history, Subject.scripture, Subject.science]),
    )
    await _save_bookmark(db_session, "Ada", Subject.scripture, days_ago=200)

    result = await get_session_plan("Ada", auth={}, db=db_session)
    assert [e["subject"] for e in result["subjects"]] == [
        Subject.history.value,
        Subject.scripture.value,
        Subject.science.value,
    ]
