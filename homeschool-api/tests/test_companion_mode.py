"""
Regression tests for the parent-chosen "companion mode" preset
(ParentSetup.tsx's setup-time picker — see models.schemas.CompanionMode):
a lighter-touch starting point for families new to homeschooling, or
easing into AI deliberately, who want Bede anchored on their own physical
books rather than driving the full subject rotation.

Mirrors test_time_of_day.py's structure, but the note lives in the STATIC
prompt block (_build_static_prompt), not the per-subject block — it's a
session-long framing, not something that varies by subject.
"""
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from anthropic.types import RawContentBlockDeltaEvent, RawContentBlockStartEvent, RawContentBlockStopEvent

from models.schemas import CompanionMode, GradeStage, SessionConfig, Subject
from services import ai_service
from services.ai_service import _build_subject_prompt, _build_static_prompt, _companion_mode_note


def _config(companion_mode: CompanionMode = CompanionMode.full_plan) -> SessionConfig:
    return SessionConfig(
        student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery, companion_mode=companion_mode,
    )


def test_full_plan_produces_no_note():
    """The default, and every config saved before this field existed —
    must be a true no-op so the cached static prompt is byte-for-byte
    unchanged for every family that never touches this setting."""
    assert _companion_mode_note(_config(CompanionMode.full_plan)) == ""


def test_book_companion_note_anchors_on_the_familys_own_books():
    note = _companion_mode_note(_config(CompanionMode.book_companion))
    assert "companion_mode_guidance" in note
    assert "Sam" in note
    assert "current_unit" in note
    assert "lesson_focus" in note


def test_guided_note_is_lighter_than_book_companion():
    note = _companion_mode_note(_config(CompanionMode.guided))
    assert "companion_mode_guidance" in note
    assert "middle path" in note


def test_build_static_prompt_omits_note_for_full_plan():
    prompt = _build_static_prompt(_config(CompanionMode.full_plan))
    assert "companion_mode_guidance" not in prompt


def test_build_static_prompt_includes_note_for_book_companion():
    prompt = _build_static_prompt(_config(CompanionMode.book_companion))
    assert "companion_mode_guidance" in prompt


@pytest.mark.asyncio
async def test_book_companion_does_not_suppress_the_composition_invitation():
    """Regression test for a real conflict this field's own first release
    shipped with: book_companion's "favor spoken discussion... over
    handwriting" line and _composition_note's separate once-per-session
    "encourage... via invite_handwriting" guarantee were both present, with
    no carve-out, in the same prompt — directly contradictory instructions
    for every family that picked Book Companion. Asserts both survive
    together: the static block still nudges away from handwriting during
    ordinary dialogue, but the subject block's composition invitation is
    both present and explicitly excepted from that nudge."""
    config = _config(CompanionMode.book_companion)
    static_prompt = _build_static_prompt(config)
    subject_prompt = await _build_subject_prompt(config, Subject.living_books, history=[])

    assert "Favor spoken discussion and oral narration over handwriting" in static_prompt
    assert "does NOT apply to the session's own once-a-day composition invitation" in static_prompt
    assert "COMPOSITION THIS SESSION" in subject_prompt
    assert "encourage a sustained piece of handwritten composition via `invite_handwriting`" in subject_prompt


# ── End-to-end: stream_tutor_response forwards it into the STATIC block ────

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
async def test_stream_tutor_response_forwards_companion_mode_into_static_block():
    captured: dict = {}
    with patch.object(ai_service._client.messages, "stream", side_effect=_capturing_stream(captured)):
        async for _ in ai_service.stream_tutor_response(
            config=_config(CompanionMode.book_companion),
            subject=Subject.living_books,
            history=[],
            child_message="What are we reading today?",
        ):
            pass

    # Static block is the FIRST entry of the two-block system prompt (see
    # stream_tutor_response's "system" list) — the companion-mode note
    # belongs there, not the per-subject second block, since it's a
    # session-long framing rather than something that varies by subject.
    static_block_text = captured["system"][0]["text"]
    subject_block_text = captured["system"][1]["text"]
    assert "companion_mode_guidance" in static_block_text
    assert "companion_mode_guidance" not in subject_block_text
