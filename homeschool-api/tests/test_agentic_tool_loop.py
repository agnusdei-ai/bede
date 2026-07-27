"""
Covers the bounded tool_result loop in stream_tutor_response (see
_MAX_TOOL_LOOP_ROUNDS / _TRIVIAL_TOOL_RESULT in services/ai_service.py):
Bede's own tool calls that carry a real outcome (show_visual_aid,
assess_narration) can now be fed back to the model as a proper
tool_result within the same turn, instead of the outcome only ever
reaching the SSE stream/DB. Every other tool still resolves to a fixed
acknowledgment, so an ordinary turn is unaffected — see
test_ai_service_streaming.py/test_tool_call_audit.py, all still green
after this change with zero modifications.

Reuses tests/test_tool_call_audit.py's fake-stream pattern, extended with
get_final_message() (stop_reason + content) since the loop's continue/
break decision depends on both.
"""
import json as _json
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest
from anthropic.types import RawContentBlockDeltaEvent, RawContentBlockStartEvent, RawContentBlockStopEvent

from core.audit import AuditEvent
from models.schemas import GradeStage, SessionConfig, Subject
from services import ai_service

pytestmark = pytest.mark.asyncio


def _config(name: str = "Sam") -> SessionConfig:
    return SessionConfig(student_name=name, grade="4", grade_stage=GradeStage.core_mastery)


def _tool_use_events(block_id: str, tool_name: str, tool_input: dict):
    yield RawContentBlockStartEvent.model_validate({
        "type": "content_block_start", "index": 0,
        "content_block": {"type": "tool_use", "id": block_id, "name": tool_name, "input": {}},
    })
    yield RawContentBlockDeltaEvent.model_validate({
        "type": "content_block_delta", "index": 0,
        "delta": {"type": "input_json_delta", "partial_json": _json.dumps(tool_input)},
    })
    yield RawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": 0})


def _text_events(text: str):
    yield RawContentBlockStartEvent.model_validate(
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
    )
    yield RawContentBlockDeltaEvent.model_validate(
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}
    )
    yield RawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": 0})


class _FakeStream:
    def __init__(self, events, stop_reason):
        self._events = events
        self._stop_reason = stop_reason

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        for event in self._events:
            yield event

    async def get_final_message(self):
        msg = MagicMock()
        msg.stop_reason = self._stop_reason
        # Only ever read (.model_dump()'d) when the loop decides to
        # continue — a plain MagicMock block stands in fine for that.
        msg.content = [MagicMock(model_dump=lambda: {"type": "tool_use"})]
        msg.usage = MagicMock(
            input_tokens=1, output_tokens=1,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )
        return msg


def _multi_round_stream(rounds: list[tuple[list, str]]):
    """rounds: [(events, stop_reason), ...] — one entry consumed per
    .messages.stream() call, in order, mirroring a real multi-round
    conversation. Calling past the given rounds is a test bug, not a
    silently-tolerated case, so it raises."""
    state = {"i": 0}

    @asynccontextmanager
    async def _fake(**kwargs):
        i = state["i"]
        state["i"] += 1
        events, stop_reason = rounds[i]
        yield _FakeStream(list(events), stop_reason)

    _fake.call_count = lambda: state["i"]
    return _fake, state


_HINT = ("offer_socratic_hint", {"hint_question": "What comes next?"})
_CELEBRATE = ("celebrate_discovery", {"specific_insight": "the pattern", "encouragement": "Well done!"})


@pytest.fixture
def audit_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ai_service, "log_event_nowait",
        lambda event, **kwargs: calls.append((event, kwargs)),
    )
    return calls


async def _run_turn(rounds, **kwargs):
    fake, state = _multi_round_stream(rounds)
    chunks = []
    with patch.object(ai_service._client.messages, "stream", side_effect=fake):
        async for chunk in ai_service.stream_tutor_response(
            config=_config(), subject=Subject.morning_time, history=[],
            child_message="hello", **kwargs,
        ):
            chunks.append(_json.loads(chunk))
    return chunks, state["i"]


async def test_ordinary_tool_only_turn_never_grows_a_second_round(audit_calls):
    """offer_socratic_hint/celebrate_discovery have nothing dynamic to
    report back — even if the model's own stop_reason says "tool_use",
    the loop must not call the model again for these."""
    rounds = [
        (list(_tool_use_events("t0", *_HINT)) + list(_tool_use_events("t1", *_CELEBRATE)), "tool_use"),
    ]
    chunks, call_count = await _run_turn(rounds)

    assert call_count == 1, "no second round for tools with only a fixed acknowledgment"
    tool_chunks = [c for c in chunks if c["type"] == "tool"]
    assert len(tool_chunks) == 2
    assert chunks[-1] == {"type": "done"}


