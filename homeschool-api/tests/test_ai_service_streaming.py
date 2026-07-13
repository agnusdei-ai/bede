"""
Business-logic tests for stream_tutor_response()'s per-tool dispatch and its
guaranteed-continuation fallback — independent of which model provider
answered. These mock get_provider() directly with normalized TextDelta/
ToolCall events; the raw-anthropic-SDK-event regression coverage this file
used to carry now lives in tests/model_providers/test_anthropic_provider.py,
against AnthropicProvider itself.
"""
import json
from unittest.mock import patch

import pytest

from models.schemas import GradeStage, SessionConfig, Subject
from services import ai_service
from services.model_providers.base import TextDelta, ToolCall


class _FakeProvider:
    def __init__(self, events):
        self._events = events

    async def stream(self, **kwargs):
        for event in self._events:
            yield event


def _config() -> SessionConfig:
    return SessionConfig(student_name="Guest", grade="4", grade_stage=GradeStage.core_mastery)


async def _run_stream(events) -> list[dict]:
    with patch.object(ai_service, "get_provider", return_value=_FakeProvider(events)):
        chunks = [
            chunk
            async for chunk in ai_service.stream_tutor_response(
                config=_config(),
                subject=Subject.living_books,
                history=[],
                child_message="Tell me about the river.",
            )
        ]
    return [json.loads(c) for c in chunks]


@pytest.mark.asyncio
async def test_stream_tutor_response_emits_text():
    parsed = await _run_stream([TextDelta("Hello there")])

    text_chunks = [p for p in parsed if p["type"] == "text"]
    assert text_chunks, "no text chunk was emitted"
    assert "".join(p["content"] for p in text_chunks) == "Hello there"
    assert parsed[-1] == {"type": "done"}


# ── Guaranteed continuation after a questionless tool card ──────────────────
#
# Regression coverage for a real observed outage: Bede's turn ended right on
# a celebrate_discovery card with no trailing text at all — a live transcript
# screenshot showed the conversation just stopping, with nothing for the
# child to respond to. The system prompt already asks the model to always
# add a question after one of these tools (see tools_guidance), but that's a
# request, not a guarantee — tool-calling models have a real tendency to
# treat a tool call as a natural end of turn. These tests exercise the
# code-level fallback in stream_tutor_response that fires regardless of
# whether the model complies.

@pytest.mark.asyncio
async def test_celebrate_discovery_as_the_last_block_gets_a_fallback_question():
    events = [ToolCall(
        id="toolu_1", name="celebrate_discovery",
        input={"specific_insight": "the river carves the canyon", "encouragement": "That's real thinking!"},
    )]
    parsed = await _run_stream(events)

    assert parsed[-1] == {"type": "done"}
    text_chunks = [p for p in parsed if p["type"] == "text"]
    assert text_chunks, "no fallback question was appended after a questionless tool card"
    assert text_chunks[-1]["content"].strip() in ai_service._FALLBACK_CONTINUATION_QUESTIONS


@pytest.mark.asyncio
async def test_no_fallback_appended_when_the_model_already_added_a_question():
    events = [
        ToolCall(id="toolu_1", name="celebrate_discovery", input={"specific_insight": "x", "encouragement": "y"}),
        TextDelta(" What do you notice about the next bend in the river?"),
    ]
    parsed = await _run_stream(events)

    text_chunks = [p for p in parsed if p["type"] == "text"]
    assert len(text_chunks) == 1, "a fallback was appended even though the model already asked a question"
    assert "next bend" in text_chunks[0]["content"]


@pytest.mark.asyncio
async def test_connect_to_faith_without_reflection_question_gets_a_fallback():
    events = [ToolCall(
        id="toolu_1", name="connect_to_faith",
        input={"connection": "Just as the river never stops moving, God's care never stops either."},
    )]
    parsed = await _run_stream(events)

    text_chunks = [p for p in parsed if p["type"] == "text"]
    assert text_chunks, "connect_to_faith with no reflection_question should still get a fallback"
    assert text_chunks[-1]["content"].strip() in ai_service._FALLBACK_CONTINUATION_QUESTIONS


@pytest.mark.asyncio
async def test_connect_to_faith_with_reflection_question_gets_no_fallback():
    events = [ToolCall(
        id="toolu_1", name="connect_to_faith",
        input={"connection": "The river never stops moving.", "reflection_question": "What else in creation never stops?"},
    )]
    parsed = await _run_stream(events)

    text_chunks = [p for p in parsed if p["type"] == "text"]
    assert not text_chunks, "connect_to_faith already had its own reflection_question — no fallback should be added"


@pytest.mark.asyncio
async def test_offer_socratic_hint_as_last_block_gets_no_fallback():
    """offer_socratic_hint's hint_question already IS the turn's question —
    it's deliberately not in _QUESTIONLESS_TOOLS."""
    events = [ToolCall(
        id="toolu_1", name="offer_socratic_hint",
        input={"hint_question": "What shape does flowing water tend to carve?"},
    )]
    parsed = await _run_stream(events)

    text_chunks = [p for p in parsed if p["type"] == "text"]
    assert not text_chunks, "offer_socratic_hint's own question should not trigger a redundant fallback"


@pytest.mark.asyncio
async def test_show_visual_aid_emits_visual_aid_event_for_known_id():
    with patch.object(ai_service, "_lookup_visual_aid", return_value={"id": "mona-lisa", "title": "Mona Lisa"}):
        events = [ToolCall(id="toolu_1", name="show_visual_aid", input={"visual_aid_id": "mona-lisa"})]
        parsed = await _run_stream(events)

    visual_events = [p for p in parsed if p["type"] == "visual_aid"]
    assert visual_events == [{"type": "visual_aid", "visualAid": {"id": "mona-lisa", "title": "Mona Lisa"}}]


@pytest.mark.asyncio
async def test_show_visual_aid_silently_drops_unknown_id():
    with patch.object(ai_service, "_lookup_visual_aid", return_value=None):
        events = [ToolCall(id="toolu_1", name="show_visual_aid", input={"visual_aid_id": "made-up"})]
        parsed = await _run_stream(events)

    assert not any(p["type"] == "visual_aid" for p in parsed)
    assert parsed[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_suggest_next_subject_emits_subject_complete_event():
    events = [ToolCall(
        id="toolu_1", name="suggest_next_subject",
        input={"reason": "mastery", "message": "You've got this — let's move on!"},
    )]
    parsed = await _run_stream(events)

    complete_events = [p for p in parsed if p["type"] == "subject_complete"]
    assert complete_events == [{
        "type": "subject_complete", "reason": "mastery", "content": "You've got this — let's move on!",
    }]
