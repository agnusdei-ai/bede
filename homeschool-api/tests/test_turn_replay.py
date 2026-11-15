"""One lesson turn records the child's work once, however many times the
tablet sends it — see services/turn_replay.py.

Three layers, for this repository's "Test The Function AND Its Invocation"
rule: the gate on its own; the real tutor dispatch loop asking it before
every write; and the chat route actually building a gate from the request's
turn id. The second and third are the point. A gate nothing consults would
leave every test of the gate green and every retried turn still recorded
twice.
"""
import json as _json
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from models.schemas import GradeStage, SessionConfig, Subject, TutorRequest
from services import ai_service, turn_replay
from tests.test_agentic_tool_loop import _multi_round_stream, _text_events, _tool_use_events


@pytest.fixture(autouse=True)
def _fresh_claims():
    turn_replay._reset_for_tests()
    yield
    turn_replay._reset_for_tests()


# ── 1. The gate ──────────────────────────────────────────────────────────

def test_no_turn_id_records_on_every_attempt_as_before():
    assert turn_replay.gate_for("child:Sam", None).may_record()
    assert turn_replay.gate_for("child:Sam", None).may_record()
    assert turn_replay.always_record().may_record()


def test_only_the_first_attempt_to_write_records():
    first = turn_replay.gate_for("child:Sam", "t1")
    retry = turn_replay.gate_for("child:Sam", "t1")
    assert first.may_record()
    assert not retry.may_record()


def test_the_winning_attempt_keeps_recording_for_the_rest_of_its_turn():
    """A turn often records several things (evidence, then a narration's
    scores). Claiming must not stop the claimant's own second write."""
    first = turn_replay.gate_for("child:Sam", "t1")
    assert first.may_record() and first.may_record() and first.may_record()


def test_an_attempt_that_never_wrote_does_not_block_the_retry():
    """The claim is taken at the first WRITE. An attempt that failed before
    saving anything must leave the retry free to save the child's work."""
    turn_replay.gate_for("child:Sam", "t1")  # created, never asked
    assert turn_replay.gate_for("child:Sam", "t1").may_record()


def test_another_caller_cannot_suppress_a_turn_by_sending_its_id():
    assert turn_replay.gate_for("child:Ada", "t1").may_record()
    assert turn_replay.gate_for("child:Sam", "t1").may_record()


def test_a_claim_expires(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(turn_replay.time, "monotonic", lambda: now[0])
    assert turn_replay.gate_for("child:Sam", "t1").may_record()
    now[0] += turn_replay.CLAIM_TTL_SECONDS + 1
    assert turn_replay.gate_for("child:Sam", "t1").may_record()


def test_the_claim_table_is_bounded(monkeypatch):
    monkeypatch.setattr(turn_replay, "MAX_CLAIMS", 10)
    for i in range(50):
        turn_replay.gate_for("child:Sam", f"t{i}").may_record()
        turn_replay.gate_for("child:Sam", f"x{i}").may_record()
    assert len(turn_replay._claims) <= 11


def test_the_turn_id_is_a_plain_token():
    base = dict(
        session_config=SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery),
        current_subject=Subject.science, conversation_history=[], child_message="hi",
    )
    assert TutorRequest(**base, turn_id="a1b2-C3_d4").turn_id == "a1b2-C3_d4"
    assert TutorRequest(**base).turn_id is None
    for bad in ("has space", "x" * 65, "semi;colon", "\x1fsep"):
        with pytest.raises(ValidationError):
            TutorRequest(**base, turn_id=bad)


# ── 2. The real dispatch loop asks the gate before every write ───────────

_SKILL = ("record_skill_evidence", {"skill_id": "add_within_10", "outcome": "correct"})
_ASSESS = ("assess_narration", {
    "completeness": 3, "sequence": 3, "detail": 2, "language_quality": 3, "synthesis": 2,
    "adaptive_signal": "steady", "bede_observation": "Told it in order.",
})


async def _attempt(gate):
    rounds = [
        (list(_tool_use_events("t0", *_SKILL)) + list(_tool_use_events("t1", *_ASSESS)), "tool_use"),
        (list(_text_events("Well told.")), "end_turn"),
    ]
    fake, _ = _multi_round_stream(rounds)
    chunks = []
    with patch.object(ai_service._client.messages, "stream", side_effect=fake):
        async for chunk in ai_service.stream_tutor_response(
            config=SessionConfig(student_name="Sam", grade="1", grade_stage=GradeStage.foundations),
            subject=Subject.mathematics, history=[], child_message="It was 7.",
            evidence_gate=gate,
        ):
            chunks.append(_json.loads(chunk))
    return chunks


@pytest.fixture
def writes(monkeypatch):
    calls = []

    async def _skill(*a, **k):
        calls.append("skill")

    async def _assess(db, student, subject, tool_input):
        calls.append("assess")
        return ai_service._assessment_summary(subject, tool_input)

    monkeypatch.setattr(ai_service, "_record_skill_evidence", _skill)
    monkeypatch.setattr(ai_service, "_save_assessment", _assess)
    monkeypatch.setattr(ai_service, "log_event_nowait", lambda *a, **k: None)
    return calls


