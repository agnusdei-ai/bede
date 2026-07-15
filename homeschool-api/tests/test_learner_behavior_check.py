"""
Tests for LearnerBehaviorCheck (core/database.py) — the minimal,
parent-only observation on whether Bede's own processing_style prompt
nudges actually change its behavior, not a claim that any of these labels
improve learning. Covers three TRACKABLE_STYLES (routers/narration.py):
kinesthetic (invite_handwriting WITH elements), reading_writing
(invite_handwriting WITHOUT elements — same tool as kinesthetic,
disambiguated by that field), and visual (a successfully-resolved
show_visual_aid call). auditory gets a prompt nudge only, no counter.

  - routers/narration.py's _sync_behavior_check row lifecycle (create on
    newly-trackable, leave alone while the SAME trackable style persists,
    reset when switching between two DIFFERENT trackable styles, delete
    once no longer any trackable style)
  - GET /narration/{student}/behavior-check
  - services/ai_service.py's _increment_behavior_check
  - end-to-end: real stream_tutor_response turns confirm each signal only
    increments for its own matching style + tool-call shape
"""
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from anthropic.types import RawContentBlockDeltaEvent, RawContentBlockStartEvent, RawContentBlockStopEvent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, LearnerBehaviorCheck, LearnerProfile
from core.encryption import decrypt_json, encrypt_json
from models.schemas import GradeStage, SessionConfig, Subject
from routers.narration import _sync_behavior_check, get_behavior_check
from services import ai_service
from services.ai_service import _increment_behavior_check


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


async def _count(db_session, student_name) -> int:
    row = await _get_row(db_session, student_name)
    return decrypt_json(row.count_enc)["count"]


def _profile(student_name: str, processing_style: str, session_count: int = 4):
    return LearnerProfile(
        student_name=student_name, session_count=session_count,
        profile_enc=encrypt_json({
            "trivium_stage": "logic", "processing_style": processing_style,
            "narration_mode": "sequential", "attention_profile": "sustained",
            "session_count_assessed": session_count, "bede_profile_notes": "",
            "assessed_at": "2026-01-01T00:00:00+00:00",
        }),
    )


# ── _sync_behavior_check row lifecycle ────────────────────────────────────────

@pytest.mark.parametrize("style", ["kinesthetic", "reading_writing", "visual"])
@pytest.mark.asyncio
async def test_newly_trackable_creates_a_fresh_row(db_session, style):
    await _sync_behavior_check(db_session, "Nora", old_style=None, new_style=style)
    await db_session.commit()

    assert await _count(db_session, "Nora") == 0


@pytest.mark.parametrize("style", ["kinesthetic", "reading_writing", "visual"])
@pytest.mark.asyncio
async def test_same_trackable_style_leaves_existing_row_untouched(db_session, style):
    await _sync_behavior_check(db_session, "Priya", old_style=None, new_style=style)
    await db_session.commit()
    await _increment_behavior_check(db_session, "Priya")  # count -> 1

    await _sync_behavior_check(db_session, "Priya", old_style=style, new_style=style)
    await db_session.commit()

    assert await _count(db_session, "Priya") == 1  # NOT reset


@pytest.mark.asyncio
async def test_switching_between_two_trackable_styles_resets_the_count(db_session):
    """The count means a different thing per style — it must not silently
    carry over just because both kinesthetic and visual use
    LearnerBehaviorCheck."""
    await _sync_behavior_check(db_session, "Omar", old_style=None, new_style="kinesthetic")
    await db_session.commit()
    await _increment_behavior_check(db_session, "Omar")
    await _increment_behavior_check(db_session, "Omar")
    assert await _count(db_session, "Omar") == 2

    await _sync_behavior_check(db_session, "Omar", old_style="kinesthetic", new_style="visual")
    await db_session.commit()
    assert await _count(db_session, "Omar") == 0


@pytest.mark.asyncio
async def test_no_longer_trackable_deletes_the_row(db_session):
    await _sync_behavior_check(db_session, "Theo", old_style=None, new_style="kinesthetic")
    await db_session.commit()
    assert await _get_row(db_session, "Theo") is not None

    await _sync_behavior_check(db_session, "Theo", old_style="kinesthetic", new_style="auditory")
    await db_session.commit()
    assert await _get_row(db_session, "Theo") is None


@pytest.mark.asyncio
async def test_never_trackable_creates_no_row(db_session):
    await _sync_behavior_check(db_session, "Zane", old_style=None, new_style="auditory")
    await db_session.commit()
    assert await _get_row(db_session, "Zane") is None


# ── GET /narration/{student}/behavior-check ───────────────────────────────────

@pytest.mark.asyncio
async def test_route_returns_none_when_not_currently_trackable(db_session):
    result = await get_behavior_check("Nobody", _={"role": "parent"}, db=db_session)
    assert result is None


@pytest.mark.asyncio
async def test_route_returns_the_observation_when_present(db_session):
    await _sync_behavior_check(db_session, "Ellie", old_style=None, new_style="visual")
    await db_session.commit()
    await _increment_behavior_check(db_session, "Ellie")
    await _increment_behavior_check(db_session, "Ellie")

    result = await get_behavior_check("Ellie", _={"role": "parent"}, db=db_session)
    assert result["count"] == 2
    assert "since" in result


# ── _increment_behavior_check ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_increment_is_a_no_op_without_a_db():
    await _increment_behavior_check(None, "Anyone")  # must not raise


