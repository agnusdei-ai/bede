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
from core.database import Base, LearnerProfile, MasteryProfile
from models.schemas import GradeStage, SessionConfig, Subject
from services import ai_service
from services.ai_service import (
    _build_subject_prompt,
    _load_mastery_vector_readonly,
    _load_processing_style_readonly,
    _processing_style_note,
)


def _config() -> SessionConfig:
    return SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery)


# ── _processing_style_note: pure function ────────────────────────────────────

def test_none_produces_no_note():
    assert _processing_style_note(None) == ""


def test_unknown_style_produces_no_note():
    assert _processing_style_note("not_a_real_style") == ""


def test_kinesthetic_note_mentions_structured_drawing_across_subjects():
    note = _processing_style_note("kinesthetic")
    assert "kinesthetic" in note
    assert "invite_handwriting" in note
    assert "DITK" in note
    assert "elements" in note


def test_reading_writing_note_favors_plain_written_narration():
    note = _processing_style_note("reading_writing")
    assert "reading/writing" in note
    assert "invite_handwriting" in note
    assert "elements` unset" in note


def test_visual_note_favors_show_visual_aid():
    note = _processing_style_note("visual")
    assert "visual" in note
    assert "show_visual_aid" in note


def test_auditory_note_favors_oral_narration_no_tool_named():
    """auditory has no honest tool-level signal (see LearnerBehaviorCheck's
    docstring) — it's a pure behavioral nudge, not tied to a specific tool
    call the way the other three are."""
    note = _processing_style_note("auditory")
    assert "auditory" in note
    assert "oral narration" in note


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


# ── Caching: this must not re-query the DB on every single turn ──────────────
# The real perf regression this closes: before caching, EVERY child message in
# EVERY subject (not just mathematics, unlike the sibling mastery-vector load)
# re-queried and re-decrypted LearnerProfile, even though the value can only
# change via an infrequent batch resynthesis, never mid-turn. See
# _READONLY_PROMPT_CACHE_TTL_SECONDS' comment in services/ai_service.py.

@pytest.mark.asyncio
async def test_second_call_within_ttl_does_not_hit_the_db_again(db_session):
    from core.encryption import encrypt_json

    db_session.add(LearnerProfile(
        student_name="Nora",
        session_count=4,
        profile_enc=encrypt_json({
            "trivium_stage": "logic", "processing_style": "kinesthetic",
            "narration_mode": "sequential", "attention_profile": "sustained",
            "session_count_assessed": 4, "bede_profile_notes": "",
            "assessed_at": "2026-01-01T00:00:00+00:00",
        }),
    ))
    await db_session.commit()

    assert await _load_processing_style_readonly(db_session, "Nora") == "kinesthetic"

    # Row deleted — a second call that actually re-queried would now see
    # nothing and fall back to None. Getting "kinesthetic" back proves the
    # second call was served from cache, not a fresh DB read.
    await db_session.delete((await db_session.get(LearnerProfile, "Nora")))
    await db_session.commit()

    assert await _load_processing_style_readonly(db_session, "Nora") == "kinesthetic"


@pytest.mark.asyncio
async def test_cache_is_keyed_per_student(db_session):
    from core.encryption import encrypt_json

    db_session.add(LearnerProfile(
        student_name="Priya",
        session_count=4,
        profile_enc=encrypt_json({
            "trivium_stage": "logic", "processing_style": "kinesthetic",
            "narration_mode": "sequential", "attention_profile": "sustained",
            "session_count_assessed": 4, "bede_profile_notes": "",
            "assessed_at": "2026-01-01T00:00:00+00:00",
        }),
    ))
    await db_session.commit()

    assert await _load_processing_style_readonly(db_session, "Priya") == "kinesthetic"
    # A different, never-seen student must still get a real (None) read,
    # not another student's cached value.
    assert await _load_processing_style_readonly(db_session, "Untouched") is None


@pytest.mark.asyncio
async def test_mastery_vector_load_is_also_cached(db_session):
    """Same fix, same reason, applied to the sibling loader — it only runs
    for mathematics turns (narrower than processing_style's every-subject
    reach), but the identical re-query-every-turn cost applied there too."""
    from core.encryption import encrypt_json

    db_session.add(MasteryProfile(
        student_name="Theo", subject_area="mathematics",
        evidence_count=5, profile_enc=encrypt_json({"oa.add_within_20": 0.9}),
    ))
    await db_session.commit()

    vector, count = await _load_mastery_vector_readonly(db_session, "Theo")
    assert (vector, count) == ({"oa.add_within_20": 0.9}, 5)

    await db_session.delete((await db_session.get(MasteryProfile, ("Theo", "mathematics"))))
    await db_session.commit()

    # Row is gone — a fresh read would now return (None, 0). Still seeing
    # the original values proves this came from cache.
    vector, count = await _load_mastery_vector_readonly(db_session, "Theo")
    assert (vector, count) == ({"oa.add_within_20": 0.9}, 5)


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
