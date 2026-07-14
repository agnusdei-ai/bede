"""
Real check for Bede's time-of-day awareness — the child's device clock at
login (see homeschool-tutor/src/store/sessionStore.ts's deriveTimeOfDay) is
bucketed into morning/afternoon/evening and sent on every /tutor/chat
request as local_time_of_day, since the server has no reliable way to know
the child's timezone otherwise. Confirms _time_of_day_note produces the
right greeting/prayer-framing instruction per bucket, that it's actually
wired into the subject prompt _build_subject_prompt returns, and that
stream_tutor_response propagates it all the way to the Anthropic request.
"""
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from anthropic.types import RawContentBlockDeltaEvent, RawContentBlockStartEvent, RawContentBlockStopEvent

from models.schemas import GradeStage, SessionConfig, Subject
from services import ai_service
from services.ai_service import _build_subject_prompt, _time_of_day_note


def test_none_produces_no_note():
    assert _time_of_day_note(None) == ""


def test_morning_note_mentions_good_morning():
    note = _time_of_day_note("morning")
    assert "Good morning" in note
    assert "Morning Time" in note


def test_afternoon_note_mentions_good_afternoon_and_no_prayer_reframing():
    note = _time_of_day_note("afternoon")
    assert "Good afternoon" in note
    assert "prayer" not in note.lower()


def test_evening_note_mentions_good_evening_and_reframes_the_opening_prayer():
    note = _time_of_day_note("evening")
    assert "Good evening" in note
    assert "Evening Time" in note
    assert "day now ending" in note


def _config() -> SessionConfig:
    return SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery)


@pytest.mark.asyncio
async def test_build_subject_prompt_includes_the_time_of_day_note():
    prompt = await _build_subject_prompt(_config(), Subject.mathematics, time_of_day="evening")
    assert "Good evening" in prompt


@pytest.mark.asyncio
async def test_build_subject_prompt_omits_note_when_time_of_day_not_supplied():
    prompt = await _build_subject_prompt(_config(), Subject.mathematics)
    assert "Good morning" not in prompt
    assert "Good afternoon" not in prompt
    assert "Good evening" not in prompt


# ── End-to-end: stream_tutor_response actually forwards time_of_day ────────

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
async def test_stream_tutor_response_forwards_time_of_day_into_the_system_prompt():
    captured: dict = {}
    with patch.object(ai_service._client.messages, "stream", side_effect=_capturing_stream(captured)):
        async for _ in ai_service.stream_tutor_response(
            config=_config(),
            subject=Subject.living_books,
            history=[],
            child_message="What happens next?",
            time_of_day="evening",
        ):
            pass

    # subject block is the second entry of the two-block system prompt (see
    # stream_tutor_response's "system" list — static block first, cached).
    subject_block_text = captured["system"][1]["text"]
    assert "Good evening" in subject_block_text
