"""
Real check that services/ai_service.py's four Anthropic call sites
(stream_tutor_response, stream_sandbox_response, generate_session_summary,
synthesize_learner_profile) actually call core.api_usage.record_usage
with the real usage numbers Anthropic returned — not just that
record_usage itself works in isolation (see test_api_usage.py).
"""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from anthropic.types import RawContentBlockDeltaEvent, RawContentBlockStartEvent, RawContentBlockStopEvent

from models.schemas import (
    ChatMessage, GradeStage, SessionConfig, SessionSummaryRequest, Subject,
)
from services import ai_service


class _FakeStream:
    """Extends the pattern from test_stream_history_normalization.py with
    get_final_message(), which stream_tutor_response/stream_sandbox_response
    now call after exhausting the event loop to capture usage."""
    def __init__(self, events, usage):
        self._events = events
        self._usage = usage

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        for event in self._events:
            yield event

    async def get_final_message(self):
        return SimpleNamespace(usage=self._usage)


def _text_events(text: str = "ok"):
    yield RawContentBlockStartEvent.model_validate(
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
    )
    yield RawContentBlockDeltaEvent.model_validate(
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}
    )
    yield RawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": 0})


def _usage(input_tokens=123, output_tokens=45, cache_creation=0, cache_read=0):
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation,
        cache_read_input_tokens=cache_read,
    )


def _fake_stream_cm(usage):
    @asynccontextmanager
    async def _fake(**kwargs):
        yield _FakeStream(list(_text_events()), usage)
    return _fake


def _config() -> SessionConfig:
    return SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery)


@pytest.mark.asyncio
async def test_tutor_stream_records_usage_with_the_students_name():
    mock_record = AsyncMock()
    usage = _usage(input_tokens=500, output_tokens=80, cache_creation=10, cache_read=2000)
    with patch.object(ai_service._client.messages, "stream", side_effect=_fake_stream_cm(usage)), \
         patch("core.api_usage.record_usage", mock_record):
        async for _ in ai_service.stream_tutor_response(
            config=_config(),
            subject=Subject.mathematics,
            history=[],
            child_message="Hi",
        ):
            pass

    mock_record.assert_awaited_once()
    kwargs = mock_record.await_args.kwargs
    assert kwargs["student_name"] == "Sam"
    assert kwargs["input_tokens"] == 500
    assert kwargs["output_tokens"] == 80
    assert kwargs["cache_creation_tokens"] == 10
    assert kwargs["cache_read_tokens"] == 2000


@pytest.mark.asyncio
async def test_sandbox_stream_records_usage_with_no_student_name():
    mock_record = AsyncMock()
    usage = _usage(input_tokens=200, output_tokens=60)
    with patch.object(ai_service._client.messages, "stream", side_effect=_fake_stream_cm(usage)), \
         patch("core.api_usage.record_usage", mock_record):
        async for _ in ai_service.stream_sandbox_response(
            conversation_history=[],
            message="What is 2+2?",
            custom_instructions="",
        ):
            pass

    mock_record.assert_awaited_once()
    kwargs = mock_record.await_args.kwargs
    assert kwargs["student_name"] is None
    assert kwargs["input_tokens"] == 200
    assert kwargs["output_tokens"] == 60


@pytest.mark.asyncio
async def test_a_turn_still_completes_normally_even_if_usage_capture_fails():
    """Usage logging is best-effort — a broken stream.get_final_message()
    must never break the child's actual turn."""
    @asynccontextmanager
    async def _broken_stream(**kwargs):
        class _Broken(_FakeStream):
            async def get_final_message(self):
                raise RuntimeError("boom")
        yield _Broken(list(_text_events()), _usage())

    chunks = []
    with patch.object(ai_service._client.messages, "stream", side_effect=_broken_stream):
        async for chunk in ai_service.stream_tutor_response(
            config=_config(), subject=Subject.mathematics, history=[], child_message="Hi",
        ):
            chunks.append(chunk)

    assert any('"type": "done"' in c for c in chunks)


@pytest.mark.asyncio
async def test_session_summary_records_usage_for_that_student():
    mock_record = AsyncMock()
    fake_response = SimpleNamespace(
        content=[SimpleNamespace(text="A lovely summary.")],
        usage=_usage(input_tokens=900, output_tokens=250),
    )
    req = SessionSummaryRequest(
        session_config=_config(),
        conversation_history=[ChatMessage(role="user", content="hi")],
        subjects_completed=[Subject.mathematics],
        duration_minutes=45,
    )
    with patch.object(ai_service._client.messages, "create", AsyncMock(return_value=fake_response)), \
         patch("core.api_usage.record_usage", mock_record):
        await ai_service.generate_session_summary(req)

    mock_record.assert_awaited_once()
    kwargs = mock_record.await_args.kwargs
    assert kwargs["student_name"] == "Sam"
    assert kwargs["input_tokens"] == 900
    assert kwargs["output_tokens"] == 250


@pytest.mark.asyncio
async def test_learner_profile_synthesis_records_usage_for_that_student():
    mock_record = AsyncMock()
    fake_response = SimpleNamespace(
        content=[SimpleNamespace(text='{"trivium_stage": "grammar", "processing_style": "visual", '
                                       '"narration_mode": "sequential", "attention_profile": "sustained", '
                                       '"bede_profile_notes": "Notes."}')],
        usage=_usage(input_tokens=300, output_tokens=90),
    )
    with patch.object(ai_service._client.messages, "create", AsyncMock(return_value=fake_response)), \
         patch("core.api_usage.record_usage", mock_record):
        await ai_service.synthesize_learner_profile("Emma", [{"total_score": 20}], session_count=1)

    mock_record.assert_awaited_once()
    kwargs = mock_record.await_args.kwargs
    assert kwargs["student_name"] == "Emma"
    assert kwargs["input_tokens"] == 300
    assert kwargs["output_tokens"] == 90
