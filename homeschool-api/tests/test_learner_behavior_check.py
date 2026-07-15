"""
Tests for LearnerBehaviorCheck (core/database.py) — the minimal,
parent-only observation on whether Bede's kinesthetic-processing_style
prompt nudge actually changes its own behavior (more invite_handwriting
calls), not a claim that the label itself improves learning. Covers:

  - routers/narration.py's _sync_behavior_check row lifecycle (create on
    newly-kinesthetic, leave alone while still kinesthetic, delete once no
    longer kinesthetic)
  - GET /narration/{student}/behavior-check
  - services/ai_service.py's _record_handwriting_invite increment
  - end-to-end: an invite_handwriting tool call during a real
    stream_tutor_response turn actually increments the row when (and only
    when) the student is currently profiled kinesthetic
"""
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from anthropic.types import RawContentBlockDeltaEvent, RawContentBlockStartEvent, RawContentBlockStopEvent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, LearnerBehaviorCheck
from models.schemas import GradeStage, SessionConfig, Subject
from routers.narration import _sync_behavior_check, get_behavior_check
from services import ai_service
from services.ai_service import _record_handwriting_invite


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


async def _get_row(db_session, student_name):
    result = await db_session.execute(
        select(LearnerBehaviorCheck).where(LearnerBehaviorCheck.student_name == student_name)
    )
    return result.scalar_one_or_none()


# ── _sync_behavior_check row lifecycle ────────────────────────────────────────

@pytest.mark.asyncio
async def test_newly_kinesthetic_creates_a_fresh_row(db_session):
    await _sync_behavior_check(db_session, "Nora", old_style=None, new_style="kinesthetic")
    await db_session.commit()

    row = await _get_row(db_session, "Nora")
    assert row is not None
    from core.encryption import decrypt_json
    assert decrypt_json(row.count_enc)["invite_handwriting_count"] == 0


@pytest.mark.asyncio
async def test_still_kinesthetic_leaves_existing_row_untouched(db_session):
    await _sync_behavior_check(db_session, "Priya", old_style=None, new_style="kinesthetic")
    await db_session.commit()
    await _record_handwriting_invite(db_session, "Priya")  # count -> 1

    await _sync_behavior_check(db_session, "Priya", old_style="kinesthetic", new_style="kinesthetic")
    await db_session.commit()

    row = await _get_row(db_session, "Priya")
    from core.encryption import decrypt_json
    assert decrypt_json(row.count_enc)["invite_handwriting_count"] == 1  # NOT reset


@pytest.mark.asyncio
async def test_no_longer_kinesthetic_deletes_the_row(db_session):
    await _sync_behavior_check(db_session, "Theo", old_style=None, new_style="kinesthetic")
    await db_session.commit()
    assert await _get_row(db_session, "Theo") is not None

    await _sync_behavior_check(db_session, "Theo", old_style="kinesthetic", new_style="visual")
    await db_session.commit()
    assert await _get_row(db_session, "Theo") is None


@pytest.mark.asyncio
async def test_never_kinesthetic_creates_no_row(db_session):
    await _sync_behavior_check(db_session, "Zane", old_style=None, new_style="auditory")
    await db_session.commit()
    assert await _get_row(db_session, "Zane") is None


# ── GET /narration/{student}/behavior-check ───────────────────────────────────

@pytest.mark.asyncio
async def test_route_returns_none_when_not_currently_kinesthetic(db_session):
    result = await get_behavior_check("Nobody", _={"role": "parent"}, db=db_session)
    assert result is None


@pytest.mark.asyncio
async def test_route_returns_the_observation_when_present(db_session):
    await _sync_behavior_check(db_session, "Ellie", old_style=None, new_style="kinesthetic")
    await db_session.commit()
    await _record_handwriting_invite(db_session, "Ellie")
    await _record_handwriting_invite(db_session, "Ellie")

    result = await get_behavior_check("Ellie", _={"role": "parent"}, db=db_session)
    assert result["invite_handwriting_count"] == 2
    assert "since" in result


# ── _record_handwriting_invite ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_increment_is_a_no_op_without_a_db():
    await _record_handwriting_invite(None, "Anyone")  # must not raise


@pytest.mark.asyncio
async def test_increment_is_a_no_op_when_no_row_exists_yet(db_session):
    await _record_handwriting_invite(db_session, "NeverProfiled")  # must not raise, no row created
    assert await _get_row(db_session, "NeverProfiled") is None


# ── End-to-end: stream_tutor_response actually increments on invite_handwriting ──

def _config() -> SessionConfig:
    return SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery)


def _invite_handwriting_events():
    yield RawContentBlockStartEvent.model_validate({
        "type": "content_block_start", "index": 0,
        "content_block": {"type": "tool_use", "id": "t1", "name": "invite_handwriting", "input": {}},
    })
    yield RawContentBlockDeltaEvent.model_validate({
        "type": "content_block_delta", "index": 0,
        "delta": {"type": "input_json_delta", "partial_json": '{"prompt": "Draw the water cycle"}'},
    })
    yield RawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": 0})


class _FakeStream:
    def __init__(self, events):
        self._events = events

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        for event in self._events:
            yield event


def _fake_stream_cm():
    @asynccontextmanager
    async def _fake(**kwargs):
        yield _FakeStream(list(_invite_handwriting_events()))
    return _fake


@pytest.mark.asyncio
async def test_invite_handwriting_increments_count_for_a_kinesthetic_student(db_session):
    from unittest.mock import patch

    await _sync_behavior_check(db_session, "Sam", old_style=None, new_style="kinesthetic")
    await db_session.commit()

    from core.database import LearnerProfile
    from core.encryption import encrypt_json
    db_session.add(LearnerProfile(
        student_name="Sam", session_count=4,
        profile_enc=encrypt_json({
            "trivium_stage": "logic", "processing_style": "kinesthetic",
            "narration_mode": "sequential", "attention_profile": "sustained",
            "session_count_assessed": 4, "bede_profile_notes": "",
            "assessed_at": "2026-01-01T00:00:00+00:00",
        }),
    ))
    await db_session.commit()

    with patch.object(ai_service._client.messages, "stream", side_effect=_fake_stream_cm()):
        async for _ in ai_service.stream_tutor_response(
            config=_config(), subject=Subject.science, history=[],
            child_message="Tell me about the water cycle", db=db_session,
        ):
            pass

    row = await _get_row(db_session, "Sam")
    from core.encryption import decrypt_json
    assert decrypt_json(row.count_enc)["invite_handwriting_count"] == 1


@pytest.mark.asyncio
async def test_invite_handwriting_does_not_touch_the_count_for_a_non_kinesthetic_student(db_session):
    from unittest.mock import patch

    from core.database import LearnerProfile
    from core.encryption import encrypt_json
    db_session.add(LearnerProfile(
        student_name="Wren", session_count=4,
        profile_enc=encrypt_json({
            "trivium_stage": "logic", "processing_style": "visual",
            "narration_mode": "sequential", "attention_profile": "sustained",
            "session_count_assessed": 4, "bede_profile_notes": "",
            "assessed_at": "2026-01-01T00:00:00+00:00",
        }),
    ))
    await db_session.commit()

    with patch.object(ai_service._client.messages, "stream", side_effect=_fake_stream_cm()):
        async for _ in ai_service.stream_tutor_response(
            config=SessionConfig(student_name="Wren", grade="4", grade_stage=GradeStage.core_mastery),
            subject=Subject.science, history=[],
            child_message="Tell me about the water cycle", db=db_session,
        ):
            pass

    assert await _get_row(db_session, "Wren") is None  # never created, never touched
