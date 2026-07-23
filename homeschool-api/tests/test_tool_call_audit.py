"""
Defense-in-depth against unauthorized tool use, and the auditability gap
it closes: before this, a tool call from Claude executed unconditionally
the moment it parsed as valid JSON — no cap on how many a single turn
could act on, and for real (non-demo) parent/child sessions, NO durable
record that a tool fired at all (the demo's interaction_signals.py is a
separate, privacy-scoped, demo-only analytics pipeline, not a general
audit trail). See services/ai_service.py's _MAX_TOOL_CALLS_PER_TURN and
the dispatch loop in stream_tutor_response, and core/audit.py's
AuditEvent.TOOL_INVOKED/TOOL_CALL_SUPPRESSED + their anomaly rules
(covered separately in tests/test_audit_anomaly.py).

Reuses tests/test_learner_behavior_check.py's fake-stream pattern (real
anthropic SDK event types, ai_service._client.messages.stream patched).
"""
import json as _json
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from anthropic.types import RawContentBlockDeltaEvent, RawContentBlockStartEvent, RawContentBlockStopEvent

from core.audit import AuditEvent
from models.schemas import GradeStage, SessionConfig, Subject
from services import ai_service


def _config(name: str = "Sam") -> SessionConfig:
    return SessionConfig(student_name=name, grade="4", grade_stage=GradeStage.core_mastery)


def _tool_use_events(block_id: str, tool_name: str, tool_input: dict):
    """One full start -> delta -> stop cycle for a single tool_use block."""
    yield RawContentBlockStartEvent.model_validate({
        "type": "content_block_start", "index": 0,
        "content_block": {"type": "tool_use", "id": block_id, "name": tool_name, "input": {}},
    })
    yield RawContentBlockDeltaEvent.model_validate({
        "type": "content_block_delta", "index": 0,
        "delta": {"type": "input_json_delta", "partial_json": _json.dumps(tool_input)},
    })
    yield RawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": 0})


class _FakeStream:
    def __init__(self, events):
        self._events = events

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        for event in self._events:
            yield event


def _fake_stream_cm(tool_calls: list[tuple[str, dict]]):
    """tool_calls: [(tool_name, tool_input), ...] — each becomes its own
    sequential start/delta/stop trio with a distinct block id, same as a
    real multi-tool-call Claude response."""
    events = []
    for i, (name, tool_input) in enumerate(tool_calls):
        events.extend(_tool_use_events(f"t{i}", name, tool_input))

    @asynccontextmanager
    async def _fake(**kwargs):
        yield _FakeStream(events)
    return _fake


# Simple, side-effect-free tools (no DB writes, no server-side lookup) so
# the test isolates the cap/audit behavior from any one tool's own logic.
_HINT = ("offer_socratic_hint", {"hint_question": "What comes next?"})
_CELEBRATE = ("celebrate_discovery", {"specific_insight": "the pattern", "encouragement": "Well done!"})
_FAITH = ("connect_to_faith", {"connection": "Creation reflects order."})


@pytest.fixture
def audit_calls(monkeypatch):
    """Captures every ai_service.log_event_nowait(...) call without
    touching the DB — ai_service imports the name directly into its own
    module namespace, so it's patched there, not on core.audit."""
    calls = []
    monkeypatch.setattr(
        ai_service, "log_event_nowait",
        lambda event, **kwargs: calls.append((event, kwargs)),
    )
    return calls


async def _run_turn(tool_calls, **kwargs):
    chunks = []
    with patch.object(ai_service._client.messages, "stream", side_effect=_fake_stream_cm(tool_calls)):
        async for chunk in ai_service.stream_tutor_response(
            config=_config(), subject=Subject.morning_time, history=[],
            child_message="hello", **kwargs,
        ):
            chunks.append(chunk)
    return chunks


@pytest.mark.asyncio
async def test_calls_within_the_cap_all_execute_and_are_audited(audit_calls):
    chunks = await _run_turn([_HINT, _CELEBRATE, _FAITH])

    tool_chunks = [c for c in chunks if _json.loads(c).get("type") == "tool"]
    assert len(tool_chunks) == 3

    invoked = [c for e, c in audit_calls if e == AuditEvent.TOOL_INVOKED]
    assert len(invoked) == 3
    assert {c["detail"].split()[0] for c in invoked} == {
        "tool=offer_socratic_hint", "tool=celebrate_discovery", "tool=connect_to_faith",
    }
    assert not [e for e, _ in audit_calls if e == AuditEvent.TOOL_CALL_SUPPRESSED]


@pytest.mark.asyncio
async def test_calls_past_the_cap_are_suppressed_not_executed(audit_calls):
    cap = ai_service._MAX_TOOL_CALLS_PER_TURN
    over_by = 3
    chunks = await _run_turn([_HINT] * (cap + over_by))

    tool_chunks = [c for c in chunks if _json.loads(c).get("type") == "tool"]
    assert len(tool_chunks) == cap, "no more than the cap's worth of tool calls may ever execute"

    invoked = [e for e, _ in audit_calls if e == AuditEvent.TOOL_INVOKED]
    suppressed = [e for e, _ in audit_calls if e == AuditEvent.TOOL_CALL_SUPPRESSED]
    assert len(invoked) == cap
    assert len(suppressed) == over_by


@pytest.mark.asyncio
async def test_suppression_never_breaks_the_turn_itself(audit_calls):
    """The child must still see a clean, terminated turn — suppression is
    silent containment, never a visible error mid-lesson."""
    cap = ai_service._MAX_TOOL_CALLS_PER_TURN
    chunks = await _run_turn([_HINT] * (cap + 2))
    assert chunks, "the turn must still produce output"
    # No error/exception text leaked into what the child sees.
    assert not any("error" in c.lower() or "wrong" in c.lower() for c in chunks)


@pytest.mark.asyncio
async def test_audit_entries_carry_the_identity_context_passed_in(audit_calls):
    await _run_turn([_HINT], role="child", ip="10.0.0.7", user_agent="TestAgent/1.0")
    event, kwargs = next((e, c) for e, c in audit_calls if e == AuditEvent.TOOL_INVOKED)
    assert kwargs["role"] == "child"
    assert kwargs["ip"] == "10.0.0.7"
    assert kwargs["user_agent"] == "TestAgent/1.0"
    assert kwargs["student_name"] == "Sam"


@pytest.mark.asyncio
async def test_default_identity_context_is_safe_for_callers_that_omit_it(audit_calls):
    """Every pre-existing caller (tests, scripts/adversarial_probe.py)
    calls stream_tutor_response without role/ip/user_agent — must not
    raise, and must log something log_event() itself already treats as
    normal (ip="unknown")."""
    await _run_turn([_HINT])
    event, kwargs = next((e, c) for e, c in audit_calls if e == AuditEvent.TOOL_INVOKED)
    assert kwargs["role"] is None
    assert kwargs["ip"] == "unknown"
