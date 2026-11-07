"""The campus tutor feeds the pooled AI backend failure alert (routers/pilot_tutor.py).

routers/tutor.py logs ``AuditEvent.AI_BACKEND_FAILURE`` on a stall and on an
exception, and core/audit.py pools those across every caller so three
failures in ten minutes email the operator. The pilot tutor logged nothing,
so a campus whose local model was down never raised that alert. These tests
drive the REAL route over HTTP with a failing local model, let the real
``log_event_nowait`` write through the real ``log_event`` anomaly watch, and
observe the alert at the email boundary.

Synthetic identities only (tests/canonical_assessment_fixtures.py).
"""
from __future__ import annotations

import time

import pytest

import core.audit as audit
import routers.pilot_tutor as tut
from core.audit import AuditEvent, read_audit_log
from core.config import settings
from test_canonical_assessment_api import _reset_rate_limiter, client, world  # noqa: F401
from test_pilot_tutor_stream import _approve

CHILD_WORDS = "Synthetic learner answer about the vowel sound"


class _DeadStream:
    async def __aenter__(self):
        raise ConnectionError("synthetic local model is down")

    async def __aexit__(self, *_):
        return False


class _DeadModel:
    """The classifier call succeeds; the tutoring stream's connection fails."""

    def __init__(self):
        self.messages = self

    async def create(self, **_):
        from types import SimpleNamespace
        return SimpleNamespace(content=[SimpleNamespace(text='{"safe": true}')])

    def stream(self, **_):
        return _DeadStream()


class _DeadClassifier(_DeadModel):
    async def create(self, **_):
        raise ConnectionError("synthetic local model is down")


@pytest.fixture
def alerts(monkeypatch):
    sent: list[int] = []

    async def fake_backend_alert(count, window_label="in the last 10 minutes"):
        sent.append(count)
        return True

    monkeypatch.setattr(audit, "_anomaly_windows", {})
    monkeypatch.setattr(audit, "_anomaly_last_alert", {})
    monkeypatch.setattr("services.email_service.security_alert_configured", lambda: True)
    monkeypatch.setattr("services.email_service.send_backend_failure_alert", fake_backend_alert)
    return sent


def _url(learner):
    return f"/pilot/me/learners/{learner}/tutoring/chat"


def _failures(world) -> list[dict]:
    async def read():
        async with world.client.db_factory() as s:
            return await read_audit_log(s, limit=200)
    deadline = time.monotonic() + 10
    while True:
        rows = world.client.portal.call(read)
        found = [e for e in rows if e.get("event") == AuditEvent.AI_BACKEND_FAILURE]
        if found or time.monotonic() > deadline:
            return found
        time.sleep(0.1)


def _wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.1)


def test_a_failing_local_stream_logs_an_ai_backend_failure(world, monkeypatch, alerts):
    _approve(world)
    monkeypatch.setattr(settings, "local_llm_base_url", "http://127.0.0.1:8766/v1")
    monkeypatch.setattr(tut, "resolve_local_only", lambda: _DeadModel())
    r = world.client.post(_url(world.learner_one),
                          json={"child_message": CHILD_WORDS, "subject": "reading"},
                          headers=world.teacher_one.headers)
    assert r.status_code == 200, r.text
    assert "Local tutoring unavailable" in r.text
    failures = _failures(world)
    assert len(failures) == 1, failures
    assert failures[0]["detail"] == "cause=exception subject=reading error=ConnectionError"
    assert failures[0]["role"] == "educator"
    # No learner content, and no exception message, which can echo it.
    blob = repr(failures)
    assert "Synthetic learner" not in blob and "vowel" not in blob
    assert "is down" not in blob


def test_a_failing_classifier_call_logs_an_ai_backend_failure(world, monkeypatch, alerts):
    _approve(world)
    monkeypatch.setattr(settings, "local_llm_base_url", "http://127.0.0.1:8766/v1")
    monkeypatch.setattr(tut, "resolve_local_only", lambda: _DeadClassifier())
    r = world.client.post(_url(world.learner_one),
                          json={"child_message": CHILD_WORDS, "subject": "mathematics"},
                          headers=world.teacher_one.headers)
    assert r.status_code == 503
    failures = _failures(world)
    assert [f["detail"] for f in failures] == [
        "cause=exception subject=mathematics error=ConnectionError"]


def test_a_stalled_local_stream_logs_a_stall(world, monkeypatch, alerts):
    import asyncio

    class _SilentStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(30)

    class _SilentModel(_DeadModel):
        def stream(self, **_):
            return _SilentStream()

    _approve(world)
    monkeypatch.setattr(settings, "local_llm_base_url", "http://127.0.0.1:8766/v1")
    monkeypatch.setattr(tut, "STREAM_STALL_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(tut, "resolve_local_only", lambda: _SilentModel())
    r = world.client.post(_url(world.learner_one), json={"child_message": "[START]"},
                          headers=world.teacher_one.headers)
    assert "Local tutoring unavailable" in r.text
    assert [f["detail"] for f in _failures(world)] == ["cause=stall subject=reading"]


def test_three_campus_failures_reach_the_pooled_operator_alert(world, monkeypatch, alerts):
    _approve(world)
    monkeypatch.setattr(settings, "local_llm_base_url", "http://127.0.0.1:8766/v1")
    monkeypatch.setattr(tut, "resolve_local_only", lambda: _DeadModel())
    for _ in range(3):
        r = world.client.post(_url(world.learner_one), json={"child_message": "[START]"},
                              headers=world.teacher_one.headers)
        assert "Local tutoring unavailable" in r.text
    _wait_for(lambda: alerts == [3])
    assert alerts == [3]


def test_a_healthy_turn_logs_no_backend_failure(world, monkeypatch, alerts):
    from test_pilot_tutor_stream import _LocalModel
    _approve(world)
    monkeypatch.setattr(settings, "local_llm_base_url", "http://127.0.0.1:8766/v1")
    monkeypatch.setattr(tut, "resolve_local_only", lambda: _LocalModel())
    r = world.client.post(_url(world.learner_one), json={"child_message": "[START]"},
                          headers=world.teacher_one.headers)
    assert '"type": "done"' in r.text
    time.sleep(0.5)

    async def read():
        async with world.client.db_factory() as s:
            return await read_audit_log(s, limit=200)
    rows = world.client.portal.call(read)
    assert not [e for e in rows if e.get("event") == AuditEvent.AI_BACKEND_FAILURE]
