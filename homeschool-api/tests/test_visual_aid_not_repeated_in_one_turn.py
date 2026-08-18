"""
One turn must never put the same picture on screen twice.

## The bug this pins

Reported against Art & Music during the beta: the same painting card
rendered up to three times in a row, each with a "Picture unavailable
right now" placeholder. The repeat came from the bounded tool_result loop
(_MAX_TOOL_LOOP_ROUNDS in services/ai_service.py):

* `show_visual_aid` is registered ``reactable`` (services/tool_registry.py)
  so that a hallucinated `visual_aid_id` can be recovered from in the same
  turn. That flag is not conditional on the outcome, so a SUCCESSFUL
  lookup also buys another model round-trip.
* Each of those extra rounds re-sends the SAME cached system block. That
  block carries `_get_visual_aids_context`'s "[ALREADY SHOWN this session]"
  marking, but it is computed once per turn from conversation HISTORY —
  so a picture shown seconds earlier, in round 1 of the very same turn, is
  still listed to the model as un-shown.
* The tool_result was `{"found": true, ...}`, which says nothing about
  having already displayed it.

So the model had both the opportunity and no signal against taking it, and
against a six-entry art catalog reaching for the same painting again is the
likely case rather than the unlucky one. Nothing downstream deduplicated:
`visual_aid` chunks are appended raw by both frontends, unlike `tool`
chunks which pass through isDuplicateUtterance.

`tests/test_visual_aids_already_shown.py` is the sibling guard BETWEEN
turns. It is structurally incapable of covering this case, which is why
this file exists rather than a case being added there.

## The boundary that matters

Suppression is scoped to the TURN and must never become session-wide.
Charlotte Mason picture study is look → put away → narrate, and showing a
picture again in a later turn is the method working, not a bug.
"""
import json as _json
from unittest.mock import patch

import pytest

from models.schemas import GradeStage, SessionConfig, Subject, TermSchedule
from services import ai_service
from tests.test_agentic_tool_loop import (
    _multi_round_stream,
    _text_events,
    _tool_use_events,
)

pytestmark = pytest.mark.asyncio

# Term 4 / quarterly puts Raphael in rotation, so both ids below are real
# catalog entries — same reasoning as test_visual_aids_already_shown.py.
AID = "raphael_sistine_madonna"
OTHER_AID = "raphael_school_of_athens"


def _config() -> SessionConfig:
    return SessionConfig(
        student_name="Emma", grade="6", grade_stage=GradeStage.independent,
        term_schedule=TermSchedule.quarterly, current_term=4,
    )


def _show(aid_id: str):
    return ("show_visual_aid", {"visual_aid_id": aid_id})


async def _run(rounds, monkeypatch):
    """Drive one full turn and return (parsed chunks, rounds consumed)."""
    monkeypatch.setattr(ai_service, "log_event_nowait", lambda event, **kw: None)
    fake, state = _multi_round_stream(rounds)
    chunks = []
    with patch.object(ai_service._client.messages, "stream", side_effect=fake):
        async for raw in ai_service.stream_tutor_response(
            config=_config(), subject=Subject.art_music, history=[],
            child_message="hello",
        ):
            chunks.append(_json.loads(raw))
    return chunks, state["i"]


def _aid_ids(chunks):
    return [c["visualAid"]["id"] for c in chunks if c.get("type") == "visual_aid"]


async def test_the_same_aid_requested_every_round_is_shown_exactly_once(monkeypatch):
    """The reported bug, reduced: the model asks for the same painting in
    all three rounds the loop allows. Before the fix this yielded three
    identical cards."""
    rounds = [(list(_tool_use_events(f"t{i}", *_show(AID))), "tool_use") for i in range(3)]
    rounds.append((list(_text_events("What do you notice?")), "end_turn"))

    chunks, _ = await _run(rounds, monkeypatch)

    assert _aid_ids(chunks) == [AID]