@pytest.mark.asyncio
async def test_a_retried_turn_records_its_work_once(writes):
    first = await _attempt(turn_replay.gate_for("child:Sam", "turn-1"))
    retry = await _attempt(turn_replay.gate_for("child:Sam", "turn-1"))

    assert writes == ["skill", "assess"], (
        f"the retry recorded the child's work again: {writes}"
    )
    # The child is still answered in full on the retry.
    assert any(c.get("content") == "Well told." for c in retry)
    assert first[-1] == retry[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_without_a_turn_id_every_attempt_records_as_before(writes):
    await _attempt(None)
    await _attempt(None)
    assert writes == ["skill", "assess", "skill", "assess"]


@pytest.mark.asyncio
async def test_two_different_turns_each_record(writes):
    await _attempt(turn_replay.gate_for("child:Sam", "turn-1"))
    await _attempt(turn_replay.gate_for("child:Sam", "turn-2"))
    assert writes == ["skill", "assess", "skill", "assess"]


def test_the_narration_summary_is_the_same_whether_saved_or_not():
    """A retry answers the model with the summary, without saving; it must
    be the same summary the save would have returned."""
    s = ai_service._assessment_summary(Subject.history, _ASSESS[1])
    assert s == {"subject": "history", "total_score": 13, "adaptive_signal": "steady"}


# ── 3. The chat route builds the gate from the request ───────────────────

def _request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 1), "headers": [(b"user-agent", b"pytest")]})


async def _route_gate(monkeypatch, student: str, turn_id):
    import routers.tutor as tutor_module

    seen = {}

    async def _capture(*a, **kw):
        seen["gate"] = kw.get("evidence_gate")
        yield _json.dumps({"type": "done"})

    monkeypatch.setattr(tutor_module, "stream_tutor_response", _capture)
    monkeypatch.setattr(tutor_module, "log_event_nowait", lambda *a, **k: None)
    req = TutorRequest(
        session_config=SessionConfig(student_name=student, grade="4", grade_stage=GradeStage.core_mastery),
        current_subject=Subject.science, conversation_history=[], child_message="Roots drink water.",
        turn_id=turn_id,
    )
    response = await tutor_module.chat(req, _request(), auth={"role": "parent"}, db=None)
    [c async for c in response.body_iterator]
    return seen["gate"]


@pytest.mark.asyncio
async def test_the_route_hands_the_stream_a_gate_built_from_the_turn_id(monkeypatch):
    first = await _route_gate(monkeypatch, "Sam", "turn-9")
    retry = await _route_gate(monkeypatch, "Sam", "turn-9")
    assert first is not None and first.tracked, "the route never passed a gate"
    assert first.may_record()
    assert not retry.may_record(), "a retry of the same turn was allowed to record"


@pytest.mark.asyncio
async def test_the_route_keys_the_gate_by_student(monkeypatch):
    assert (await _route_gate(monkeypatch, "Sam", "turn-9")).may_record()
    assert (await _route_gate(monkeypatch, "Ada", "turn-9")).may_record()


@pytest.mark.asyncio
async def test_the_route_without_a_turn_id_records_as_before(monkeypatch):
    gate = await _route_gate(monkeypatch, "Sam", None)
    assert gate is not None and not gate.tracked
    assert gate.may_record()


# The learning-style counter has its own condition, built from two styles;
# a retry must not count either one twice. Needs a db for the style to load,
# so every reader the stream consults is replaced with a stated value.

_HANDWRITING_STRUCTURED = ("invite_handwriting", {"prompt": "Draw the plant.", "elements": ["root", "stem"]})
_HANDWRITING_PLAIN = ("invite_handwriting", {"prompt": "Write what happened first."})


async def _handwriting_attempt(monkeypatch, style, call, gate):
    from unittest.mock import AsyncMock, MagicMock

    async def _none(*a, **k):
        return None

    async def _pair(*a, **k):
        return None, 0

    async def _style(*a, **k):
        return style

    monkeypatch.setattr(ai_service, "_load_processing_style_readonly", _style)
    monkeypatch.setattr(ai_service, "_load_mastery_vector_readonly", _pair)
    monkeypatch.setattr(ai_service, "_load_music_vector_readonly", _pair)
    monkeypatch.setattr(ai_service, "_load_lesson_bookmark_readonly", _none)
    import core.api_usage as api_usage

    async def _no_usage(*a, **k):
        return None

    # Usage logging opens its own database session; keep it off any real one.
    monkeypatch.setattr(api_usage, "record_usage", _no_usage)
    db = MagicMock()
    db.execute = AsyncMock(side_effect=RuntimeError("no database in this test"))
    rounds = [(list(_tool_use_events("t0", *call)), "end_turn")]
    fake, _ = _multi_round_stream(rounds)
    with patch.object(ai_service._client.messages, "stream", side_effect=fake):
        async for _ in ai_service.stream_tutor_response(
            config=SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery),
            subject=Subject.science, history=[], child_message="It has roots.",
            db=db, evidence_gate=gate,
        ):
            pass


@pytest.mark.asyncio
@pytest.mark.parametrize("style,call", [
    ("kinesthetic", _HANDWRITING_STRUCTURED),
    ("reading_writing", _HANDWRITING_PLAIN),
])
async def test_a_retry_does_not_count_the_learning_style_twice(monkeypatch, style, call):
    counted = []

    async def _count(db, student):
        counted.append(student)

    monkeypatch.setattr(ai_service, "_increment_behavior_check", _count)
    monkeypatch.setattr(ai_service, "log_event_nowait", lambda *a, **k: None)
    await _handwriting_attempt(monkeypatch, style, call, turn_replay.gate_for("child:Sam", "turn-h"))
    await _handwriting_attempt(monkeypatch, style, call, turn_replay.gate_for("child:Sam", "turn-h"))
    assert counted == ["Sam"], f"{style}: counted {len(counted)} times for one turn"
