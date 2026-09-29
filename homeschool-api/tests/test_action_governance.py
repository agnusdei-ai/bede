"""
The Action Validator stage of Bede's turn controller — see
services/action_governance.py and CLAUDE.md's "Bede's turn controller".

Three layers, and the middle one is the layer this repository's standing
"Test The Function AND Its Invocation" rule exists for:

1. `validate()` as a pure function — what each rule decides, given a
   situation stated rather than built.
2. **The real dispatch loop actually calling it, with the budget it was
   handed.** A governance module nothing invokes is the exact defect that
   rule was written after (`bayesian_update`'s unpassed `params`), so the
   time budget is traced from `stream_tutor_response`'s own argument
   through to a suppressed tool call, driving the real loop.
3. The prompt half (`_time_remaining_note`, `_pacing_note`) — the guidance
   that makes Bede decline gracefully, which is what a child actually
   experiences. The backstop only fires when this half did not work.
"""
import json as _json
from unittest.mock import patch

import pytest

from core.audit import AuditEvent
from models.schemas import ChatMessage, GradeStage, SessionConfig, Subject
from services import action_governance, ai_service
from services.action_governance import (
    LONG_FORM_TOOLS,
    MIN_SECONDS_FOR_LONG_FORM_TASK,
    validate,
)
from services.tool_registry import TUTOR_TOOL_SPECS, is_dispatchable_by_tutor

from tests.test_agentic_tool_loop import (  # reuse the real-loop harness
    _multi_round_stream,
    _tool_use_events,
)

# Only the four invocation tests below are async, so the asyncio mark is
# applied per test rather than to the module — a module-level mark warns
# on every sync test in the file.

_CAP = 6


def _ok(tool: str, **kw):
    return validate(tool, calls_this_turn=0, max_calls_per_turn=_CAP, **kw)


# ── 1. The pure function ─────────────────────────────────────────────────

def test_an_ordinary_call_with_budget_to_spare_is_allowed():
    for tool in TUTOR_TOOL_SPECS:
        d = _ok(tool, time_remaining_seconds=20 * 60)
        assert d.allowed, tool
        assert not d.end_loop, tool


def test_a_hallucinated_tool_name_is_refused_and_ends_the_loop():
    d = _ok("summon_dragon")
    assert not d.allowed
    assert "not_dispatchable_by_tutor" in d.reason
    assert d.end_loop


def test_the_per_turn_cap_still_bites_exactly_as_before():
    """This rule moved here from an inline check in the dispatch loop; it
    must not have changed behaviour on the way."""
    assert validate("offer_socratic_hint", calls_this_turn=_CAP - 1, max_calls_per_turn=_CAP).allowed
    over = validate("offer_socratic_hint", calls_this_turn=_CAP, max_calls_per_turn=_CAP)
    assert not over.allowed
    assert f"cap={_CAP}" in over.reason
    assert over.end_loop


def test_an_unknown_tool_is_refused_before_the_cap_is_consulted():
    """A hallucinated name must not be able to report itself as a cap
    problem, which would send a reader looking at the wrong rule."""
    d = validate("summon_dragon", calls_this_turn=_CAP, max_calls_per_turn=_CAP)
    assert "not_dispatchable_by_tutor" in d.reason
    assert "cap=" not in d.reason


@pytest.mark.parametrize("tool", sorted(LONG_FORM_TOOLS))
def test_a_long_form_task_is_refused_under_the_time_floor(tool):
    d = _ok(tool, time_remaining_seconds=MIN_SECONDS_FOR_LONG_FORM_TASK - 1)
    assert not d.allowed
    assert "time_remaining" in d.reason
    assert d.end_loop


@pytest.mark.parametrize("tool", sorted(LONG_FORM_TOOLS))
def test_a_long_form_task_is_allowed_exactly_at_the_floor(tool):
    assert _ok(tool, time_remaining_seconds=MIN_SECONDS_FOR_LONG_FORM_TASK).allowed


