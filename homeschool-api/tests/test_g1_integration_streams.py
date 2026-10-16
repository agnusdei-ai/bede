"""G1 integration: revocation, membership disable and learner deletion end
live output AND evict caches; two same-named learners on two campuses stay
isolated across cache, assessment, voice and deletion; and campus-mode
tutoring never reaches the legacy (name-keyed) learner scope.

These combine four lanes that were built and tested separately:
#606 (pilot_authz context, voice binding, tutoring revalidation),
#608 (LearnerScope cache namespace, evict_learner),
#607 (canonical assessment routes) and
#611 (services/pilot_learner_deletion.py).

Real uvicorn + real httpx + real SSE (tests/g1_harness.py), read
incrementally while revocations and deletions are sent on the same live
loop. SQLite by default; Postgres when G1_TEST_DATABASE_URL is set.
Synthetic data only.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import routers.voice as voice_router
import services.ai_service as ai_service
import services.pilot_authz as pilot_authz
import services.streaming_transcription as st
from core import student_keys
from core.learner_scope import LearnerScope
from g1_harness import SAME_NAME, world  # noqa: F401 (fixture)
from test_g1_voice_binding import UNKNOWN, _audio, _data_items, _revocations, _start

NOT_FOUND = {"detail": "Record not found"}
SENTINEL = ("SYNTHETIC-CACHED", 1e18)


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    async def echo(audio_bytes, language="en"):
        return {"text": audio_bytes[-12:].decode("ascii", "ignore"), "language": language}
    monkeypatch.setattr(st, "transcribe_audio", echo)
    monkeypatch.setattr(st, "partial_passes_are_affordable", lambda: True)
    monkeypatch.setattr(pilot_authz, "REVALIDATE_INTERVAL_SECONDS", 0.2)
    # Long enough that two event streams can be opened one after the other
    # (each httpx stream() returns once the server flushes headers, which
    # here is the first 3 s ping), short enough that a broken guard fails
    # rather than hangs. A stream ending by stall can never pass for a
    # revocation: every revocation test also asserts the voice.events audit.
    monkeypatch.setattr(voice_router, "STREAM_STALL_TIMEOUT_SECONDS", 12.0)
    yield
    student_keys.clear_cache()
    for cache in ai_service._PROMPT_CACHES:
        cache.clear()


# ── helpers ─────────────────────────────────────────────────────────────────

def _scopes(w):
    return (LearnerScope.institutional(w.campus_one, w.learner_one),
            LearnerScope.institutional(w.campus_two, w.learner_two))


def _prime(scope: LearnerScope) -> None:
    """One entry in every per-learner cache the process keeps, keyed exactly
    as the real loaders key them (core/learner_scope.py's five components)."""
    student_keys._cache[scope.cache_key("student_data_key", 1)] = (b"S" * 32, 1e18)
    for i, cache in enumerate(ai_service._PROMPT_CACHES):
        cache[scope.cache_key(f"prompt_{i}", ai_service._PROMPT_CACHE_VERSION)] = SENTINEL


def _cached(scope: LearnerScope) -> int:
    n = sum(1 for k in student_keys._cache if scope.owns(k))
    for cache in ai_service._PROMPT_CACHES:
        n += sum(1 for k in cache if scope.owns(k))
    return n


def _ended_by_revocation(w, learner_id) -> bool:
    """The stream ended through pilot_authz (audited), never by stalling."""
    return any("stage=voice.events" in e.get("detail", "") and learner_id in e.get("detail", "")
               for e in _revocations(w))


def _open_voice(w, teacher_id, learner_id, tag):
    headers = w.teacher(teacher_id)
    r = _start(w, headers, learner_id=learner_id)
    assert r.status_code == 200, r.text
    return headers, r.json()["session_id"]


def _assessment(w, teacher_id, campus, learner):
    body = {
        "instrument": "dibels8", "edition": "8th", "measure": "multiple", "grade": "1",
        "form_id": "SYN-PM-FORM-1", "administration_purpose": "progress_monitoring",
        "instructional_cycle": "valor_q1",
        "administered_at": datetime(2031, 9, 2, 9, 0, tzinfo=timezone.utc).isoformat(),
        "report_source": "teacher_administered", "official_benchmark_window": "none",
        "vendor_next_assessment_date": None, "accommodations": [], "notes": None,
        "vendor_guidance": None,
    }
    r = w.client.post(f"/pilot/campuses/{campus}/learners/{learner}/assessments",
                      json=body, headers=w.teacher(teacher_id))
    assert r.status_code == 201, r.text
    return r.json()["assessment_id"]


def _calendar(w, campus):
    r = w.client.put(f"/pilot/campuses/{campus}/calendar",
                     json={"preset": "valor_default", "first_data_day": "2031-08-25"},
                     headers=w.admin())
    assert r.status_code == 200, r.text


def _delete(w, campus, learner):
    async def run():
        from services.pilot_learner_deletion import delete_pilot_learner
        async with w.factory() as s:
            return await delete_pilot_learner(s, campus, learner)
    return w.run(run)


def _tutor_body(student_name: str) -> dict:
    from g1_harness import legacy_config
    return {"session_config": legacy_config(student_name), "current_subject": "mathematics",
            "conversation_history": [], "child_message": "Synthetic question"}


def _no_model(monkeypatch) -> list:
    """Record any call into the tutoring model path. routers.tutor imported
    stream_tutor_response by name, so that is the binding patched."""
    import routers.tutor as tutor_router
    calls: list = []
    monkeypatch.setattr(tutor_router, "stream_tutor_response",
                        lambda **kw: calls.append(kw) or iter(()))
    return calls


# ── 1. Revoke ends voice, evicts caches; campus tutoring never runs ─────────

def test_grant_revoke_ends_voice_and_evicts_caches_and_tutoring_stays_closed(world, monkeypatch):
    w = world
    one, two = _scopes(w)
    _prime(one)
    _prime(two)
    primed = _cached(one)
    assert primed >= 2

    model_calls = _no_model(monkeypatch)

    t1, sid = _open_voice(w, w.teacher_one, w.learner_one, "one")
    with w.client.stream("GET", f"/voice/stream/{sid}/events", headers=t1) as events:
        w.client.post(f"/voice/stream/{sid}/chunk", files=_audio("before"), headers=t1)
        assert _data_items(events, until=lambda i: i["type"] == "partial")[-1]["text"].startswith("before")
        w.revoke(w.campus_one, w.teacher_one, w.learner_one)
        assert _data_items(events) == [UNKNOWN]          # no protected output after revoke
    assert _ended_by_revocation(w, w.learner_one)
    assert sid not in st._sessions
    assert _cached(one) == 0                             # every learner-one cache evicted
    assert _cached(two) == primed                        # same name, other campus untouched

    fresh = w.teacher(w.teacher_one)
    assert _start(w, fresh, learner_id=w.learner_one).status_code == 404   # reconnect denied
    with w.client.stream("GET", f"/voice/stream/{sid}/events", headers=fresh) as events:
        assert _data_items(events) == [UNKNOWN]
    # Tutoring: campus mode keeps educator tutoring disabled, before AND
    # after revocation, and no model call is ever made.
    for student_name in (SAME_NAME, w.learner_one):
        r = w.client.post("/tutor/chat", json=_tutor_body(student_name), headers=fresh)
        assert r.status_code == 404, (student_name, r.text)
    assert model_calls == []


# ── 2. Membership disable: grant version bump + eviction + stream ends ──────

def test_membership_disable_bumps_every_grant_version_evicts_and_ends_streams(world):
    w = world
    one, two = _scopes(w)
    _prime(one)
    _prime(two)

    async def ctx_and_version():
        from core.database import PilotRosterGrant
        from core.database import ClassicalEducator
        async with w.factory() as s:
            grant = await s.get(PilotRosterGrant, (w.teacher_one, w.campus_one, w.learner_one))
            teacher = await s.get(ClassicalEducator, w.teacher_one)
            # Exactly the context resolve_campus_learner mints for this grant.
            ctx = pilot_authz.PilotAuthzContext(
                principal_id=w.teacher_one, action=pilot_authz.ACTION_LEARNER_READ,
                grant_id=grant.grant_id, grant_version=grant.version,
                credential_version=teacher.credential_version,
                campus_id=w.campus_one, learner_id=w.learner_one,
            )
            return ctx, grant.version

    ctx, v_before = w.run(ctx_and_version)
    assert w.run(pilot_authz.revalidate, ctx) is True

    t1, sid = _open_voice(w, w.teacher_one, w.learner_one, "one")
    with w.client.stream("GET", f"/voice/stream/{sid}/events", headers=t1) as events:
        w.client.post(f"/voice/stream/{sid}/chunk", files=_audio("before"), headers=t1)
        _data_items(events, until=lambda i: i["type"] == "partial")
        r = w.client.post(f"/pilot/campuses/{w.campus_one}/educators/{w.teacher_one}/disable",
                          headers=w.admin())
        assert r.status_code == 204, r.text
        assert _data_items(events) == [UNKNOWN]
    assert _ended_by_revocation(w, w.learner_one)

    async def version_after():
        from core.database import PilotRosterGrant
        async with w.factory() as s:
            return (await s.get(PilotRosterGrant, (w.teacher_one, w.campus_one, w.learner_one))).version

    assert w.run(version_after) == v_before + 1
    assert w.run(pilot_authz.revalidate, ctx) is False
    assert _cached(one) == 0 and _cached(two) > 0


# ── 3. Deletion is equivalent to revocation for live streams ───────────────

def test_deleting_a_learner_ends_live_voice_and_denies_reconnect(world):
    w = world
    one, two = _scopes(w)
    _prime(one)
    _prime(two)
    primed_two = _cached(two)

    t1, sid1 = _open_voice(w, w.teacher_one, w.learner_one, "one")
    t2, sid2 = _open_voice(w, w.teacher_two, w.learner_two, "two")
    with w.client.stream("GET", f"/voice/stream/{sid1}/events", headers=t1) as ev1, \
            w.client.stream("GET", f"/voice/stream/{sid2}/events", headers=t2) as ev2:
        for sid, tag, headers in ((sid1, "learner1", t1), (sid2, "learner2", t2)):
            r = w.client.post(f"/voice/stream/{sid}/chunk", files=_audio(tag), headers=headers)
            assert r.status_code == 200, (tag, r.status_code, r.text)
        assert _data_items(ev1, until=lambda i: i["type"] == "partial")[-1]["text"].startswith("learner1")
        assert _data_items(ev2, until=lambda i: i["type"] == "partial")[-1]["text"].startswith("learner2")

        result = _delete(w, w.campus_one, w.learner_one)
        assert result.signed_out_educators == 1

        # Learner One's stream ends with nothing protected after it.
        assert _data_items(ev1) == [UNKNOWN]
        assert _ended_by_revocation(w, w.learner_one)
        # Learner Two (same display name, other campus) keeps streaming.
        w.client.post(f"/voice/stream/{sid2}/chunk", files=_audio("still2"), headers=t2)
        assert _data_items(ev2, until=lambda i: i["type"] == "partial")[-1]["text"].startswith("still2")

    assert sid1 not in st._sessions and sid2 in st._sessions
    # Old token: signed out by the deletion. Fresh token: the learner is gone.
    assert w.client.post(f"/voice/stream/{sid1}/chunk", files=_audio("late"), headers=t1).status_code == 401
    fresh = w.teacher(w.teacher_one)
    assert (_start(w, fresh, learner_id=w.learner_one).status_code,) == (404,)
    with w.client.stream("GET", f"/voice/stream/{sid1}/events", headers=fresh) as events:
        assert _data_items(events) == [UNKNOWN]
    assert w.client.get(f"/pilot/me/learners/{w.learner_one}", headers=fresh).status_code == 404
    assert _cached(one) == 0 and _cached(two) == primed_two


# ── 4. Same display name, two campuses: cache, assessment, voice, deletion ─

def test_same_display_name_on_two_campuses_stays_isolated_end_to_end(world):
    w = world
    one, two = _scopes(w)
    for campus in (w.campus_one, w.campus_two):
        _calendar(w, campus)
    a1 = _assessment(w, w.teacher_one, w.campus_one, w.learner_one)
    a2 = _assessment(w, w.teacher_two, w.campus_two, w.learner_two)
    _prime(one)
    _prime(two)

    # Search by the shared display name returns only each teacher's own UUID.
    for teacher, learner, campus in ((w.teacher_one, w.learner_one, w.campus_one),
                                     (w.teacher_two, w.learner_two, w.campus_two)):
        hits = w.client.post("/pilot/me/learners/search", json={"query": SAME_NAME},
                             headers=w.teacher(teacher)).json()
        assert [(h["learner_id"], h["campus_id"]) for h in hits] == [(learner, campus)]

    # Assessment: each teacher sees exactly their own record; the other's
    # record id under their own path is the uniform 404.
    def listed(teacher, campus, learner):
        r = w.client.get(f"/pilot/campuses/{campus}/learners/{learner}/assessments",
                         headers=w.teacher(teacher))
        assert r.status_code == 200, r.text
        return [x["assessment_id"] for x in r.json()]

    assert listed(w.teacher_one, w.campus_one, w.learner_one) == [a1]
    assert listed(w.teacher_two, w.campus_two, w.learner_two) == [a2]
    r = w.client.get(f"/pilot/campuses/{w.campus_one}/learners/{w.learner_one}/assessments/{a2}",
                     headers=w.teacher(w.teacher_one))
    assert (r.status_code, r.json()) == (404, NOT_FOUND)

    # Voice: sessions for the two same-named learners are distinct and the
    # other teacher cannot reach one with a copied session id.
    t1, sid1 = _open_voice(w, w.teacher_one, w.learner_one, "one")
    t2, sid2 = _open_voice(w, w.teacher_two, w.learner_two, "two")
    assert sid1 != sid2
    assert w.client.post(f"/voice/stream/{sid1}/chunk", files=_audio("x"), headers=t2).status_code == 404

    # Deletion of Learner One removes only Learner One.
    _delete(w, w.campus_one, w.learner_one)
    assert _cached(one) == 0 and _cached(two) > 0
    assert listed(w.teacher_two, w.campus_two, w.learner_two) == [a2]

    async def rows():
        from sqlalchemy import func, select
        from core.pilot_assessment_models import PilotAssessmentAdministration as A
        async with w.factory() as s:
            out = {}
            for learner in (w.learner_one, w.learner_two):
                out[learner] = (await s.execute(
                    select(func.count()).select_from(A).where(A.learner_id == learner)
                )).scalar_one()
            return out

    assert w.run(rows) == {w.learner_one: 0, w.learner_two: 1}


# ── 5. Campus-mode tutoring never reaches the legacy (name-keyed) scope ────

def test_campus_mode_tutoring_never_constructs_a_legacy_scope(world, monkeypatch):
    """Educator tutoring is DISABLED in campus mode (the institutional path
    is not built; #606). This proves the disable holds before any learner
    scope exists: no request, whatever name or UUID it carries, makes the
    process build a legacy household scope (which would key caches and the
    data key by a display name two campuses share) or call the model.
    Wiring learner_scope into the tutoring path is deliberately NOT done,
    because that path answers 404 before it would be used."""
    w = world
    legacy_built: list = []
    real_legacy = LearnerScope.legacy.__func__

    def spy(cls, student_name):
        legacy_built.append(student_name)
        return real_legacy(cls, student_name)

    monkeypatch.setattr(LearnerScope, "legacy", classmethod(spy))
    model_calls = _no_model(monkeypatch)

    for teacher in (w.teacher_one, w.teacher_two):
        for student_name in (SAME_NAME, w.learner_one, w.learner_two):
            r = w.client.post("/tutor/chat", json=_tutor_body(student_name),
                              headers=w.teacher(teacher))
            assert r.status_code == 404, (student_name, r.status_code, r.text)
    assert model_calls == []
    assert legacy_built == []
