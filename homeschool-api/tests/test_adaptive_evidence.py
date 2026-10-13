"""Actual persistence and invocation checks for governed teaching observations."""
import inspect
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from anthropic.types import (
    RawContentBlockStartEvent, RawContentBlockDeltaEvent, RawContentBlockStopEvent,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, AdaptiveInstructionTrace
from core.deps import require_parent
from models.schemas import GradeStage, SessionConfig, Subject
from routers.diagnostic import get_adaptive_recommendation_history
from services import ai_service
from services.adaptive_learning import load_recent_math_work, select_instruction
from services.adaptive_evidence import (
    parent_recommendation_history, recommendation_fingerprint,
    record_prompt_recommendation,
)
from services.diagnostic.activity import record_activity

SKILL = "oa.multiplication_facts"


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        from core.encryption import initialize_encryption
        await initialize_encryption(settings.master_secret, session)
        yield session
    await engine.dispose()


async def _decision(db, student="Sam"):
    assert await record_activity(
        db, student, "mathematics", SKILL, "Multiplication facts", "hint_dependent",
    )
    work = await load_recent_math_work(db, student)
    result = select_instruction(work, "3-5")
    assert result is not None
    return result


@pytest.mark.asyncio
async def test_recommendation_is_encrypted_student_scoped_and_deduplicated(db_session):
    selected = await _decision(db_session)
    assert await record_prompt_recommendation(db_session, "Sam", selected, parent_focus=True)
    assert not await record_prompt_recommendation(db_session, "Sam", selected, parent_focus=True)

    rows = (await db_session.execute(select(AdaptiveInstructionTrace))).scalars().all()
    assert len(rows) == 1
    assert rows[0].student_name == "Sam"
    assert rows[0].fingerprint == recommendation_fingerprint(selected)
    assert b"Sam" not in rows[0].detail_enc
    assert b"smaller_step" not in rows[0].detail_enc

    mine = await parent_recommendation_history(db_session, "Sam")
    theirs = await parent_recommendation_history(db_session, "Another Student")
    assert len(mine["recommendations"]) == 1
    assert theirs["recommendations"] == []
    assert mine["recommendations"][0]["parent_focus"] is True
    assert mine["recommendations"][0]["status"] == "recommended_in_prompt"
    assert mine["recommendations"][0]["later_completed_work"] is None


@pytest.mark.asyncio
async def test_later_work_is_observed_but_not_claimed_as_effectiveness(db_session):
    selected = await _decision(db_session)
    assert await record_prompt_recommendation(db_session, "Sam", selected, parent_focus=False)
    assert await record_activity(
        db_session, "Sam", "mathematics", SKILL, "Multiplication facts", "correct",
    )
    history = await parent_recommendation_history(db_session, "Sam")
    assert len(history["recommendations"]) == 1
    recommendation = history["recommendations"][0]
    observed = recommendation["later_completed_work"]
    assert observed is not None
    assert observed["assistance"] == "unaided"
    assert observed["activity_id"] not in recommendation["source_activity_ids"]
    assert "not proven delivered interventions" in history["interpretation"]
    assert "not evidence that the recommendation caused learning" in history["interpretation"]
    assert "score" not in history


@pytest.mark.asyncio
async def test_new_evidence_gets_new_trace_with_source_ids(db_session):
    first = await _decision(db_session)
    assert await record_prompt_recommendation(db_session, "Sam", first, parent_focus=False)
    await record_activity(db_session, "Sam", "mathematics", SKILL, "Multiplication facts", "correct")
    second = select_instruction(await load_recent_math_work(db_session, "Sam"), "3-5")
    assert second is not None
    assert recommendation_fingerprint(first) != recommendation_fingerprint(second)
    assert await record_prompt_recommendation(db_session, "Sam", second, parent_focus=False)
    rows = (await db_session.execute(select(AdaptiveInstructionTrace))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_tampering_with_ciphertext_is_not_presented_as_learning_evidence(db_session):
    selected = await _decision(db_session)
    assert await record_prompt_recommendation(db_session, "Sam", selected, parent_focus=False)
    row = (await db_session.execute(select(AdaptiveInstructionTrace))).scalar_one()
    row.detail_enc = b"tampered"
    await db_session.commit()
    report = await parent_recommendation_history(db_session, "Sam")
    assert report["recommendations"] == []


def test_parent_only_endpoint_has_the_real_auth_guard():
    from fastapi.params import Depends
    default = inspect.signature(get_adaptive_recommendation_history).parameters["auth"].default
    assert isinstance(default, Depends)
    assert default.dependency is require_parent


class _FakeStream:
    def __aiter__(self):
        return self._events()

    async def _events(self):
        yield RawContentBlockStartEvent.model_validate({
            "type": "content_block_start", "index": 0,
            "content_block": {"type": "text", "text": ""},
        })
        yield RawContentBlockDeltaEvent.model_validate({
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": "What do you notice?"},
        })
        yield RawContentBlockStopEvent.model_validate({
            "type": "content_block_stop", "index": 0,
        })


def _capture_stream(captured):
    @asynccontextmanager
    async def fake(**kwargs):
        captured["system"] = kwargs["system"]
        yield _FakeStream()
    return fake


@pytest.mark.asyncio
async def test_real_tutor_invocation_records_recommendation(db_session):
    await _decision(db_session)
    config = SessionConfig(
        student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery,
    )
    captured = {}
    with patch.object(ai_service._client.messages, "stream", side_effect=_capture_stream(captured)):
        async for _ in ai_service.stream_tutor_response(
            config=config, subject=Subject.mathematics,
            history=[], child_message="How does multiplication work?",
            db=db_session,
        ):
            pass
    assert "<adaptive_learning_policy>" in captured["system"][1]["text"]
    report = await parent_recommendation_history(db_session, "Sam")
    assert len(report["recommendations"]) == 1

    # Calling again without NEW completed work must not create duplicate
    # records, even though the model is correctly given the same guidance.
    with patch.object(ai_service._client.messages, "stream", side_effect=_capture_stream(captured)):
        async for _ in ai_service.stream_tutor_response(
            config=config, subject=Subject.mathematics,
            history=[], child_message="Could you show another way?",
            db=db_session,
        ):
            pass
    report = await parent_recommendation_history(db_session, "Sam")
    assert len(report["recommendations"]) == 1


@pytest.mark.asyncio
async def test_public_demo_does_not_persist_adaptive_history(db_session):
    config = SessionConfig(
        student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery,
    )
    captured = {}
    with patch.object(ai_service._client.messages, "stream", side_effect=_capture_stream(captured)):
        async for _ in ai_service.stream_tutor_response(
            config=config, subject=Subject.mathematics,
            history=[], child_message="Hello", db=None,
        ):
            pass
    rows = (await db_session.execute(select(AdaptiveInstructionTrace))).scalars().all()
    assert rows == []
