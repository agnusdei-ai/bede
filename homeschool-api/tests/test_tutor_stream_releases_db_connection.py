"""A tutoring turn must not hold a pool connection while it waits on the model.

The capacity run (docs/CAPACITY.md) failed at ten children on the default
pool of 5 + 5: each turn kept its request's connection idle through the whole
streamed reply. `core.database.release_idle_connection` ends a transaction
with nothing pending, and is called before the moderation check
(`routers/tutor.py`) and before every model round (`stream_tutor_response`).
These tests check the helper, both call sites, and that it never commits a
staged write early.
"""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from anthropic.types import RawContentBlockDeltaEvent, RawContentBlockStartEvent, RawContentBlockStopEvent
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import Base, LessonBookmark, release_idle_connection
from models.schemas import GradeStage, SessionConfig, Subject
from services import ai_service


@pytest_asyncio.fixture
async def session(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pool.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_session_that_has_queried_holds_a_connection_until_released(session):
    await session.execute(text("SELECT 1"))
    assert session.in_transaction()
    assert await release_idle_connection(session) is True
    assert not session.in_transaction()
    # The session still works: its next query checks a connection out again.
    await session.execute(text("SELECT 1"))
    assert session.in_transaction()


@pytest.mark.asyncio
async def test_a_staged_write_is_never_committed_early(session):
    session.add(LessonBookmark(student_name="Sam", subject="math", bookmark_enc=b"x"))
    assert await release_idle_connection(session) is False
    assert session.in_transaction()
    await session.rollback()
    rows = (await session.execute(select(LessonBookmark))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_nothing_to_release_and_no_session_are_both_no_ops(session):
    assert await release_idle_connection(None) is False
    assert await release_idle_connection(session) is False


@pytest.mark.asyncio
async def test_the_revocation_gated_session_releases_without_tripping_its_gate(session):
    from services.pilot_authz import RevocationGatedSession

    gated = RevocationGatedSession(session, ctx=SimpleNamespace(), request_ctx=None)
    await session.execute(text("SELECT 1"))
    # Its gate would revalidate the grant; with nothing pending there is no
    # write to gate, so release goes straight to the wrapped session.
    with patch("services.pilot_authz.revalidate", AsyncMock(side_effect=AssertionError("gate called"))):
        assert await release_idle_connection(gated) is True
    assert not session.in_transaction()


class _Stream:
    def __init__(self, usage):
        self._usage = usage

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        yield RawContentBlockStartEvent.model_validate(
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
        yield RawContentBlockDeltaEvent.model_validate(
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}})
        yield RawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": 0})

    async def get_final_message(self):
        return SimpleNamespace(usage=SimpleNamespace(
            input_tokens=1, output_tokens=1, cache_creation_input_tokens=0, cache_read_input_tokens=0))


@pytest.mark.asyncio
async def test_stream_tutor_response_releases_the_connection_before_the_model_call(session):
    seen = []

    @asynccontextmanager
    async def fake_stream(**kwargs):
        seen.append(session.in_transaction())
        yield _Stream(None)

    await session.execute(text("SELECT 1"))
    assert session.in_transaction()
    config = SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery)
    with patch.object(ai_service._client.messages, "stream", side_effect=fake_stream), \
         patch("core.api_usage.record_usage", AsyncMock()):
        async for _ in ai_service.stream_tutor_response(
            config=config, subject=Subject.mathematics, history=[], child_message="Hi", db=session,
        ):
            pass
    assert seen, "the model was never called"
    assert seen == [False] * len(seen), f"a connection was held during a model call: {seen}"


def test_the_chat_route_releases_before_moderation_and_streaming():
    """routers/tutor.py's event generator must release first, before the
    moderation call and the streamed reply (both long waits). A source check,
    since the route's own preconditions (consent, quota, authz) need a full
    app to drive; the stream_tutor_response test above proves the call works."""
    import inspect
    from routers import tutor

    src = inspect.getsource(tutor.chat)
    gen = src[src.index("async def event_generator():"):]
    release = gen.index("await release_idle_connection(db)")
    assert release < gen.index("classify_child_message(")
    assert release < gen.index("stream_tutor_response(")
