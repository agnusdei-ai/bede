"""G1: voice sessions are bound to one principal, campus, learner, session,
grant id and grant version, and an educator's event stream ends on revocation.

Real HTTP and real SSE through the assembled app (tests/g1_harness.py). The
SSE stream is read incrementally while chunks, finishes and revocations are
sent on the same live loop. Transcription is stubbed to a synthetic echo of
the audio bytes, so each learner's session produces distinguishable text.
SQLite by default; Postgres when G1_TEST_DATABASE_URL is set.
"""
import json
import weakref

import pytest

import routers.voice as voice_router
import services.pilot_authz as pilot_authz
import services.streaming_transcription as st
from core.audit import AuditEvent
from g1_harness import legacy_world, world  # noqa: F401 (fixtures)

NOT_FOUND = {"detail": "Record not found"}
UNKNOWN = {"type": "error", "message": "unknown or expired session"}


@pytest.fixture(autouse=True)
def _synthetic_transcription(monkeypatch):
    async def echo(audio_bytes, language="en"):
        # The last bytes name the speaker, so two sessions' transcripts differ.
        return {"text": audio_bytes[-12:].decode("ascii", "ignore"), "language": language}
    monkeypatch.setattr(st, "transcribe_audio", echo)
    monkeypatch.setattr(st, "partial_passes_are_affordable", lambda: True)
    monkeypatch.setattr(pilot_authz, "REVALIDATE_INTERVAL_SECONDS", 0.2)
    # A broken guard must fail the test, not hang it.
    monkeypatch.setattr(voice_router, "STREAM_STALL_TIMEOUT_SECONDS", 4.0)


def _audio(tag: str) -> dict:
    return {"audio": ("chunk.wav", b"\x00\x01" * 64 + tag.encode().ljust(12, b"."), "audio/wav")}


def _start(w, headers, **scope):
    return w.client.post("/voice/stream/start", json={"language": "en", **scope}, headers=headers)


_LINE_ITERATORS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _data_items(response, until=None, limit=40):
    """Read SSE data items incrementally until ``until(item)`` or the stream
    ends. ONE line iterator per response, reused across calls: abandoning an
    httpx line iterator closes the connection, which the server then sees as
    a client disconnect."""
    if response not in _LINE_ITERATORS:
        _LINE_ITERATORS[response] = response.iter_lines()
    lines = _LINE_ITERATORS[response]
    items = []
    for line in lines:
        if not line.startswith("data:"):
            continue
        item = json.loads(line[5:].strip())
        items.append(item)
        if until is not None and until(item):
            break
        if len(items) >= limit:
            break
    return items


def _revocations(w):
    return [e for e in w.audit_events() if e.get("event") == AuditEvent.AUTHZ_REVOKED_IN_FLIGHT]


# ── Same campus works end to end ─────────────────────────────────────────────

def test_authorized_teacher_streams_a_permitted_synthetic_event(world):
    w = world
    t1 = w.teacher(w.teacher_one)
    sid = _start(w, t1, learner_id=w.learner_one).json()["session_id"]

    async def grant_id():
        from core.database import PilotRosterGrant
        async with w.factory() as s:
            return (await s.get(PilotRosterGrant, (w.teacher_one, w.campus_one, w.learner_one))).grant_id
    # principal | campus | learner | grant id | grant version | credential version.
    # The session UUID is the key the owner is stored under.
    assert st._sessions[sid].owner == "|".join(
        ("educator", w.teacher_one, w.campus_one, w.learner_one, w.run(grant_id), "1", "1"))
    with w.client.stream("GET", f"/voice/stream/{sid}/events", headers=t1) as events:
        assert events.status_code == 200
        assert w.client.post(f"/voice/stream/{sid}/chunk", files=_audio("one-ok"), headers=t1).status_code == 200
        first = _data_items(events, until=lambda i: i["type"] == "partial")
        assert first[-1] == {"type": "partial", "text": "one-ok......"}
        assert w.client.post(f"/voice/stream/{sid}/finish", headers=t1).status_code == 200
        rest = _data_items(events, until=lambda i: i["type"] == "done")
    assert [i["type"] for i in rest] == ["final", "done"]


def test_campus_supplied_by_the_client_is_compared_not_trusted(world):
    w = world
    t1 = w.teacher(w.teacher_one)
    assert _start(w, t1, learner_id=w.learner_one, campus_id=w.campus_one).status_code == 200
    r = _start(w, t1, learner_id=w.learner_one, campus_id=w.campus_two)
    assert (r.status_code, r.json()) == (404, NOT_FOUND)