async def test_unresolved_visual_aid_gets_a_reactive_second_round(audit_calls):
    """The concrete case this loop exists for: a hallucinated
    visual_aid_id used to be a silent no-op. Now Bede's own next round
    sees {"found": false, ...} and can recover with real text."""
    round1 = list(_tool_use_events("t0", "show_visual_aid", {"visual_aid_id": "not-a-real-id"}))
    round2 = list(_text_events("Let's picture it a different way instead."))
    chunks, call_count = await _run_turn([(round1, "tool_use"), (round2, "end_turn")])

    assert call_count == 2, "an unresolved visual aid must trigger a reactive follow-up round"
    visual_aid_chunks = [c for c in chunks if c["type"] == "visual_aid"]
    assert visual_aid_chunks == [], "an unresolved id must never render a visual_aid card"
    text_chunks = [c for c in chunks if c["type"] == "text"]
    assert any("picture it a different way" in c["content"] for c in text_chunks)
    assert chunks[-1] == {"type": "done"}


async def test_second_round_receives_the_actual_tool_result_payload(audit_calls):
    """The messages list handed to round 2 must carry a real tool_result
    for the show_visual_aid call, not just an acknowledgment — that's
    the entire point of the loop."""
    round1 = list(_tool_use_events("t0", "show_visual_aid", {"visual_aid_id": "missing"}))
    round2 = list(_text_events("Okay, let's try describing it instead."))

    fake, state = _multi_round_stream([(round1, "tool_use"), (round2, "end_turn")])
    captured_calls = []
    original = fake

    @asynccontextmanager
    async def _spy(**kwargs):
        captured_calls.append(kwargs.get("messages"))
        async with original(**kwargs) as s:
            yield s

    with patch.object(ai_service._client.messages, "stream", side_effect=_spy):
        async for _ in ai_service.stream_tutor_response(
            config=_config(), subject=Subject.morning_time, history=[], child_message="hi",
        ):
            pass

    assert len(captured_calls) == 2
    second_call_messages = captured_calls[1]
    tool_result_msg = next(m for m in second_call_messages if m["role"] == "user" and isinstance(m["content"], list) and m["content"] and m["content"][0].get("type") == "tool_result")
    payload = _json.loads(tool_result_msg["content"][0]["content"])
    assert payload == {"found": False, "visual_aid_id": "missing"}


async def test_suggest_next_subject_always_ends_the_loop_immediately(audit_calls):
    """suggest_next_subject is a terminal UI transition — even paired with
    a reactable tool in the same round, no second round should happen."""
    round1 = list(_tool_use_events("t0", "show_visual_aid", {"visual_aid_id": "missing"})) + list(
        _tool_use_events("t1", "suggest_next_subject", {"reason": "complete", "message": "Great work!"})
    )
    chunks, call_count = await _run_turn([(round1, "tool_use")])

    assert call_count == 1
    assert any(c["type"] == "subject_complete" for c in chunks)


async def test_round_cap_stops_the_loop_and_is_audited(audit_calls):
    """If the model keeps returning stop_reason="tool_use" with a
    reactable tool every round, the loop still terminates at
    _MAX_TOOL_LOOP_ROUNDS and logs AGENTIC_LOOP_CAPPED — it can never
    spin indefinitely."""
    cap = ai_service._MAX_TOOL_LOOP_ROUNDS
    rounds = [
        (list(_tool_use_events(f"t{i}", "show_visual_aid", {"visual_aid_id": "missing"})), "tool_use")
        for i in range(cap)
    ]
    chunks, call_count = await _run_turn(rounds)

    assert call_count == cap, "must never exceed the round cap regardless of what the model wants"
    assert chunks[-1] == {"type": "done"}
    capped = [c for e, c in audit_calls if e == AuditEvent.AGENTIC_LOOP_CAPPED]
    assert len(capped) == 1


async def test_call_cap_ends_the_loop_outright_even_mid_round(audit_calls):
    """Hitting _MAX_TOOL_CALLS_PER_TURN mid-round must never leave a
    tool_use block without a matching tool_result on the next call — the
    safest way to guarantee that is to never make a next call at all."""
    cap = ai_service._MAX_TOOL_CALLS_PER_TURN
    # cap calls to fill the budget, then one more (suppressed) reactable
    # call in the same round.
    events = []
    for i in range(cap):
        events.extend(_tool_use_events(f"t{i}", *_HINT))
    events.extend(_tool_use_events("t_over", "show_visual_aid", {"visual_aid_id": "missing"}))

    chunks, call_count = await _run_turn([(events, "tool_use")])

    assert call_count == 1, "a suppressed call must never lead to a second round"
    suppressed = [e for e, _ in audit_calls if e == AuditEvent.TOOL_CALL_SUPPRESSED]
    assert len(suppressed) == 1
    assert chunks[-1] == {"type": "done"}