@pytest.mark.asyncio
async def test_increment_is_a_no_op_when_no_row_exists_yet(db_session):
    await _increment_behavior_check(db_session, "NeverProfiled")  # must not raise, no row created
    assert await _get_row(db_session, "NeverProfiled") is None


# ── End-to-end: stream_tutor_response's three signal call sites ──────────────

def _config(name: str = "Sam") -> SessionConfig:
    return SessionConfig(student_name=name, grade="4", grade_stage=GradeStage.core_mastery)


def _tool_use_events(tool_name: str, tool_input: dict):
    import json as _json
    yield RawContentBlockStartEvent.model_validate({
        "type": "content_block_start", "index": 0,
        "content_block": {"type": "tool_use", "id": "t1", "name": tool_name, "input": {}},
    })
    yield RawContentBlockDeltaEvent.model_validate({
        "type": "content_block_delta", "index": 0,
        "delta": {"type": "input_json_delta", "partial_json": _json.dumps(tool_input)},
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


def _fake_stream_cm(tool_name: str, tool_input: dict):
    @asynccontextmanager
    async def _fake(**kwargs):
        yield _FakeStream(list(_tool_use_events(tool_name, tool_input)))
    return _fake


async def _run_turn(db_session, student_name, subject, tool_name, tool_input):
    from unittest.mock import patch

    with patch.object(ai_service._client.messages, "stream", side_effect=_fake_stream_cm(tool_name, tool_input)):
        async for _ in ai_service.stream_tutor_response(
            config=_config(student_name), subject=subject, history=[],
            child_message="hello", db=db_session,
        ):
            pass


@pytest.mark.asyncio
async def test_kinesthetic_signal_requires_elements_set(db_session):
    db_session.add(_profile("Sam", "kinesthetic"))
    await _sync_behavior_check(db_session, "Sam", old_style=None, new_style="kinesthetic")
    await db_session.commit()

    await _run_turn(db_session, "Sam", Subject.science, "invite_handwriting",
                     {"prompt": "Draw it", "elements": ["petal", "stem"]})
    assert await _count(db_session, "Sam") == 1


@pytest.mark.asyncio
async def test_kinesthetic_signal_does_not_count_a_freeform_invite(db_session):
    db_session.add(_profile("Sam", "kinesthetic"))
    await _sync_behavior_check(db_session, "Sam", old_style=None, new_style="kinesthetic")
    await db_session.commit()

    await _run_turn(db_session, "Sam", Subject.science, "invite_handwriting", {"prompt": "Draw it"})
    assert await _count(db_session, "Sam") == 0


@pytest.mark.asyncio
async def test_reading_writing_signal_requires_no_elements(db_session):
    db_session.add(_profile("Sam", "reading_writing"))
    await _sync_behavior_check(db_session, "Sam", old_style=None, new_style="reading_writing")
    await db_session.commit()

    await _run_turn(db_session, "Sam", Subject.language_arts, "invite_handwriting", {"prompt": "Write it out"})
    assert await _count(db_session, "Sam") == 1


@pytest.mark.asyncio
async def test_reading_writing_signal_does_not_count_a_structured_invite(db_session):
    db_session.add(_profile("Sam", "reading_writing"))
    await _sync_behavior_check(db_session, "Sam", old_style=None, new_style="reading_writing")
    await db_session.commit()

    await _run_turn(db_session, "Sam", Subject.language_arts, "invite_handwriting",
                     {"prompt": "Draw it", "elements": ["thesis", "evidence"]})
    assert await _count(db_session, "Sam") == 0


@pytest.mark.asyncio
async def test_visual_signal_counts_a_resolved_visual_aid(db_session, monkeypatch):
    db_session.add(_profile("Sam", "visual"))
    await _sync_behavior_check(db_session, "Sam", old_style=None, new_style="visual")
    await db_session.commit()
    monkeypatch.setattr(
        ai_service, "_lookup_visual_aid",
        lambda aid_id: {"id": aid_id, "title": "t", "creator": "", "year": "",
                         "wiki_title": "t", "description": "d", "category": "picture_study"},
    )

    await _run_turn(db_session, "Sam", Subject.art_music, "show_visual_aid", {"visual_aid_id": "starry_night"})
    assert await _count(db_session, "Sam") == 1


@pytest.mark.asyncio
async def test_visual_signal_does_not_count_an_unresolved_visual_aid(db_session, monkeypatch):
    db_session.add(_profile("Sam", "visual"))
    await _sync_behavior_check(db_session, "Sam", old_style=None, new_style="visual")
    await db_session.commit()
    monkeypatch.setattr(ai_service, "_lookup_visual_aid", lambda aid_id: None)

    await _run_turn(db_session, "Sam", Subject.art_music, "show_visual_aid", {"visual_aid_id": "not_a_real_id"})
    assert await _count(db_session, "Sam") == 0


@pytest.mark.asyncio
async def test_auditory_profile_never_gets_a_row_even_after_tool_calls(db_session):
    db_session.add(_profile("Wren", "auditory"))
    await db_session.commit()  # no _sync_behavior_check call — auditory never creates a row

    await _run_turn(db_session, "Wren", Subject.science, "invite_handwriting",
                     {"prompt": "Draw it", "elements": ["a", "b"]})
    assert await _get_row(db_session, "Wren") is None
