"""One lesson turn records each piece of the child's work once, however many
times the tablet sends it — see services/turn_replay.py.

Three layers, for this repository's "Test The Function AND Its Invocation"
rule: the gate on its own; the real tutor dispatch loop claiming every save
through it; and the chat route building a gate from the request's turn id.
The second and third are the point: a gate nothing consults would leave every
test of the gate green and every retried turn still recorded twice.

The failure cases are the ones a per-turn claim got wrong: a first save that
fails, a turn that drops between two saves, two attempts racing on one save,
and a retry whose model answers differently.
"""
import asyncio
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


def _gate(turn="t1", owner="child:Sam"):
    return turn_replay.gate_for(owner, turn)


async def _save(gate, name, ok=True, result=True):
    """One save through the gate: (did it run, what it returned or was handed)."""
    claim = await gate.claim(name)
    if not claim.allowed:
        return False, claim.prior
    claim.finish(ok, result if ok else None)
    return True, result


# ── 1. The gate ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_turn_id_saves_on_every_attempt_as_before():
    for _ in range(3):
        assert (await _save(turn_replay.gate_for("child:Sam", None), "assess_narration"))[0]
    assert (await _save(turn_replay.always_record(), "assess_narration"))[0]


@pytest.mark.asyncio
async def test_a_saved_effect_is_not_saved_again_by_a_retry():
    assert (await _save(_gate(), "assess_narration"))[0]
    assert not (await _save(_gate(), "assess_narration"))[0]


@pytest.mark.asyncio
async def test_a_failed_first_save_leaves_the_effect_for_the_retry():
    """The case a per-turn claim lost: attempt 1 tried and failed."""
    assert (await _save(_gate(), "assess_narration", ok=False))[0]
    assert (await _save(_gate(), "assess_narration"))[0], "the retry was blocked from saving unsaved work"


@pytest.mark.asyncio
async def test_a_turn_that_dropped_between_saves_lets_the_retry_finish_the_rest():
    """Attempt 1 saved the skill evidence, then the connection dropped before
    the narration. The retry skips the first and saves the second."""
    first = _gate()
    assert (await _save(first, "record_skill_evidence:probe.add_within_10"))[0]
    retry = _gate()
    assert not (await _save(retry, "record_skill_evidence:probe.add_within_10"))[0]
    assert (await _save(retry, "assess_narration"))[0]


@pytest.mark.asyncio
async def test_a_cancelled_save_releases_the_effect():
    """The child's connection dropped mid-save: the server task is cancelled."""
    first = _gate()
    claim = await first.claim("assess_narration")

    async def _cancelled():
        try:
            await asyncio.sleep(10)
        finally:
            claim.finish(False)

    task = asyncio.create_task(_cancelled())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await _save(_gate(), "assess_narration"))[0]


@pytest.mark.asyncio
async def test_two_attempts_racing_on_one_save_write_it_once():
    """A retry that arrives while the first attempt is mid-save waits for it,
    then skips the save it completed."""
    first = _gate()
    claim = await first.claim("assess_narration")
    retry_result = asyncio.create_task(_save(_gate(), "assess_narration"))
    await asyncio.sleep(0.01)
    assert not retry_result.done(), "the retry did not wait for the save in progress"
    claim.finish(True, {"total_score": 13})
    ran, prior = await retry_result
    assert not ran and prior == {"total_score": 13}


@pytest.mark.asyncio
async def test_a_racing_save_that_fails_is_then_saved_by_the_waiting_retry():
    first = _gate()
    claim = await first.claim("assess_narration")
    retry_result = asyncio.create_task(_save(_gate(), "assess_narration"))
    await asyncio.sleep(0.01)
    claim.finish(False)
    ran, _ = await retry_result
    assert ran, "the waiting retry did not save after the first attempt failed"


@pytest.mark.asyncio
async def test_the_retry_is_handed_what_was_saved_not_its_own_value():
    await _save(_gate(), "assess_narration", result={"total_score": 13})
    ran, prior = await _save(_gate(), "assess_narration", result={"total_score": 7})
    assert not ran and prior == {"total_score": 13}