async def test_assess_narration_summary_is_the_reactive_payload(audit_calls, monkeypatch):
    """assess_narration's already-computed summary (subject/total_score/
    adaptive_signal) becomes the tool_result content, not a bare ack."""
    async def _fake_save_assessment(db, student_name, subject, tool_input):
        return {"subject": subject.value, "total_score": 12, "adaptive_signal": "ready_to_advance"}

    monkeypatch.setattr(ai_service, "_save_assessment", _fake_save_assessment)

    round1 = list(_tool_use_events("t0", "assess_narration", {
        "completeness": 3, "sequence": 3, "detail": 2, "language_quality": 2, "synthesis": 2,
    }))
    round2 = list(_text_events("You really nailed the sequence of events!"))

    fake, state = _multi_round_stream([(round1, "tool_use"), (round2, "end_turn")])
    captured_calls = []
    original = fake

    @asynccontextmanager
    async def _spy(**kwargs):
        captured_calls.append(kwargs.get("messages"))
        async with original(**kwargs) as s:
            yield s

    with patch.object(ai_service._client.messages, "stream", side_effect=_spy):
        async for _ in ai_service.stream_tutor_response(
            config=_config(), subject=Subject.language_arts, history=[], child_message="hi",
        ):
            pass

    assert len(captured_calls) == 2
    tool_result_msg = next(
        m for m in captured_calls[1]
        if m["role"] == "user" and isinstance(m["content"], list) and m["content"] and m["content"][0].get("type") == "tool_result"
    )
    payload = _json.loads(tool_result_msg["content"][0]["content"])
    assert payload == {"subject": "language_arts", "total_score": 12, "adaptive_signal": "ready_to_advance"}


async def test_second_round_replay_works_with_non_anthropic_adapter_blocks(audit_calls):
    """The demo's OpenAI/Mistral failover and any self-hosted local vLLM
    deployment route through services/adapters/openai_compatible_adapter.py,
    whose AdapterMessage.content is a list of services/adapters/base.py's
    TextBlock/ToolUseBlock — plain slotted objects with NO .model_dump(),
    unlike the real Anthropic SDK's pydantic content blocks. Without
    _content_block_to_dict()'s fallback, the second round would raise
    AttributeError the first time any non-Anthropic provider hit a
    reactive tool_result (show_visual_aid/assess_narration)."""
    from services.adapters.base import ToolUseBlock

    round1 = list(_tool_use_events("t0", "show_visual_aid", {"visual_aid_id": "missing"}))
    round2 = list(_text_events("Let's try it a different way."))

    fake, state = _multi_round_stream([(round1, "tool_use"), (round2, "end_turn")])
    original = fake

    @asynccontextmanager
    async def _adapter_shaped(**kwargs):
        async with original(**kwargs) as stream:
            # Swap in an adapter-shaped (no model_dump) final message for
            # round 1 only — the exact object shape a real
            # OpenAICompatibleClient would hand back.
            if state["i"] == 1:
                async def _adapter_final_message():
                    msg = MagicMock()
                    msg.stop_reason = "tool_use"
                    msg.content = [ToolUseBlock(id="t0", name="show_visual_aid", input={"visual_aid_id": "missing"})]
                    msg.usage = MagicMock(
                        input_tokens=1, output_tokens=1,
                        cache_creation_input_tokens=0, cache_read_input_tokens=0,
                    )
                    return msg
                stream.get_final_message = _adapter_final_message
            yield stream

    chunks = []
    with patch.object(ai_service._client.messages, "stream", side_effect=_adapter_shaped):
        async for chunk in ai_service.stream_tutor_response(
            config=_config(), subject=Subject.morning_time, history=[], child_message="hi",
        ):
            chunks.append(_json.loads(chunk))

    assert state["i"] == 2, "must still reach round 2 without raising"
    assert any(c["type"] == "text" and "different way" in c["content"] for c in chunks)


async def test_silent_evidence_tools_never_extend_the_loop(audit_calls):
    """record_skill_evidence/record_phonics_evidence/record_language_evidence
    keep their explicit no-return-value, no-SSE-chunk contract — they must
    never gain a reactive tool_result or trigger a second round."""
    round1 = list(_tool_use_events("t0", "record_skill_evidence", {
        "probe_id": "probe.cc.rote_count_20", "outcome": "correct",
    }))
    chunks2 = []
    fake, state = _multi_round_stream([(round1, "tool_use")])
    with patch.object(ai_service._client.messages, "stream", side_effect=fake):
        async for chunk in ai_service.stream_tutor_response(
            config=_config(), subject=Subject.mathematics, history=[], child_message="hi",
        ):
            chunks2.append(_json.loads(chunk))

    assert state["i"] == 1, "a silent evidence tool must never grow a second round"
    assert not [c for c in chunks2 if c["type"] not in ("done",)], "nothing but 'done' should ever be emitted for this tool"
