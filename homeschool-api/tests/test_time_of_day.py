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
    assert "day now ending" in note


def test_the_evening_note_does_not_coin_a_practice_called_evening_time():
    """Reported by a real family, at 10:54pm: Bede opened with "Let's begin
    our evening Morning Time moment together."

    This note used to instruct: 'frame your one-sentence introduction ... as
    an Evening Time moment'. "Evening Time" is not a practice — it was
    invented here as a counterpart to Morning Time, which IS one. Given a
    subject literally named "Morning Time" and an instruction naming an
    "Evening Time moment", the model welded the two into a phrase that means
    nothing, in the very first sentence a child reads.

    A model may not be handed a coined name for something and be expected to
    keep it separate from a real one it looks like. The instruction now
    describes the framing (thank God for the day now ending) and names
    nothing, so there is no second label to collide with the subject's own.
    """
    note = _time_of_day_note("evening")
    assert "Evening Time" not in note.replace('there is no such practice as "Evening Time"', "")
    # And it says so outright, since the phrase is an easy one to reinvent.
    assert "evening Morning Time" in note


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


def test_morning_time_is_taught_as_a_proper_noun_not_a_clock_reading():
    """The deeper half of the same bug, and the reason fixing the evening
    note alone was not enough.

    Nothing anywhere told Bede that "Morning Time" NAMES a practice. So a
    model told "it is currently evening" while teaching a subject called
    Morning Time will keep trying to reconcile the two — the coined
    "Evening Time" gave it one way to do that, and removing the phrase does
    not remove the pull. Charlotte Mason / Mater Amabilis families keep
    Morning Time whenever their own day allows, evening included; the name
    is not a schedule.

    Asserted against the subject block rather than the time-of-day note,
    because it must hold at every hour, including when no time_of_day was
    sent at all.
    """
    from services.ai_service import _SUBJECT_CONTEXT

    context = _SUBJECT_CONTEXT[Subject.morning_time]
    assert "not a claim about the clock" in context
    assert "evening Morning Time" in context
    assert "Call it Morning Time at every hour" in context


def test_the_morning_time_block_no_longer_assumes_the_day_is_ahead():
    """"Set a joyful, expectant tone for the day" and "the hour in which"
    are both false for a family gathering at 10pm — the day is over. The
    time-of-day note already supplies the day-ahead vs day-ending framing,
    so this block states the practice rather than the schedule."""
    from services.ai_service import _SUBJECT_CONTEXT

    context = _SUBJECT_CONTEXT[Subject.morning_time]
    assert "expectant tone for the day" not in context
    assert "the hour in which" not in context


@pytest.mark.asyncio
async def test_an_evening_morning_time_prompt_carries_both_guards():
    """The exact reported configuration: Morning Time, opened in the
    evening. Both halves must reach the model in the same prompt."""
    prompt = await _build_subject_prompt(
        _config(), Subject.morning_time, time_of_day="evening"
    )
    assert "Good evening" in prompt
    assert "Call it Morning Time at every hour" in prompt
    assert "evening Morning Time" in prompt