def test_a_short_task_is_never_refused_for_time():
    """A hint, a celebration, a picture, a faith connection are read in
    place. Refusing those near the end of a block would leave Bede unable
    to answer at all, which is worse than the ending it would prevent."""
    for tool in TUTOR_TOOL_SPECS:
        if tool in LONG_FORM_TOOLS:
            continue
        assert _ok(tool, time_remaining_seconds=0).allowed, tool


def test_an_absent_budget_disables_the_time_rule_entirely():
    """Older clients, the sandbox and every existing test pass no budget.
    None must mean "unknown", never "assume the worst" — otherwise adding
    this field would silently stop narration working for them."""
    for tool in sorted(LONG_FORM_TOOLS):
        assert _ok(tool, time_remaining_seconds=None).allowed, tool
        assert _ok(tool).allowed, tool


def test_every_long_form_tool_is_a_real_tutor_tool():
    """A name in this set that no longer matches a tool would be a rule
    guarding nothing, and would read as though it still did."""
    for tool in LONG_FORM_TOOLS:
        assert is_dispatchable_by_tutor(tool), tool


# ── 2. The invocation: the real loop calls it with the real budget ───────

def _config(**kw) -> SessionConfig:
    base = dict(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery)
    base.update(kw)
    return SessionConfig(**base)


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


@pytest.fixture
def audit_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ai_service, "log_event_nowait",
        lambda event, **kw: calls.append((event, kw)),
    )
    return calls


_NARRATION = ("request_narration", {"prompt": "Tell me what you remember."})


@pytest.mark.asyncio
async def test_the_loop_passes_its_time_budget_to_the_validator(audit_calls):
    """Traces the value from stream_tutor_response's own argument to the
    validator, by watching a real call rather than reading the source."""
    seen = []
    real = action_governance.validate

    def _spy(tool_name, **kw):
        seen.append((tool_name, kw))
        return real(tool_name, **kw)

    rounds = [(list(_tool_use_events("t0", *_NARRATION)), "end_turn")]
    with patch.object(action_governance, "validate", _spy):
        await _run_turn(rounds, time_remaining_seconds=42)

    assert seen, "the dispatch loop never consulted the Action Validator at all"
    tool_name, kw = seen[0]
    assert tool_name == "request_narration"
    assert kw["time_remaining_seconds"] == 42, (
        "the budget did not reach the validator — the rule is unreachable "
        "from the only path that uses it"
    )
    assert kw["max_calls_per_turn"] == ai_service._MAX_TOOL_CALLS_PER_TURN


@pytest.mark.asyncio
async def test_a_narration_proposed_with_no_time_left_never_reaches_the_child(audit_calls):
    rounds = [(list(_tool_use_events("t0", *_NARRATION)), "end_turn")]
    chunks, _ = await _run_turn(rounds, time_remaining_seconds=30)

    assert not [c for c in chunks if c["type"] == "tool"], (
        "the narration card was rendered despite the block being nearly over"
    )
    suppressed = [kw for e, kw in audit_calls if e == AuditEvent.TOOL_CALL_SUPPRESSED]
    assert len(suppressed) == 1
    assert "time_remaining=30s" in suppressed[0]["detail"]
    assert chunks[-1] == {"type": "done"}, "the turn must still close cleanly"


@pytest.mark.asyncio
async def test_the_same_narration_goes_through_with_the_block_ahead(audit_calls):
    """The complement, so the test above cannot pass by suppressing
    everything: the only difference is the clock."""
    rounds = [(list(_tool_use_events("t0", *_NARRATION)), "end_turn")]
    chunks, _ = await _run_turn(rounds, time_remaining_seconds=20 * 60)

    assert [c for c in chunks if c["type"] == "tool"], "narration should have rendered"
    assert not [e for e, _ in audit_calls if e == AuditEvent.TOOL_CALL_SUPPRESSED]


@pytest.mark.asyncio
async def test_no_budget_behaves_exactly_as_before_this_stage_existed(audit_calls):
    rounds = [(list(_tool_use_events("t0", *_NARRATION)), "end_turn")]
    chunks, _ = await _run_turn(rounds)
    assert [c for c in chunks if c["type"] == "tool"]
    assert not [e for e, _ in audit_calls if e == AuditEvent.TOOL_CALL_SUPPRESSED]


