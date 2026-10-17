"""G1: an educator's tutoring turn re-validates its grant before context
retrieval, before every chunk it releases, before every durable write, and
periodically while generation is silent. Revocation cancels output and later
writes, and leaves an audit event. A retry is a fresh request and is refused.

Real HTTP and real SSE through the assembled app (tests/g1_harness.py),
through the REAL stream_tutor_response. Only the model client is a fake: a
scripted stream that pauses on a gate the test controls, and emits a real
record_skill_evidence tool call whose write goes through the real diagnostic
and work-ledger code. Moderation is stubbed to "not flagged".

Educator tutoring exists only in single-household (legacy) mode; in campus
mode it is disabled and every attempt is a 404 (asserted below).
"""
import asyncio
import json
import weakref
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from anthropic.types import RawContentBlockDeltaEvent, RawContentBlockStartEvent, RawContentBlockStopEvent

import routers.tutor as tutor_router
import services.pilot_authz as pilot_authz
from core.audit import AuditEvent
from g1_harness import SAME_NAME, legacy_config, legacy_world, world  # noqa: F401 (fixtures)
from services import ai_service

PROBE = "probe.cc.count_objects_20"


# ── scripted model ───────────────────────────────────────────────────────────

def _text(text, index=0):
    return [
        RawContentBlockStartEvent.model_validate(
            {"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}}),
        RawContentBlockDeltaEvent.model_validate(
            {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": text}}),
        RawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": index}),
    ]


def _skill_evidence(block_id, index=0):
    return [
        RawContentBlockStartEvent.model_validate({
            "type": "content_block_start", "index": index,
            "content_block": {"type": "tool_use", "id": block_id, "name": "record_skill_evidence", "input": {}},
        }),
        RawContentBlockDeltaEvent.model_validate({
            "type": "content_block_delta", "index": index,
            "delta": {"type": "input_json_delta",
                      "partial_json": json.dumps({"probe_id": PROBE, "outcome": "correct"})},
        }),
        RawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": index}),
    ]


GATE = object()  # marker in a script: wait for the test to open the gate


class Script:
    """One scripted model round. Runs on the server's loop."""

    def __init__(self, world, steps):
        self.world, self.steps = world, steps
        self.calls = 0
        self._gate = None

    def gate(self):
        if self._gate is None:
            self._gate = asyncio.Event()
        return self._gate

    def open_gate(self):
        async def _open():
            self.gate().set()
        self.world.run(_open)

    def install(self, monkeypatch):
        script = self

        class _Stream:
            def __aiter__(self):
                return self._run()

            async def _run(self):
                for step in script.steps:
                    if step is GATE:
                        await script.gate().wait()
                        continue
                    for event in step:
                        yield event

            async def get_final_message(self):
                msg = MagicMock()
                msg.stop_reason = "end_turn"
                msg.content = []
                msg.usage = MagicMock(input_tokens=1, output_tokens=1,
                                      cache_creation_input_tokens=0, cache_read_input_tokens=0)
                return msg

        @asynccontextmanager
        async def fake_stream(**kwargs):
            script.calls += 1
            yield _Stream()

        monkeypatch.setattr(ai_service._client.messages, "stream", fake_stream)


@pytest.fixture(autouse=True)
def _quiet_moderation(monkeypatch):
    async def not_flagged(text, student_name=None):
        return {"flagged": False, "categories": [], "confidence": "low", "should_block": False}
    monkeypatch.setattr(tutor_router, "classify_child_message", not_flagged)
    monkeypatch.setattr(pilot_authz, "REVALIDATE_INTERVAL_SECONDS", 0.2)
    monkeypatch.setattr(tutor_router, "STREAM_STALL_TIMEOUT_SECONDS", 6.0)


# ── helpers ──────────────────────────────────────────────────────────────────

def _body(name, message="I counted seven acorns."):
    return {"session_config": legacy_config(name), "current_subject": "mathematics",
            "conversation_history": [], "child_message": message}


_ITER: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _items(response, until=None):
    if response not in _ITER:
        _ITER[response] = response.iter_lines()
    out = []
    for line in _ITER[response]:
        if line.startswith("data:"):
            item = json.loads(line[5:].strip())
            out.append(item)
            if until is not None and until(item):
                break
    return out


def _ledger_rows(w):
    async def count():
        from sqlalchemy import func, select
        from core.database import SkillActivityLog
        async with w.factory() as s:
            return (await s.execute(select(func.count()).select_from(SkillActivityLog))).scalar_one()
    return w.run(count)


def _revocation_stages(w):
    return [e.get("detail", "") for e in w.audit_events()
            if e.get("event") == AuditEvent.AUTHZ_REVOKED_IN_FLIGHT]


def _remove_learner_one(w):
    r = w.client.put(f"/educators/accounts/{w.teacher_one}/roster", headers=w.admin(),
                     json={"configs": [legacy_config("Synthetic Learner Three")]})
    assert r.status_code == 200


# ── tests ────────────────────────────────────────────────────────────────────

def test_authorized_turn_streams_and_writes(legacy_world, monkeypatch):
    w = legacy_world
    Script(w, [_text("Synthetic reply."), _skill_evidence("tool-1", 1)]).install(monkeypatch)
    with w.client.stream("POST", "/tutor/chat", json=_body(w.extra["name_one"]),
                         headers=w.teacher(w.teacher_one)) as r:
        assert r.status_code == 200
        items = _items(r)
    assert {"type": "text", "content": "Synthetic reply."} in items
    assert items[-1] == {"type": "done"}
    assert _ledger_rows(w) == 1
    assert _revocation_stages(w) == []


def test_revocation_mid_generation_stops_output_and_later_writes(legacy_world, monkeypatch):
    w = legacy_world
    script = Script(w, [_text("Synthetic first part."), _skill_evidence("tool-1", 1), GATE,
                        _skill_evidence("tool-2", 2), _text("Synthetic second part.", 3)])
    script.install(monkeypatch)
    with w.client.stream("POST", "/tutor/chat", json=_body(w.extra["name_one"]),
                         headers=w.teacher(w.teacher_one)) as r:
        first = _items(r, until=lambda i: i.get("content") == "Synthetic first part.")
        assert first[-1]["content"] == "Synthetic first part."
        _remove_learner_one(w)
        # The model is silent (blocked on the gate). The periodic check, not
        # a new chunk, is what ends the turn.
        rest = _items(r)
    assert rest == [{"type": "done"}]
    script.open_gate()
    assert _ledger_rows(w) == 1  # only the write made before revocation
    assert any("stage=tutor.idle" in d for d in _revocation_stages(w))


def test_a_write_attempted_after_revocation_is_refused(legacy_world, monkeypatch):
    """With the periodic check pushed out of the way, the write gate alone
    must refuse the post-revocation write, and the chunk check must stop the
    text that follows it."""
    w = legacy_world
    monkeypatch.setattr(pilot_authz, "REVALIDATE_INTERVAL_SECONDS", 60.0)
    script = Script(w, [_text("Synthetic first part."), GATE,
                        _skill_evidence("tool-2", 1), _text("Synthetic second part.", 2)])
    script.install(monkeypatch)
    with w.client.stream("POST", "/tutor/chat", json=_body(w.extra["name_one"]),
                         headers=w.teacher(w.teacher_one)) as r:
        _items(r, until=lambda i: i.get("content") == "Synthetic first part.")
        _remove_learner_one(w)
        script.open_gate()
        rest = _items(r)
    assert rest == [{"type": "done"}]
    assert _ledger_rows(w) == 0
    stages = _revocation_stages(w)
    assert any("stage=write" in d for d in stages)
    assert any("stage=tutor.item" in d for d in stages)


def test_revocation_before_context_retrieval_prevents_the_model_call(legacy_world, monkeypatch):
    w = legacy_world
    script = Script(w, [_text("Should never be generated.")])
    script.install(monkeypatch)
    entered = {}

    async def slow_moderation(text, student_name=None):
        entered["gate"] = script.gate()
        await script.gate().wait()
        return {"flagged": False, "categories": [], "confidence": "low", "should_block": False}
    monkeypatch.setattr(tutor_router, "classify_child_message", slow_moderation)

    with w.client.stream("POST", "/tutor/chat", json=_body(w.extra["name_one"]),
                         headers=w.teacher(w.teacher_one)) as r:
        assert r.status_code == 200
        _remove_learner_one(w)
        script.open_gate()
        items = _items(r)
    assert items == [{"type": "done"}]
    assert script.calls == 0
    assert any("stage=tutor.open" in d for d in _revocation_stages(w))


def test_retry_after_revocation_is_refused(legacy_world, monkeypatch):
    w = legacy_world
    Script(w, [_text("Synthetic reply.")]).install(monkeypatch)
    old = w.teacher(w.teacher_one)
    _remove_learner_one(w)
    # The frontend's TUTOR_MAX_ATTEMPTS retry is a new POST: it re-resolves.
    r = w.client.post("/tutor/chat", json=_body(w.extra["name_one"]), headers=old)
    assert r.status_code == 401
    r = w.client.post("/tutor/chat", json=_body(w.extra["name_one"]), headers=w.teacher(w.teacher_one))
    assert r.status_code == 404


def test_other_teacher_cannot_tutor_or_read_another_teachers_learner(legacy_world, monkeypatch):
    w = legacy_world
    script = Script(w, [_text("Should never be generated.")])
    script.install(monkeypatch)
    t2 = w.teacher(w.teacher_two)
    r = w.client.post("/tutor/chat", json=_body(w.extra["name_one"]), headers=t2)
    assert r.status_code == 404
    for path in (f"/educators/me/students/{w.extra['name_one']}/config",
                 f"/educators/me/students/{w.extra['name_one']}/activity"):
        assert w.client.get(path, headers=t2).status_code == 404
    assert script.calls == 0


def test_campus_mode_tutoring_and_history_are_denied_to_every_teacher(world, monkeypatch):
    w = world
    script = Script(w, [_text("Should never be generated.")])
    script.install(monkeypatch)
    for teacher in (w.teacher_one, w.teacher_two):
        r = w.client.post("/tutor/chat", json=_body(SAME_NAME), headers=w.teacher(teacher))
        assert r.status_code == 404
        for path in (f"/educators/me/students/{SAME_NAME}/activity",
                     f"/educators/me/students/{SAME_NAME}/assessments",
                     f"/narration/{SAME_NAME}/profile"):
            assert w.client.get(path, headers=w.teacher(teacher)).status_code in (403, 404)
    assert script.calls == 0
