"""
Regression tests for the weekly poetry/prayer rotation using the CHILD's
device date (see homeschool-tutor/src/store/sessionStore.ts's
deriveLocalDate) rather than the server's date.today() — the bug being
fixed: a server running in a different timezone than the family (typically
UTC) could pick a different ISO week's poem/prayer than the child's own
calendar near a Sunday/Monday boundary, since poetry_catalog.py and
prayer_catalog.py previously always fell through to date.today() with no
way for a caller to supply the real one.

Mirrors test_time_of_day.py's structure: unit-level threading through
_build_subject_prompt, then an end-to-end check that stream_tutor_response
actually forwards local_date all the way to the request Bede sees.
"""
from contextlib import asynccontextmanager
from datetime import date
from unittest.mock import patch

import pytest
from anthropic.types import RawContentBlockDeltaEvent, RawContentBlockStartEvent, RawContentBlockStopEvent

from models.schemas import GradeStage, SessionConfig, Subject
from services import ai_service
from services.ai_service import _build_subject_prompt
from services.poetry_catalog import poem_for_week
from services.prayer_catalog import prayer_for_week

pytestmark = pytest.mark.asyncio


def _config() -> SessionConfig:
    return SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery)


# Two dates deliberately one ISO week apart (both Mondays), the exact
# scenario this fix targets: a client-local Monday the server (in a
# different timezone) might still consider the prior Sunday, or vice versa.
_WEEK_1_MONDAY = date(2027, 1, 4)
_WEEK_2_MONDAY = date(2027, 1, 11)


async def test_build_subject_prompt_poetry_reflects_supplied_local_date():
    config = _config()
    prompt = await _build_subject_prompt(config, Subject.morning_time, local_date=_WEEK_1_MONDAY)
    expected = poem_for_week(config.grade, config.grade_stage, week_salt=config.current_term, today=_WEEK_1_MONDAY)
    assert expected is not None
    assert expected["title"] in prompt


async def test_build_subject_prompt_prayer_reflects_supplied_local_date():
    config = _config()
    prompt = await _build_subject_prompt(config, Subject.morning_time, local_date=_WEEK_1_MONDAY)
    expected = prayer_for_week(config.grade, config.grade_stage, week_salt=config.current_term, today=_WEEK_1_MONDAY)
    assert expected is not None
    assert expected["title"] in prompt


async def test_different_local_dates_can_select_different_weeks_poem():
    """Not just present — the parameter actually changes which week is
    picked, proving _build_subject_prompt isn't silently ignoring it."""
    config = _config()
    entry_week_1 = poem_for_week(config.grade, config.grade_stage, week_salt=config.current_term, today=_WEEK_1_MONDAY)
    entry_week_2 = poem_for_week(config.grade, config.grade_stage, week_salt=config.current_term, today=_WEEK_2_MONDAY)
    prompt_week_1 = await _build_subject_prompt(config, Subject.morning_time, local_date=_WEEK_1_MONDAY)
    prompt_week_2 = await _build_subject_prompt(config, Subject.morning_time, local_date=_WEEK_2_MONDAY)
    assert entry_week_1["title"] in prompt_week_1
    assert entry_week_2["title"] in prompt_week_2


async def test_build_subject_prompt_without_local_date_falls_back_to_server_today():
    """No client date supplied (older client, sandbox) — behavior must be
    unchanged from before this fix: the catalogs' own date.today() default."""
    config = _config()
    prompt = await _build_subject_prompt(config, Subject.morning_time)
    expected = poem_for_week(config.grade, config.grade_stage, week_salt=config.current_term)
    assert expected is not None
    assert expected["title"] in prompt


# ── End-to-end: stream_tutor_response actually forwards local_date ─────────

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


async def test_stream_tutor_response_forwards_local_date_into_the_system_prompt():
    config = _config()
    expected = poem_for_week(config.grade, config.grade_stage, week_salt=config.current_term, today=_WEEK_1_MONDAY)
    captured: dict = {}
    with patch.object(ai_service._client.messages, "stream", side_effect=_capturing_stream(captured)):
        async for _ in ai_service.stream_tutor_response(
            config=config,
            subject=Subject.morning_time,
            history=[],
            child_message="What's today's poem?",
            local_date=_WEEK_1_MONDAY,
        ):
            pass

    subject_block_text = captured["system"][1]["text"]
    assert expected["title"] in subject_block_text