# ── Cross-campus denial ──────────────────────────────────────────────────────

def test_other_campus_teacher_cannot_start_a_session_for_learner_one(world):
    w = world
    r = _start(w, w.teacher(w.teacher_two), learner_id=w.learner_one)
    assert (r.status_code, r.json()) == (404, NOT_FOUND)
    r = _start(w, w.teacher(w.teacher_one), learner_id=w.learner_two)
    assert (r.status_code, r.json()) == (404, NOT_FOUND)


def test_other_teacher_cannot_write_read_finish_or_subscribe_with_a_copied_session_id(world):
    w = world
    t1, t2 = w.teacher(w.teacher_one), w.teacher(w.teacher_two)
    sid = _start(w, t1, learner_id=w.learner_one).json()["session_id"]

    r = w.client.post(f"/voice/stream/{sid}/chunk", files=_audio("intruder"), headers=t2)
    assert r.status_code == 404
    assert bytes(st._sessions[sid].pcm) == b"" and st._sessions[sid].audio == b""
    r = w.client.post(f"/voice/stream/{sid}/finish", headers=t2)
    assert r.status_code == 404
    with w.client.stream("GET", f"/voice/stream/{sid}/events", headers=t2) as events:
        assert _data_items(events) == [UNKNOWN]
    # Reads exactly like a session that never existed.
    with w.client.stream("GET", "/voice/stream/0123456789abcdef0123456789abcdef/events", headers=t2) as events:
        assert _data_items(events) == [UNKNOWN]
    # Teacher One's session is untouched by any of that.
    assert sid in st._sessions and not st._sessions[sid].finished


def test_same_name_learners_on_two_campuses_get_isolated_sessions(world):
    w = world
    t1, t2 = w.teacher(w.teacher_one), w.teacher(w.teacher_two)
    s1 = _start(w, t1, learner_id=w.learner_one).json()["session_id"]
    s2 = _start(w, t2, learner_id=w.learner_two).json()["session_id"]
    assert st._sessions[s1].owner != st._sessions[s2].owner
    for sid, headers, tag in ((s1, t1, "learner-one"), (s2, t2, "learner-two")):
        assert w.client.post(f"/voice/stream/{sid}/chunk", files=_audio(tag), headers=headers).status_code == 200
        assert w.client.post(f"/voice/stream/{sid}/finish", headers=headers).status_code == 200
    for sid, headers, tag in ((s1, t1, "learner-one"), (s2, t2, "learner-two")):
        with w.client.stream("GET", f"/voice/stream/{sid}/events", headers=headers) as events:
            texts = {i.get("text") for i in _data_items(events, until=lambda i: i["type"] == "done")}
        assert any(t and t.startswith(tag) for t in texts)
        other = "learner-two" if tag == "learner-one" else "learner-one"
        assert not any(t and t.startswith(other) for t in texts)


# ── Revocation ───────────────────────────────────────────────────────────────

def test_grant_revocation_closes_the_open_stream_and_denies_reconnect(world):
    w = world
    t1 = w.teacher(w.teacher_one)
    sid = _start(w, t1, learner_id=w.learner_one).json()["session_id"]
    with w.client.stream("GET", f"/voice/stream/{sid}/events", headers=t1) as events:
        w.client.post(f"/voice/stream/{sid}/chunk", files=_audio("before"), headers=t1)
        assert _data_items(events, until=lambda i: i["type"] == "partial")[-1]["text"].startswith("before")
        w.revoke(w.campus_one, w.teacher_one, w.learner_one)
        after = _data_items(events)
    # The stream ends with the unknown-session answer and nothing protected.
    assert after == [UNKNOWN]
    assert sid not in st._sessions
    # The old token is dead; a fresh token cannot reattach or write.
    assert w.client.post(f"/voice/stream/{sid}/chunk", files=_audio("after"), headers=t1).status_code == 401
    fresh = w.teacher(w.teacher_one)
    assert w.client.post(f"/voice/stream/{sid}/chunk", files=_audio("after"), headers=fresh).status_code == 404
    with w.client.stream("GET", f"/voice/stream/{sid}/events", headers=fresh) as events:
        assert _data_items(events) == [UNKNOWN]
    r = _start(w, fresh, learner_id=w.learner_one)
    assert (r.status_code, r.json()) == (404, NOT_FOUND)
    assert any("stage=voice.events" in e.get("detail", "") for e in _revocations(w))


