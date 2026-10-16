"""Real HTTP tests for the teacher-governed synthetic tutoring route.

No real model or student data: fake local adapter emits deterministic text.
A missing teacher decision never invokes it. G1 campus grants are required
on both sides of the SSE request and its durable encrypted transcript.
"""
from types import SimpleNamespace

from core.config import settings
import routers.pilot_tutor as tut
from test_canonical_assessment_api import _reset_rate_limiter, client, world


def _url(learner):
    return f"/pilot/me/learners/{learner}/tutoring/chat"


class _Stream:
    def __init__(self):
        self.index = 0
    async def __aenter__(self): return self
    async def __aexit__(self, *_): return False
    def __aiter__(self): return self
    async def __anext__(self):
        if self.index:
            raise StopAsyncIteration
        self.index += 1
        return SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text="What do you notice about this sound?")
        )


class _LocalModel:
    def __init__(self):
        self.calls = []
        self.messages = self
    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return _Stream()


def _approve(world):
    path = f"/pilot/me/learners/{world.learner_one}"
    body = {
        "framework": "dibels8", "measure": "ORF_WC",
        "assessed_on": "2026-01-15", "source_name": "Synthetic classroom evidence",
        "score": 12, "score_unit": "correct_per_minute",
        "reported_band": "intensive_at_risk",
        "assessed_grade": "2", "assessment_window": "middle_of_year",
    }
    ev = world.client.post(f"{path}/evidence", json=body,
                           headers=world.teacher_one.headers)
    assert ev.status_code == 201, ev.text
    draft = world.client.post(f"{path}/recommendations",
                              headers=world.teacher_one.headers)
    assert draft.status_code == 200 and draft.json().get("abstained") is False, draft.text
    r = draft.json()
    done = world.client.post(
        f"{path}/recommendations/{r['recommendation_id']}/decision",
        headers=world.teacher_one.headers,
        json={"action": "approve", "expected_version": r["version"]},
    )
    assert done.status_code == 200, done.text


def test_no_teacher_approval_no_model_call(world, monkeypatch):
    calls = []
    monkeypatch.setattr(tut, "resolve_local_only",
                        lambda: calls.append("called") or _LocalModel())
    res = world.client.post(_url(world.learner_one), json={"child_message": "[START]"},
                            headers=world.teacher_one.headers)
    assert res.status_code == 409
    assert "Teacher approval" in res.text and calls == []


def test_other_campus_never_discovers_learner_or_approved_instruction(world):
    _approve(world)
    bad = world.client.post(_url(world.learner_one), json={"child_message": "[START]"},
                            headers=world.teacher_two.headers)
    missing = world.client.post(
        _url("00000000-0000-0000-0000-000000000000"),
        json={"child_message": "[START]"}, headers=world.teacher_two.headers)
    assert bad.status_code == missing.status_code == 404
    assert bad.content == missing.content


def test_approved_synthetic_local_stream_persists_authorized_encrypted_history(world, monkeypatch):
    _approve(world)
    fake = _LocalModel()
    monkeypatch.setattr(settings, "local_llm_base_url", "http://127.0.0.1:8766/v1")
    monkeypatch.setattr(tut, "resolve_local_only", lambda: fake)
    r = world.client.post(_url(world.learner_one), json={"child_message": "[START]"},
                          headers=world.teacher_one.headers)
    assert r.status_code == 200, r.text
    assert '"type": "text"' in r.text
    assert '"type": "done"' in r.text
    assert len(fake.calls) == 1
    assert fake.calls[0]["model"] == settings.local_llm_model
    assert fake.calls[0].get("tools") is None
    own = world.client.get(f"/pilot/me/learners/{world.learner_one}/tutoring/history",
                           headers=world.teacher_one.headers)
    assert own.status_code == 200, own.text
    assert own.json()["sessions"][0]["message_count"] == 2
    assert "What do you notice" not in own.text
    cross = world.client.get(f"/pilot/me/learners/{world.learner_one}/tutoring/history",
                             headers=world.teacher_two.headers)
    assert cross.status_code == 404


def test_production_and_remote_provider_are_fail_closed(world, monkeypatch):
    _approve(world)
    monkeypatch.setattr(settings, "production", "true")
    r = world.client.post(_url(world.learner_one), json={"child_message": "[START]"},
                          headers=world.teacher_one.headers)
    assert r.status_code == 403
    monkeypatch.setattr(settings, "production", "false")
    monkeypatch.setattr(settings, "local_llm_base_url", "https://api.openai.com/v1")
    r = world.client.post(_url(world.learner_one), json={"child_message": "[START]"},
                          headers=world.teacher_one.headers)
    assert r.status_code == 503
