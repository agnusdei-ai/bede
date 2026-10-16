"""Synthetic, real-HTTP tutoring-history read and isolation tests (SQLite/Postgres).

The canonical assessment client fixture supplies real app, DB and two
different campuses whose learners deliberately share a display name.
"""
from datetime import datetime, timezone

from sqlalchemy import select

from test_canonical_assessment_api import _reset_rate_limiter, client, world
from core import student_keys
from core.database import SessionTranscript
from core.encryption import encrypt_json, student_aad
from core.learner_scope import LearnerScope

def _path(learner):
    return f"/pilot/me/learners/{learner}/tutoring/history"


def test_empty_history_is_not_fabricated(world):
    r = world.client.get(_path(world.learner_one), headers=world.teacher_one.headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"learner_id": world.learner_one, "sessions": [], "has_more": False}


def _seed(world):
    scope = LearnerScope.institutional(world.campus_one, world.learner_one)
    now = datetime(2031, 9, 4, 12, 0, tzinfo=timezone.utc)

    async def write():
        async with world.client.db_factory() as db:
            key = await student_keys.get_or_create(db, scope)
            row = SessionTranscript(
                student_name=scope.storage_subject, session_date=now,
                subjects="reading", duration_minutes=5,
                transcript_enc=encrypt_json(
                    {"messages": [{"role": "learner", "content": "Synthetic practice"}]},
                    student_aad("session_transcripts", "transcript_enc", scope.storage_subject),
                    key,
                ),
            )
            db.add(row)
            await db.commit()
            return row.id

    return world.client.portal.call(write)


def test_reads_real_encrypted_scoped_session_without_message_contents(world):
    session_id = _seed(world)
    r = world.client.get(_path(world.learner_one), headers=world.teacher_one.headers)
    assert r.status_code == 200, r.text
    assert len(r.json()["sessions"]) == 1
    item = r.json()["sessions"][0]
    assert item["session_id"] == session_id
    assert item["message_count"] == 1 and item["subjects"] == ["reading"]
    assert "Synthetic practice" not in r.text
    assert "Example Learner" not in r.text


def test_same_display_name_never_crosses_campus_or_invalid_id(world):
    _seed(world)
    other = world.client.get(_path(world.learner_one), headers=world.teacher_two.headers)
    random_missing = world.client.get(
        _path("00000000-0000-0000-0000-000000000000"),
        headers=world.teacher_two.headers)
    assert other.status_code == random_missing.status_code == 404
    assert other.content == random_missing.content
    own = world.client.get(_path(world.learner_two), headers=world.teacher_two.headers)
    assert own.status_code == 200
    assert own.json()["sessions"] == []
    assert world.learner_one not in own.text


def test_corrupted_encrypted_history_fails_closed(world):
    sid = _seed(world)
    async def tamper():
        async with world.client.db_factory() as db:
            record = await db.get(SessionTranscript, sid)
            record.transcript_enc = b"not-a-verified-encrypted-transcript"
            await db.commit()
    world.client.portal.call(tamper)
    result = world.client.get(_path(world.learner_one), headers=world.teacher_one.headers)
    assert result.status_code == 409
    assert result.json() == {"detail": "Verified tutoring history is unavailable"}


def test_revocation_during_history_read_refuses_output(world, monkeypatch):
    from services import pilot_authz
    async def revoked(_ctx): return False
    monkeypatch.setattr(pilot_authz, "revalidate", revoked)
    r = world.client.get(_path(world.learner_one), headers=world.teacher_one.headers)
    assert r.status_code == 404
    assert "sessions" not in r.text