def test_revocation_that_leaves_the_token_valid_still_stops_writes_and_events(world):
    """Disabling the learner does not bump any credential version, so the
    teacher's token still authenticates. The grant check is what stops it."""
    w = world
    t1 = w.teacher(w.teacher_one)
    sid = _start(w, t1, learner_id=w.learner_one).json()["session_id"]

    async def disable_learner():
        from core.database import PilotLearner
        async with w.factory() as s:
            (await s.get(PilotLearner, w.learner_one)).enabled = False
            await s.commit()

    with w.client.stream("GET", f"/voice/stream/{sid}/events", headers=t1) as events:
        w.client.post(f"/voice/stream/{sid}/chunk", files=_audio("before"), headers=t1)
        _data_items(events, until=lambda i: i["type"] == "partial")
        w.run(disable_learner)
        assert _data_items(events) == [UNKNOWN]
    r = w.client.post(f"/voice/stream/{sid}/chunk", files=_audio("after"), headers=t1)
    assert (r.status_code, r.json()["detail"]) == (404, "Unknown or finished streaming session")


def test_chunk_after_revocation_is_refused_and_never_lands(world):
    w = world
    t1 = w.teacher(w.teacher_one)
    sid = _start(w, t1, learner_id=w.learner_one).json()["session_id"]

    async def disable_membership_without_bump():
        from core.database import PilotEducatorCampus
        async with w.factory() as s:
            (await s.get(PilotEducatorCampus, (w.teacher_one, w.campus_one))).enabled = False
            await s.commit()

    w.run(disable_membership_without_bump)
    r = w.client.post(f"/voice/stream/{sid}/chunk", files=_audio("late"), headers=t1)
    assert r.status_code == 404
    assert sid not in st._sessions  # discarded, worker cancelled
    assert any("stage=voice.write" in e.get("detail", "") for e in _revocations(w))


# ── Uniform failure for every bad learner id on start ───────────────────────

@pytest.mark.parametrize("scope", [
    {},                                               # missing
    {"learner_id": None},                             # explicit null
    {"learner_id": "not-a-uuid"},                     # malformed
    {"learner_id": "00000000-0000-0000-0000-000000000000"},  # nil, not v4
    {"learner_id": "6F9619FF-8B86-4011-B42D-00CF4FC964FF"},  # non-canonical case
    {"learner_id": "1b4e28ba-2fa1-41d2-883f-0016d3cca427"},  # random v4
    {"student_name": "Synthetic Learner"},            # a name cannot bypass the UUID
])
def test_every_bad_or_missing_learner_reads_the_same(world, scope):
    w = world
    r = _start(w, w.teacher(w.teacher_one), **scope)
    assert (r.status_code, r.json()) == (404, NOT_FOUND)


# ── Other roles keep their semantics ─────────────────────────────────────────

def test_parent_sessions_keep_role_ownership(world):
    w = world
    sid = _start(w, w.admin()).json()["session_id"]
    assert st._sessions[sid].owner == "parent"
    assert st._sessions[sid].authz is None
    assert w.client.post(f"/voice/stream/{sid}/chunk", files=_audio("parent"), headers=w.admin()).status_code == 200
    # An educator holding the id still cannot reach a parent's session.
    t1 = w.teacher(w.teacher_one)
    assert w.client.post(f"/voice/stream/{sid}/chunk", files=_audio("x"), headers=t1).status_code == 404


# ── Single-household (no campus) mode ───────────────────────────────────────

def test_legacy_mode_binds_to_the_roster_learner(legacy_world):
    w = legacy_world
    t1, t2 = w.teacher(w.teacher_one), w.teacher(w.teacher_two)
    r = _start(w, t1, student_name=w.extra["name_one"])
    assert r.status_code == 200
    sid = r.json()["session_id"]
    assert w.extra["name_one"] not in st._sessions[sid].owner  # digest, never the name
    assert _start(w, t1, student_name=w.extra["name_two"]).status_code == 404
    assert _start(w, t1).status_code == 404
    assert w.client.post(f"/voice/stream/{sid}/chunk", files=_audio("x"), headers=t2).status_code == 404
    # Removing the learner from the roster revokes: the old token is dead and
    # a fresh one cannot reach the session.
    r = w.client.put(f"/educators/accounts/{w.teacher_one}/roster", headers=w.admin(),
                     json={"configs": [{"student_name": "Synthetic Learner Three", "grade": "4",
                                        "grade_stage": "3-5", "subjects": ["mathematics"]}]})
    assert r.status_code == 200
    assert w.client.post(f"/voice/stream/{sid}/chunk", files=_audio("x"), headers=t1).status_code == 401
    fresh = w.teacher(w.teacher_one)
    assert w.client.post(f"/voice/stream/{sid}/chunk", files=_audio("x"), headers=fresh).status_code == 404
