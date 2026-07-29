"""
Lesson continuity: a student picking a subject back up from where they
left off, instead of restarting cold, without the parent having to retype
lesson_focus/current_unit every day. See core/database.py's LessonBookmark
and CLAUDE.md's "Lesson continuity (bookmarks)" section for the full
design. Mirrors test_processing_style.py's structure: pure-function tests
for the note builder, a _build_subject_prompt wiring check, a real DB
round trip + caching check for the readonly loader, the write-side parse
of generate_session_summary's trailing block, and an end-to-end
stream_tutor_response check.
"""

from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
import pytest_asyncio
from anthropic.types import RawContentBlockDeltaEvent, RawContentBlockStartEvent, RawContentBlockStopEvent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, LessonBookmark
from models.schemas import GradeStage, SessionConfig, Subject
from services import ai_service
from services.ai_service import (
    _bookmark_note,
    _build_subject_prompt,
    _load_lesson_bookmark_readonly,
    _persist_lesson_bookmarks,
    _split_bookmarks_block,
)


def _config() -> SessionConfig:
    return SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery)


# ── _bookmark_note: pure function ─────────────────────────────────────────────

def test_none_produces_no_note():
    assert _bookmark_note(None) == ""


def test_empty_note_string_produces_no_note():
    assert _bookmark_note({"note": "", "updated_at": datetime.now(timezone.utc)}) == ""


def test_recent_bookmark_says_last_time():
    note = _bookmark_note({"note": "We were on the fall of Rome.", "updated_at": datetime.now(timezone.utc)})
    assert "last time" in note
    assert "a while back" not in note
    assert "fall of Rome" in note


def test_stale_bookmark_fades_to_a_while_back():
    old = datetime.now(timezone.utc) - timedelta(days=30)
    note = _bookmark_note({"note": "We were on fractions.", "updated_at": old})
    assert "a while back" in note
    assert "last time" not in note


def test_boundary_just_under_two_weeks_still_says_last_time():
    recent = datetime.now(timezone.utc) - timedelta(days=13)
    note = _bookmark_note({"note": "We were on fractions.", "updated_at": recent})
    assert "last time" in note


# ── Wired into _build_subject_prompt, and outranked by the parent's own note ──

@pytest.mark.asyncio
async def test_build_subject_prompt_includes_bookmark_note():
    prompt = await _build_subject_prompt(
        _config(), Subject.history,
        bookmark={"note": "We were partway through the fall of Rome.", "updated_at": datetime.now(timezone.utc)},
    )
    assert "fall of Rome" in prompt


@pytest.mark.asyncio
async def test_build_subject_prompt_omits_note_when_no_bookmark():
    prompt = await _build_subject_prompt(_config(), Subject.history)
    assert "left off" not in prompt.lower()


@pytest.mark.asyncio
async def test_opener_rule_defers_to_parents_note_when_both_present():
    """A parent-typed lesson_focus/current_unit is a deliberate redirect —
    the static-prompt opener rule must say so, not just the subject block
    silently include both notes."""
    prompt = ai_service._build_static_prompt(_config())
    assert "parent's own note for today or current unit of study points somewhere else" in prompt


# ── _split_bookmarks_block: parsing the model's trailing internal block ──────

def test_splits_summary_text_from_bookmarks_block():
    raw = (
        "1. **Session Highlights**\n- did great\n\n"
        '<<<BOOKMARKS>>>\n{"history": "Left off at the fall of Rome."}\n<<<END_BOOKMARKS>>>'
    )
    summary, bookmarks = _split_bookmarks_block(raw)
    assert "BOOKMARKS" not in summary
    assert "did great" in summary
    assert bookmarks == {"history": "Left off at the fall of Rome."}


def test_missing_block_returns_full_text_and_empty_dict():
    raw = "1. **Session Highlights**\n- did great"
    summary, bookmarks = _split_bookmarks_block(raw)
    assert summary == raw
    assert bookmarks == {}


def test_malformed_json_degrades_to_empty_dict_without_raising():
    raw = "Summary text\n<<<BOOKMARKS>>>\nnot json at all\n<<<END_BOOKMARKS>>>"
    summary, bookmarks = _split_bookmarks_block(raw)
    assert "Summary text" in summary
    assert bookmarks == {}