@pytest.mark.asyncio
async def test_a_different_skill_in_the_retry_is_a_different_effect():
    await _save(_gate(), turn_replay.effect_name("record_skill_evidence", {"probe_id": "probe.a"}))
    assert (await _save(_gate(), turn_replay.effect_name("record_skill_evidence", {"probe_id": "probe.b"})))[0]
    # The same skill with a different outcome is the same effect: the child answered once.
    assert not (await _save(_gate(), turn_replay.effect_name(
        "record_skill_evidence", {"probe_id": "probe.a", "outcome": "incorrect"})))[0]


@pytest.mark.asyncio
async def test_one_attempt_may_save_the_same_effect_twice_and_a_second_failure_keeps_the_first():
    gate = _gate()
    assert (await _save(gate, "behavior_check"))[0]
    assert (await _save(gate, "behavior_check", ok=False))[0]
    assert not (await _save(_gate(), "behavior_check"))[0], "a failed second save erased the first"


@pytest.mark.asyncio
async def test_another_caller_cannot_suppress_a_save_by_sending_its_turn_id():
    await _save(_gate(owner="child:Ada"), "assess_narration")
    assert (await _save(_gate(owner="child:Sam"), "assess_narration"))[0]


@pytest.mark.asyncio
async def test_a_claim_expires(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(turn_replay.time, "monotonic", lambda: now[0])
    await _save(_gate(), "assess_narration")
    now[0] += turn_replay.CLAIM_TTL_SECONDS + 1
    assert (await _save(_gate(), "assess_narration"))[0]


@pytest.mark.asyncio
async def test_the_turn_table_is_bounded(monkeypatch):
    monkeypatch.setattr(turn_replay, "MAX_TURNS", 10)
    for i in range(50):
        await _save(_gate(turn=f"t{i}"), "assess_narration")
    assert len(turn_replay._turns) <= 11


def test_effect_names_follow_what_is_recorded():
    assert turn_replay.effect_name("record_skill_evidence", {"probe_id": "probe.x"}) == "record_skill_evidence:probe.x"
    assert turn_replay.effect_name("record_phonics_evidence", {"domain": "cvc_blending"}) == "record_phonics_evidence:cvc_blending"
    assert turn_replay.effect_name("record_language_evidence", {"language": "latin"}) == "record_language_evidence:latin"
    assert turn_replay.effect_name("assess_narration", {"completeness": 3}) == "assess_narration"


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


# ── 2. The real dispatch loop claims every save ──────────────────────────

_SKILL = ("record_skill_evidence", {"probe_id": "probe.add_within_10", "outcome": "correct"})
_ASSESS = ("assess_narration", {
    "completeness": 3, "sequence": 3, "detail": 2, "language_quality": 3, "synthesis": 2,
    "adaptive_signal": "steady", "bede_observation": "Told it in order.",
})


async def _attempt(gate, assess=_ASSESS):
    rounds = [
        (list(_tool_use_events("t0", *_SKILL)) + list(_tool_use_events("t1", *assess)), "tool_use"),
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
    """Replace the save functions with ones that record the call and report
    success or failure as told."""
    state = {"calls": [], "fail": set()}

    async def _skill(*a, **k):
        state["calls"].append("skill")
        return "skill" not in state["fail"]

    async def _assess(db, student, subject, tool_input):
        state["calls"].append("assess")
        if "assess" in state["fail"]:
            return None
        return ai_service._assessment_summary(subject, tool_input)

    monkeypatch.setattr(ai_service, "_record_skill_evidence", _skill)
    monkeypatch.setattr(ai_service, "_save_assessment", _assess)
    monkeypatch.setattr(ai_service, "log_event_nowait", lambda *a, **k: None)
    return state


@pytest.mark.asyncio
async def test_a_retried_turn_records_its_work_once(writes):
    await _attempt(_gate("turn-1"))
    retry = await _attempt(_gate("turn-1"))
    assert writes["calls"] == ["skill", "assess"], f"the retry recorded the child's work again: {writes['calls']}"
    assert any(c.get("content") == "Well told." for c in retry), "the child was not answered on the retry"
    assert retry[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_a_retry_saves_what_the_first_attempt_failed_to(writes):
    writes["fail"].add("assess")
    await _attempt(_gate("turn-1"))
    writes["fail"].clear()
    await _attempt(_gate("turn-1"))
    assert writes["calls"] == ["skill", "assess", "assess"], writes["calls"]


@pytest.mark.asyncio
async def test_a_retry_reports_the_saved_narration_never_its_own(writes):
    """The retry's model scored the narration differently. The screen and the
    model must be told about the scores that were saved."""
    await _attempt(_gate("turn-1"))
    rescored = ("assess_narration", {**_ASSESS[1], "completeness": 1, "synthesis": 1})
    retry = await _attempt(_gate("turn-1"), assess=rescored)
    shown = [c["data"] for c in retry if c.get("type") == "assessment"]
    assert shown == [{"subject": "mathematics", "total_score": 13, "adaptive_signal": "steady"}], shown


@pytest.mark.asyncio
async def test_without_a_turn_id_every_attempt_records_as_before(writes):
    await _attempt(None)
    await _attempt(None)
    assert writes["calls"] == ["skill", "assess", "skill", "assess"]


@pytest.mark.asyncio
async def test_two_different_turns_each_record(writes):
    await _attempt(_gate("turn-1"))
    await _attempt(_gate("turn-2"))
    assert writes["calls"] == ["skill", "assess", "skill", "assess"]


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
    assert (await _save(first, "assess_narration"))[0]
    assert not (await _save(retry, "assess_narration"))[0], "a retry of the same turn saved again"


@pytest.mark.asyncio
async def test_the_route_keys_the_gate_by_student(monkeypatch):
    assert (await _save(await _route_gate(monkeypatch, "Sam", "turn-9"), "assess_narration"))[0]
    assert (await _save(await _route_gate(monkeypatch, "Ada", "turn-9"), "assess_narration"))[0]


@pytest.mark.asyncio
async def test_the_route_without_a_turn_id_records_as_before(monkeypatch):
    gate = await _route_gate(monkeypatch, "Sam", None)
    assert gate is not None and not gate.tracked


# ── The learning-style counter, built from two styles ────────────────────
# Needs a db for the style to load, so every reader the stream consults is
# replaced with a stated value.

_HANDWRITING_STRUCTURED = ("invite_handwriting", {"prompt": "Draw the plant.", "elements": ["root", "stem"]})
_HANDWRITING_PLAIN = ("invite_handwriting", {"prompt": "Write what happened first."})


async def _handwriting_attempt(monkeypatch, style, call, gate):
    from unittest.mock import AsyncMock, MagicMock

    import core.api_usage as api_usage

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
    # Usage logging opens its own database session; keep it off any real one.
    monkeypatch.setattr(api_usage, "record_usage", _none)
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
        return True

    monkeypatch.setattr(ai_service, "_increment_behavior_check", _count)
    monkeypatch.setattr(ai_service, "log_event_nowait", lambda *a, **k: None)
    await _handwriting_attempt(monkeypatch, style, call, _gate("turn-h"))
    await _handwriting_attempt(monkeypatch, style, call, _gate("turn-h"))
    assert counted == ["Sam"], f"{style}: counted {len(counted)} times for one turn"


# ── The save functions report whether they saved ─────────────────────────

@pytest.mark.asyncio
async def test_a_save_outside_its_subject_reports_nothing_saved():
    cfg = SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery)
    assert await ai_service._record_skill_evidence(None, None, cfg, Subject.science, dict(_SKILL[1])) is False
    assert await ai_service._increment_behavior_check(None, "Sam") is False


@pytest.mark.asyncio
async def test_a_save_that_raises_reports_nothing_saved():
    from unittest.mock import AsyncMock, MagicMock

    db = MagicMock()
    db.execute = AsyncMock(side_effect=RuntimeError("database went away"))
    assert await ai_service._increment_behavior_check(db, "Sam") is False
