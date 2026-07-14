"""
Real check for feeding the synthesized learner profile's processing_style
back into live tutoring (DITK-style structured drawing for kinesthetic
learners) — closes a real gap: the profile has always been synthesized
and shown to the parent (routers/narration.py), but nothing ever read it
back into Bede's own tutoring prompt before this. Mirrors
test_time_of_day.py's structure (unit tests for the note-builder, a
_build_subject_prompt wiring check, and an end-to-end stream_tutor_response
check) plus a real DB round trip for _load_processing_style_readonly
(test_facade_persisted.py's db_session fixture pattern).
"""

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
import pytest_asyncio
from anthropic.types import RawContentBlockDeltaEvent, RawContentBlockStartEvent, RawContentBlockStopEvent
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, LearnerProfile
from models.schemas import GradeStage, SessionConfig, Subject
from services import ai_service
from services.ai_service import (
    _build_subject_prompt,
    _load_processing_style_readonly,
    _processing_style_note,
)


def _config() -> SessionConfig:
    return SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery)


# ── _processing_style_note: pure function ────────────────────────────────────

def test_none_produces_no_note():
    assert _processing_style_note(None) == ""


@pytest.mark.parametrize("style", ["visual", "auditory", "reading_writing"])
def test_non_kinesthetic_styles_produce_no_note(style):
    """Deliberate: only kinesthetic gets an explicit nudge right now — see
    _processing_style_note's own docstring for why the other three aren't
    touched yet."""
    assert _processing_style_note(style) == ""


def test_kinesthetic_note_mentions_structured_drawing_across_subjects():
    note = _processing_style_note("kinesthetic")
    assert "kinesthetic" in note
    assert "invite_handwriting" in note
    assert "DITK" in note
    assert "not only nature study or" in note  # explicitly cross-subject, not science-only


# ── Wired into _build_subject_prompt ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_subject_prompt_includes_kinesthetic_note():
    prompt = await _build_subject_prompt(_config(), Subject.language_arts, processing_style="kinesthetic")
    assert "kinesthetic processing style" in prompt


@pytest.mark.asyncio
async def test_build_subject_prompt_omits_note_when_style_not_supplied():
    prompt = await _build_subject_prompt(_config(), Subject.language_arts)
    assert "kinesthetic" not in prompt.lower()


# ── _load_processing_style_readonly: real DB round trip ──────────────────────

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
async def test_returns_none_when_no_profile_exists_yet(db_session):
    assert await _load_processing_style_readonly(db_session, "Nobody") is None


@pytest.mark.asyncio
async def test_returns_the_stored_processing_style(db_session):
    from core.encryption import encrypt_json

    db_session.add(LearnerProfile(
        student_name="Ellie",
        session_count=4,
        profile_enc=encrypt_json({
            "trivium_stage": "logic",
            "processing_style": "kinesthetic",
            "narration_mode": "sequential",
            "attention_profile": "sustained",
            "session_count_assessed": 4,
            "bede_profile_notes": "",
            "assessed_at": "2026-01-01T00:00:00+00:00",
        }),
    ))
    await db_session.commit()

    assert await _load_processing_style_readonly(db_session, "Ellie") == "kinesthetic"


@pytest.mark.asyncio
async def test_corrupted_row_degrades_to_none_instead_of_raising(db_session):
    db_session.add(LearnerProfile(
        student_name="Zoe", session_count=3, profile_enc=b"not a valid SAGE envelope",
    ))
    await db_session.commit()

    assert await _load_processing_style_readonly(db_session, "Zoe") is None


# ── End-to-end: stream_tutor_response actually forwards processing_style ─────

class _FakeStream:
    def __init__(self, events):
        self._events = events

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        for event in self._events:
            yield event


def _text_events(text: str = "ok"):
    yield RawContentBlockStartEvent.model_validate(
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
    )
    yield RawContentBlockDeltaEvent.model_validate(
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}
    )
    yield RawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": 0})


def _capturing_stream(captured: dict):
    @asynccontextmanager
    async def _fake(**kwargs):
        captured["system"] = kwargs["system"]
        yield _FakeStream(list(_text_events()))
    return _fake


@pytest.mark.asyncio
async def test_stream_tutor_response_forwards_kinesthetic_style_into_the_prompt(db_session):
    from core.encryption import encrypt_json

    db_session.add(LearnerProfile(
        student_name="Sam",
        session_count=5,
        profile_enc=encrypt_json({
            "trivium_stage": "logic",
            "processing_style": "kinesthetic",
            "narration_mode": "sequential",
            "attention_profile": "sustained",
            "session_count_assessed": 5,
            "bede_profile_notes": "",
            "assessed_at": "2026-01-01T00:00:00+00:00",
        }),
    ))
    await db_session.commit()

    captured: dict = {}
    with patch.object(ai_service._client.messages, "stream", side_effect=_capturing_stream(captured)):
        async for _ in ai_service.stream_tutor_response(
            config=_config(),
            subject=Subject.language_arts,
            history=[],
            child_message="Let's talk about the story.",
            db=db_session,
        ):
            pass

    subject_block_text = captured["system"][1]["text"]
    assert "kinesthetic processing style" in subject_block_text


@pytest.mark.asyncio
async def test_stream_tutor_response_never_loads_processing_style_for_demo_sessions():
    """demo_code sessions have no LearnerProfile history at all — db is None
    there, so this must never attempt the load (and never crash for lacking
    a db to query)."""
    captured: dict = {}
    with patch.object(ai_service._client.messages, "stream", side_effect=_capturing_stream(captured)):
        async for _ in ai_service.stream_tutor_response(
            config=_config(),
            subject=Subject.language_arts,
            history=[],
            child_message="Hi Bede",
            demo_code="123456",
        ):
            pass

    subject_block_text = captured["system"][1]["text"]
    assert "kinesthetic" not in subject_block_text.lower()