def test_non_string_values_are_dropped():
    raw = 'Summary\n<<<BOOKMARKS>>>\n{"history": "ok note", "mathematics": 42}\n<<<END_BOOKMARKS>>>'
    _, bookmarks = _split_bookmarks_block(raw)
    assert bookmarks == {"history": "ok note"}


# ── Real DB round trip: readonly load, persistence, caching ──────────────────

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
async def test_returns_none_when_no_bookmark_exists_yet(db_session):
    assert await _load_lesson_bookmark_readonly(db_session, "Nobody", Subject.history) is None


@pytest.mark.asyncio
async def test_persist_then_read_back(db_session):
    await _persist_lesson_bookmarks(db_session, "Ellie", {"history": "Left off at the fall of Rome."})

    loaded = await _load_lesson_bookmark_readonly(db_session, "Ellie", Subject.history)
    assert loaded["note"] == "Left off at the fall of Rome."


@pytest.mark.asyncio
async def test_persist_is_scoped_per_subject(db_session):
    await _persist_lesson_bookmarks(db_session, "Ellie", {"history": "Rome note."})
    assert await _load_lesson_bookmark_readonly(db_session, "Ellie", Subject.mathematics) is None


@pytest.mark.asyncio
async def test_persist_upserts_rather_than_duplicating(db_session):
    await _persist_lesson_bookmarks(db_session, "Ellie", {"history": "First note."})
    await _persist_lesson_bookmarks(db_session, "Ellie", {"history": "Updated note."})

    loaded = await _load_lesson_bookmark_readonly(db_session, "Ellie", Subject.history)
    assert loaded["note"] == "Updated note."


@pytest.mark.asyncio
async def test_persist_ignores_invented_subject_keys(db_session):
    await _persist_lesson_bookmarks(db_session, "Ellie", {"not_a_real_subject": "should be dropped"})
    result = await db_session.execute(
        select(LessonBookmark).where(LessonBookmark.student_name == "Ellie")
    )
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_corrupted_row_degrades_to_none_instead_of_raising(db_session):
    db_session.add(LessonBookmark(student_name="Zoe", subject="history", bookmark_enc=b"not a valid SAGE envelope"))
    await db_session.commit()

    assert await _load_lesson_bookmark_readonly(db_session, "Zoe", Subject.history) is None


@pytest.mark.asyncio
async def test_second_call_within_ttl_does_not_hit_the_db_again(db_session):
    await _persist_lesson_bookmarks(db_session, "Nora", {"history": "Original note."})
    assert (await _load_lesson_bookmark_readonly(db_session, "Nora", Subject.history))["note"] == "Original note."

    await db_session.delete((await db_session.get(LessonBookmark, ("Nora", "history"))))
    await db_session.commit()

    # Row deleted — a second call that actually re-queried would now see
    # nothing. Getting the original value back proves it came from cache.
    assert (await _load_lesson_bookmark_readonly(db_session, "Nora", Subject.history))["note"] == "Original note."


@pytest.mark.asyncio
async def test_persisting_invalidates_the_cache():
    """_persist_lesson_bookmarks clears the module cache outright — a fresh
    end-of-session write must be visible to the very next session's opener,
    not served stale for up to _READONLY_PROMPT_CACHE_TTL_SECONDS."""
    ai_service._lesson_bookmark_cache[("Priya", "history")] = ({"note": "stale", "updated_at": datetime.now(timezone.utc)}, 1e18)
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        from core.encryption import initialize_encryption
        await initialize_encryption(settings.master_secret, session)
        await _persist_lesson_bookmarks(session, "Priya", {"history": "fresh note"})

        assert ("Priya", "history") not in ai_service._lesson_bookmark_cache
        assert (await _load_lesson_bookmark_readonly(session, "Priya", Subject.history))["note"] == "fresh note"
    await engine.dispose()


# ── End-to-end: stream_tutor_response actually forwards the bookmark ─────────

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
async def test_stream_tutor_response_forwards_bookmark_into_the_prompt(db_session):
    await _persist_lesson_bookmarks(db_session, "Sam", {"language_arts": "We were discussing the story's climax."})

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
    assert "story's climax" in subject_block_text


@pytest.mark.asyncio
async def test_stream_tutor_response_never_loads_bookmark_for_demo_sessions():
    """demo_code sessions have no LessonBookmark history at all — db is
    None there, so this must never attempt the load."""
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
    assert "left off" not in subject_block_text.lower()