async def test_a_repeat_request_is_answered_as_found_not_as_a_failure(monkeypatch):
    """A suppressed repeat must not read to the model as a miss. `found`
    stays true — the picture is real and is on screen — and `already_shown`
    carries the fact it could not otherwise have. Telling it `found: false`
    would send it hunting for a different id to fix a failure that never
    happened."""
    rounds = [
        (list(_tool_use_events("t0", *_show(AID))), "tool_use"),
        (list(_tool_use_events("t1", *_show(AID))), "tool_use"),
        (list(_text_events("Look at her face.")), "end_turn"),
    ]
    monkeypatch.setattr(ai_service, "log_event_nowait", lambda event, **kw: None)

    fake, _ = _multi_round_stream(rounds)
    sent_messages = []

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _recording(**kwargs):
        # Deep-copied by json round-trip: `messages` is mutated in place
        # across rounds, so holding the reference would show every round
        # the final state rather than what that round actually received.
        sent_messages.append(_json.loads(_json.dumps(kwargs.get("messages"), default=str)))
        async with fake(**kwargs) as stream:
            yield stream

    with patch.object(ai_service._client.messages, "stream", side_effect=_recording):
        async for _ in ai_service.stream_tutor_response(
            config=_config(), subject=Subject.art_music, history=[],
            child_message="hello",
        ):
            pass

    # Round 3's request carries the tool_result produced for round 2's
    # repeated call — the payload the model actually reads. Parsed rather
    # than substring-matched: the payload is a JSON string nested inside
    # the message JSON, so a naive `in` check passes or fails on escaping
    # rather than on content.
    payloads = [
        _json.loads(block["content"])
        for message in sent_messages[-1]
        if isinstance(message.get("content"), list)
        for block in message["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    repeats = [p for p in payloads if p.get("already_shown")]
    assert len(repeats) == 1, f"expected exactly one suppressed repeat, got {payloads}"
    assert repeats[0]["found"] is True
    assert repeats[0]["visual_aid_id"] == AID
    # The model is told what it could not otherwise know, in words.
    assert "already showed this picture" in repeats[0]["note"]


async def test_a_different_aid_in_a_later_round_is_still_shown(monkeypatch):
    """Suppression is per-picture, not "one aid per turn" — asking for a
    genuinely different painting must still reach the child."""
    rounds = [
        (list(_tool_use_events("t0", *_show(AID))), "tool_use"),
        (list(_tool_use_events("t1", *_show(OTHER_AID))), "tool_use"),
        (list(_text_events("Compare the two.")), "end_turn"),
    ]

    chunks, _ = await _run(rounds, monkeypatch)

    assert _aid_ids(chunks) == [AID, OTHER_AID]


async def test_two_calls_for_one_aid_in_the_SAME_round_also_collapse(monkeypatch):
    """The loop is the reported cause, but not the only route to a repeat:
    a single round can contain two tool_use blocks. Suppression keyed on
    what has been emitted covers both without needing to know which
    happened."""
    rounds = [
        (
            list(_tool_use_events("t0", *_show(AID)))
            + list(_tool_use_events("t1", *_show(AID))),
            "tool_use",
        ),
        (list(_text_events("What stands out?")), "end_turn"),
    ]

    chunks, _ = await _run(rounds, monkeypatch)

    assert _aid_ids(chunks) == [AID]


async def test_suppression_does_not_leak_between_turns(monkeypatch):
    """The load-bearing boundary. Picture study is look → put away →
    narrate; re-showing a picture in a LATER turn is the method working.
    Two independent turns must each render the aid."""
    for _ in range(2):
        rounds = [
            (list(_tool_use_events("t0", *_show(AID))), "tool_use"),
            (list(_text_events("Tell me what you remember.")), "end_turn"),
        ]
        chunks, _ = await _run(rounds, monkeypatch)
        assert _aid_ids(chunks) == [AID]