# ── 3. The prompt half ───────────────────────────────────────────────────

def test_the_time_note_is_silent_with_plenty_of_time_and_when_unknown():
    assert ai_service._time_remaining_note(None) == ""
    assert ai_service._time_remaining_note(20 * 60) == ""
    assert ai_service._time_remaining_note(MIN_SECONDS_FOR_LONG_FORM_TASK) == ""


def test_the_time_note_fires_under_the_floor_and_names_no_clock_to_the_child():
    note = ai_service._time_remaining_note(90)
    assert "<time_remaining>" in note
    assert "narration" in note.lower()
    # The standing rule: never hurry a child, and never put the clock in
    # front of them. The note must instruct Bede to keep it to itself.
    assert "never mention the clock" in note.lower()
    assert "never tell the child to hurry" in note.lower()


def test_the_time_note_never_goes_negative_in_its_wording():
    assert "-" not in ai_service._time_remaining_note(0).split("<time_remaining>")[1][:80]


def _assistant(text: str) -> ChatMessage:
    return ChatMessage(role="assistant", content=text)


def _child(text: str = "um") -> ChatMessage:
    return ChatMessage(role="user", content=text)


def test_follow_up_depth_counts_consecutive_questions():
    history = [
        _assistant("What do you notice?"), _child(),
        _assistant("And why might that be?"), _child(),
    ]
    assert ai_service._consecutive_question_turns(history) == 2


def test_a_hint_resets_the_follow_up_depth():
    """A hint is Bede giving ground, so the thread starts again — which is
    why a lesson going well never accumulates a depth."""
    history = [
        _assistant("What do you notice?"), _child(),
        _assistant(ai_service._HINT_CARD_PREFIX + "Let me ask it this way: what colour?"), _child(),
        _assistant("So what happens next?"), _child(),
    ]
    assert ai_service._consecutive_question_turns(history) == 1


def test_a_celebration_resets_the_follow_up_depth():
    history = [
        _assistant("What do you notice?"), _child(),
        _assistant(ai_service._CELEBRATION_CARD_PREFIX + "Well done! I noticed you saw that."), _child(),
    ]
    assert ai_service._consecutive_question_turns(history) == 0


def test_a_turn_with_no_question_ends_the_count():
    history = [
        _assistant("Here is how a mill works."), _child(),
        _assistant("What do you notice?"), _child(),
    ]
    assert ai_service._consecutive_question_turns(history) == 1


def test_no_history_is_zero_depth():
    assert ai_service._consecutive_question_turns(None) == 0
    assert ai_service._consecutive_question_turns([]) == 0


def test_the_pacing_note_is_silent_while_the_thread_is_healthy():
    one = [_assistant("What do you notice?"), _child()]
    assert ai_service._pacing_note(one, GradeStage.core_mastery) == ""
    assert ai_service._pacing_note([], GradeStage.core_mastery) == ""


def test_the_pacing_note_fires_at_the_limit_and_offers_real_alternatives():
    history = [
        _assistant("What do you notice?"), _child(),
        _assistant("And why might that be?"), _child(),
    ]
    note = ai_service._pacing_note(history, GradeStage.core_mastery)
    assert "<pacing>" in note
    assert "offer_socratic_hint" in note
    assert "Do NOT ask another question" in note


def test_k2_reaches_the_pacing_limit_a_round_sooner_than_older_children():
    """_STAGE_GUIDANCE already tightens the follow-up cap for K-2; the
    computed note has to honour the same split rather than applying one
    number to every child."""
    one_round = [_assistant("What do you notice?"), _child()]
    assert ai_service._pacing_note(one_round, GradeStage.foundations) != ""
    assert ai_service._pacing_note(one_round, GradeStage.core_mastery) == ""
    assert ai_service._pacing_note(one_round, GradeStage.independent) == ""
