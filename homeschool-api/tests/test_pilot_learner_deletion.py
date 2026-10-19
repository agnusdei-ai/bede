"""Valor pilot learner deletion over the real app, on SQLite and Postgres.

services/pilot_learner_deletion.py removes one pilot learner's ACTIVE
application records by campus UUID and learner UUID, re-counts, rolls back
on any leftover, evicts the learner's caches only after commit, and leaves a
content-free audit tombstone. These tests drive the real routes over HTTP
for every read path, and the real cache loaders for the cache path.

Postgres runs as a NON-superuser role. Set ``BEDE_DELETE_PG_URL`` to point
elsewhere; ``BEDE_REQUIRE_PG=1`` turns an unreachable Postgres into a
failure instead of a skip.

Synthetic data only (tests/canonical_assessment_fixtures.py): Synthetic
Campus One / Two, Synthetic Teacher One / Two, and two learners who share
one display name.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core import student_keys
from core.config import settings
from core.database import (
    Base, ClassicalEducator, MasteryProfile, PilotLearner, PilotRosterGrant, StudentKey, get_db,
)
from core.encryption import encrypt_json, student_aad
from core.learner_scope import LearnerScope
import core.pilot_assessment_models as models
from canonical_assessment_fixtures import (
    ADMIN, SHARED_DISPLAY_NAME, Teacher, World, boy_vendor_report, responses_with_errors,
)
from test_canonical_assessment_api import _protected_requests
from test_learner_scope_cache_isolation import all_cache_keys, prime, seed_learner_one
import services.pilot_learner_deletion as deletion
from services import ai_service
from services.pilot_learner_deletion import (
    DeletionIncomplete, LearnerNotFound, STORAGE_SUBJECT_EXEMPT, delete_pilot_learner,
    pilot_cascade, storage_subject_tables,
)

PG_URL = os.environ.get(
    "BEDE_DELETE_PG_URL",
    "postgresql+asyncpg://bede_delete_app:synthetic-only@127.0.0.1:5433/deletion_lifecycle",
)
API = Path(__file__).resolve().parents[1]
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
TOMBSTONE = re.compile(rf"pilot_learner_deleted campus={UUID} learner={UUID} rows=\d+ tables=\d+")

# Text that exists only inside learner one's content. None of it may survive
# deletion anywhere a tombstone or audit view can show it.
CONTENT = (SHARED_DISPLAY_NAME, "Synthetic evidence summary", "Synthetic teacher plan",
           "Synthetic rationale", "Synthetic teacher annotation", "Below Benchmark",
           "Some Support", "At Benchmark", "onset_rime_only", "Synthetic resume point",
           "Synthetic teacher follow-up after offline instruction")


def _pg_available() -> bool:
    async def probe():
        eng = create_async_engine(PG_URL, poolclass=NullPool)
        try:
            async with eng.connect() as conn:
                await conn.execute(text("select 1"))
            return True
        except Exception:
            return False
        finally:
            await eng.dispose()
    return asyncio.run(probe())


@pytest.fixture(autouse=True)
def _clean_process_state():
    from core.middleware import reset_rate_limiter
    reset_rate_limiter()
    student_keys.clear_cache()
    yield
    reset_rate_limiter()
    student_keys.clear_cache()


@pytest.fixture(params=["sqlite", "postgres"])
def client(request, monkeypatch, test_client_with_database_context):
    import main
    import core.database as database_module
    import core.encryption as encryption_module

    if request.param == "postgres":
        if not _pg_available():
            if os.environ.get("BEDE_REQUIRE_PG") == "1":
                pytest.fail("Postgres required (BEDE_REQUIRE_PG=1) but unreachable")
            pytest.skip("Postgres not reachable")
        url = PG_URL
    else:
        url = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/delete.sqlite"

    async def _reset():
        eng = create_async_engine(url, poolclass=NullPool)
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await eng.dispose()

    asyncio.run(_reset())
    monkeypatch.setattr(settings, "educator_pilot_enabled", True)
    monkeypatch.setattr(settings, "demo_pin", "")
    monkeypatch.setattr(settings, "elevation_enforced", False)
    monkeypatch.setattr(settings, "production", "false")
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database_module, "AsyncSessionLocal", factory)
    monkeypatch.setattr(database_module, "engine", engine)
    if encryption_module._DATA_KEY is None:
        from Crypto.Random import get_random_bytes
        monkeypatch.setattr(encryption_module, "_DATA_KEY", get_random_bytes(32))

    async def _override():
        async with factory() as session:
            yield session

    main.app.dependency_overrides[get_db] = _override
    with test_client_with_database_context(main.app, engine) as test_client:
        test_client.db_factory = factory
        test_client.backend = request.param
        yield test_client
    main.app.dependency_overrides.pop(get_db, None)


# ── Seeding ─────────────────────────────────────────────────────────────────

def _post(w, path, body, teacher, status):
    r = w.client.post(path, json=body, headers=teacher.headers)
    assert r.status_code == status, (path, r.status_code, r.text)
    return r.json()


def journey(w: World, campus: str, learner: str, teacher: Teacher) -> tuple[str, str]:
    """One full journey for one learner, touching EVERY learner-scoped table:
    administration, scores, responses, transitions, evidence, proposal,
    decision, plan and progress-monitoring schedule."""
    kw = dict(campus=campus, learner=learner, teacher=teacher)
    adm = w.administer(**kw)["assessment_id"]
    w.step(adm, "mark_ready", "DRAFT", **kw)
    w.step(adm, "start", "READY_FOR_ADMINISTRATION", **kw)
    w.scores(adm, boy_vendor_report(), responses_with_errors(), **kw)
    w.step(adm, "submit", "IN_PROGRESS", **kw)
    w.step(adm, "finalize", "COMPLETED_PENDING_REVIEW", **kw)
    base = w.base(campus, learner)
    _post(w, f"{base}/assessments/{adm}/evidence", {"summary": "Synthetic evidence summary"}, teacher, 201)
    prop = _post(w, f"{base}/assessments/{adm}/proposal", None, teacher, 200)
    w.decide(adm, prop["proposal_id"], {
        "action": "approve", "expected_version": 1,
        "confirmed_review_on": prop["proposed_review_on"], "rationale": "Synthetic rationale"}, **kw)
    plan = _post(w, f"{base}/assessments/{adm}/plan", {"plan_text": "Synthetic teacher plan"}, teacher, 201)
    _post(w, f"{base}/assessments/{adm}/plans/{plan['plan_id']}/follow-ups", {
        "observed_on": date.today().isoformat(), "teaching_mode": "in_person",
        "observation": "Synthetic teacher follow-up after offline instruction",
        "next_step": "Continue synthetic classroom observation",
    }, teacher, 201)
    _post(w, f"{base}/assessments/{adm}/progress-monitoring",
          {"measure": "PSF", "planned_dates": ["2031-09-08", "2031-09-22"]}, teacher, 201)
    return adm, prop["proposal_id"]


def _scopes(w: World):
    return (LearnerScope.institutional(w.campus_one, w.learner_one),
            LearnerScope.institutional(w.campus_two, w.learner_two))


def _run(client, fn):
    async def go():
        async with client.db_factory() as s:
            return await fn(s)
    return client.portal.call(go)


def _learner_counts(client, learner_id: str, subject: str) -> dict[str, int]:
    async def fn(s):
        out = {}
        for t in pilot_cascade():
            col = t.c.id if t.name == "pilot_learners" else t.c.learner_id
            out[t.name] = (await s.execute(select(func.count()).select_from(t)
                                           .where(col == learner_id))).scalar_one()
        for t in storage_subject_tables():
            out[t.name] = (await s.execute(select(func.count()).select_from(t)
                                           .where(t.c.student_name == subject))).scalar_one()
        return out
    return _run(client, fn)


def _delete(client, campus_id, learner_id, **kw):
    return _run(client, lambda s: delete_pilot_learner(s, campus_id, learner_id, **kw))


def _audit_entries(client) -> list[dict]:
    r = client.get("/admin/audit", params={"limit": 200}, headers=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()["entries"]


@pytest.fixture
def world(client):
    w = World(client).seed()
    one, two = _scopes(w)
    w.journeys = {
        "one": journey(w, w.campus_one, w.learner_one, w.teacher_one),
        "two": journey(w, w.campus_two, w.learner_two, w.teacher_two),
    }
    # Household-shaped rows under each learner's institutional storage
    # subject, plus the per-learner data key, exactly as #608's own seed.
    _run(client, lambda s: seed_learner_one(s, one))
    _run(client, lambda s: seed_learner_one(s, two))
    # A HOUSEHOLD learner whose name equals the pilot learners' display
    # name. A delete keyed by display name would take this row with it.
    async def household(s):
        s.add(MasteryProfile(
            student_name=SHARED_DISPLAY_NAME, subject_area="mathematics", evidence_count=2,
            profile_enc=encrypt_json({"add_within_10": 0.5}, student_aad(
                "mastery_profiles", "profile_enc", SHARED_DISPLAY_NAME, "mathematics")),
        ))
        await s.commit()
    _run(client, household)
    return w


# ── Deletion removes every table, and only learner one's rows ──────────────

def test_deletion_removes_every_listed_table_and_leaves_the_same_named_learner(world):
    one, two = _scopes(world)
    before_one = _learner_counts(world.client, one.learner_id, one.storage_subject)
    before_two = _learner_counts(world.client, two.learner_id, two.storage_subject)
    # The seed must exercise every table in the cascade, or "removes every
    # table" would be vacuous for whichever one it skipped.
    for t in models.LEARNER_SCOPED_TABLES:
        assert before_one[t.name] > 0, t.name
    for name in ("pilot_roster_grants", "pilot_learners", "mastery_profiles",
                 "learner_profiles", "lesson_bookmarks"):
        assert before_one[name] > 0, name
    assert before_one == before_two

    result = _delete(world.client, world.campus_one, world.learner_one)

    after_one = _learner_counts(world.client, one.learner_id, one.storage_subject)
    assert all(v == 0 for v in after_one.values()), after_one
    assert result.deleted == {k: v for k, v in before_one.items() if v}
    assert result.signed_out_educators == 1
    assert _learner_counts(world.client, two.learner_id, two.storage_subject) == before_two

    # Learner two's content still DECRYPTS over HTTP: same display name,
    # same scores, intact snapshot, valid audit chain.
    w, t2 = world, world.teacher_two
    base = w.base(w.campus_two, w.learner_two)
    me = w.client.get(f"/pilot/me/learners/{w.learner_two}", headers=t2.headers)
    assert me.status_code == 200 and me.json()["display_name"] == SHARED_DISPLAY_NAME
    adm = w.journeys["two"][0]
    detail = w.client.get(f"{base}/assessments/{adm}", headers=t2.headers).json()
    assert detail["snapshot_verified"] is True
    assert "Some Support" in json.dumps(detail)
    assert w.client.get(f"{base}/assessments/{adm}/audit", headers=t2.headers).json()["chain_valid"]

    # The household learner sharing the display name is untouched.
    async def household(s):
        return (await s.execute(select(func.count()).select_from(MasteryProfile)
                                .where(MasteryProfile.student_name == SHARED_DISPLAY_NAME))).scalar_one()
    assert _run(world.client, household) == 1


def test_campus_configuration_is_kept(world):
    def config_counts():
        async def fn(s):
            return [(await s.execute(select(func.count()).select_from(m)
                                     .where(m.campus_id == world.campus_one))).scalar_one()
                    for m in (models.PilotCampusCycle, models.PilotBenchmarkAuthorization)]
        return _run(world.client, fn)
    before = config_counts()
    assert all(before)
    _delete(world.client, world.campus_one, world.learner_one)
    assert config_counts() == before


# ── Every read path afterwards ──────────────────────────────────────────────

def test_every_read_and_write_path_answers_the_uniform_404_after_deletion(world):
    w = world
    adm, pid = w.journeys["one"]
    random_reference = w.client.get(
        f"{w.base(w.campus_one, '1b4e28ba-2fa1-4d3b-a3f5-ef19b5a7633b')}/assessments",
        headers=w.teacher_one.headers)
    assert random_reference.status_code == 404
    _delete(w.client, w.campus_one, w.learner_one)

    # The old token was signed out by the deletion.
    stale = w.client.get(f"{w.base()}/assessments", headers=w.teacher_one.headers)
    assert stale.status_code == 401, stale.text
    # A fresh token for the same teacher reaches nothing about the learner.
    fresh = Teacher(w.teacher_one.id, ev=2)
    listing = w.client.get("/pilot/me/learners", headers=fresh.headers)
    assert listing.status_code == 200 and listing.json() == []
    me = w.client.get(f"/pilot/me/learners/{w.learner_one}", headers=fresh.headers)
    assert me.status_code == 404 and me.content == random_reference.content
    for method, url, body in _protected_requests(w, adm, pid):
        r = w.client.request(method, url, json=body, headers=fresh.headers)
        assert r.status_code == 404, (method, url, r.status_code, r.text)
        assert r.content == random_reference.content, (method, url)
    # Direct lookup of the old administration id through a DIFFERENT, still
    # authorized learner's path finds nothing either.
    other = w.base(w.campus_two, w.learner_two)
    for suffix in ("", "/audit"):
        r = w.client.get(f"{other}/assessments/{adm}{suffix}", headers=w.teacher_two.headers)
        assert r.status_code == 404 and r.content == random_reference.content
    # Re-granting the deleted learner is refused: there is no learner row.
    regrant = w.client.post(
        f"/pilot/campuses/{w.campus_one}/educators/{w.teacher_one.id}/learners/{w.learner_one}",
        headers=ADMIN)
    assert regrant.status_code == 404


# ── Caches: evicted through the real cache functions ────────────────────────

def test_caches_are_evicted_and_cannot_repopulate_from_deleted_rows(world):
    one, two = _scopes(world)
    primed_one = _run(world.client, lambda s: prime(s, one))
    _run(world.client, lambda s: prime(s, two))
    assert primed_one["mastery"] and primed_one["bookmark"]
    two_keys = sorted(k for k in all_cache_keys() if two.owns(k))
    assert len([k for k in all_cache_keys() if one.owns(k)]) == 5
    assert len(two_keys) == 5

    result = _delete(world.client, world.campus_one, world.learner_one)

    assert result.evicted_cache_entries == 5
    assert not [k for k in all_cache_keys() if one.owns(k)]
    assert sorted(k for k in all_cache_keys() if two.owns(k)) == two_keys
    # Re-reading through the real loaders finds nothing to cache from.
    # Re-reading through the real loaders yields exactly what a learner who
    # never had any data yields: nothing remained to cache from.
    again = _run(world.client, lambda s: prime(s, one))
    never = _run(world.client, lambda s: prime(s, LearnerScope.institutional(
        world.campus_one, "1b4e28ba-2fa1-4d3b-a3f5-ef19b5a7633b")))
    assert again == never
    assert again != primed_one


# ── Failure: nothing committed, nothing evicted, nothing logged ─────────────

def _snapshot(world):
    one, two = _scopes(world)

    async def versions(s):
        return sorted((await s.execute(select(ClassicalEducator.id, ClassicalEducator.credential_version)))
                      .all())
    return (_learner_counts(world.client, one.learner_id, one.storage_subject),
            _run(world.client, versions),
            sorted(k for k in all_cache_keys() if one.owns(k)),
            len([e for e in _audit_entries(world.client) if e.get("event") == "student.data_deleted"]))


def test_a_failure_before_commit_rolls_everything_back_and_does_not_evict(world):
    one, _ = _scopes(world)
    _run(world.client, lambda s: prime(s, one))
    before = _snapshot(world)
    assert before[2]  # caches primed, so "not evicted" is observable

    async def boom(db, result):
        raise RuntimeError("forced failure after every delete, before commit")

    with pytest.raises(RuntimeError):
        _delete(world.client, world.campus_one, world.learner_one, before_commit=boom)
    assert _snapshot(world) == before


def test_a_row_the_delete_key_missed_blocks_the_commit(world):
    """A grant row naming learner one under campus TWO is outside the
    (campus, learner) delete key but inside the learner-UUID recount, so the
    deletion must refuse rather than commit a partial erasure."""
    one, _ = _scopes(world)
    _run(world.client, lambda s: prime(s, one))

    async def misattribute(s):
        s.add(PilotRosterGrant(educator_id=world.teacher_two.id, campus_id=world.campus_two,
                               learner_id=world.learner_one))
        await s.commit()
    _run(world.client, misattribute)
    before = _snapshot(world)

    with pytest.raises(DeletionIncomplete) as exc:
        _delete(world.client, world.campus_one, world.learner_one)
    assert exc.value.remaining == {"pilot_roster_grants": 1}
    assert _snapshot(world) == before


def test_a_mid_cascade_database_error_rolls_everything_back(world, monkeypatch):
    one, _ = _scopes(world)
    _run(world.client, lambda s: prime(s, one))
    before = _snapshot(world)
    real = deletion.delete
    calls = {"n": 0}

    def failing_delete(table):
        calls["n"] += 1
        if calls["n"] == 5:  # partway through the pilot tables
            raise RuntimeError("forced failure mid-cascade")
        return real(table)

    monkeypatch.setattr(deletion, "delete", failing_delete)
    with pytest.raises(RuntimeError):
        _delete(world.client, world.campus_one, world.learner_one)
    assert calls["n"] == 5
    assert _snapshot(world) == before


def test_wrong_campus_or_malformed_ids_delete_nothing(world):
    one, two = _scopes(world)
    before = (_learner_counts(world.client, one.learner_id, one.storage_subject),
              _learner_counts(world.client, two.learner_id, two.storage_subject))
    for campus, learner in ((world.campus_two, world.learner_one),
                            (world.campus_one, world.learner_two),
                            (world.campus_one, "not-a-uuid"),
                            (world.campus_one, world.learner_one.upper()),
                            (world.campus_one, "1b4e28ba-2fa1-4d3b-a3f5-ef19b5a7633b")):
        with pytest.raises(LearnerNotFound):
            _delete(world.client, campus, learner)
    assert (_learner_counts(world.client, one.learner_id, one.storage_subject),
            _learner_counts(world.client, two.learner_id, two.storage_subject)) == before


# ── Tombstone ───────────────────────────────────────────────────────────────

def test_the_tombstone_is_one_content_free_audit_event(world):
    before = len(_audit_entries(world.client))
    result = _delete(world.client, world.campus_one, world.learner_one,
                     audit_context={"ip": "203.0.113.7", "user_agent": "synthetic-agent"})
    deleted = [e for e in _audit_entries(world.client) if e.get("event") == "student.data_deleted"]
    assert len(deleted) == 1
    entry = deleted[0]
    assert TOMBSTONE.fullmatch(entry["detail"]), entry["detail"]
    assert entry["detail"] == (
        f"pilot_learner_deleted campus={world.campus_one} learner={world.learner_one} "
        f"rows={result.total_rows} tables={len(result.deleted)}")
    assert entry.get("role") == "parent" and entry.get("success") is True
    assert "student" not in entry  # never a name field
    assert set(entry) <= {"ts", "event", "ip", "ua", "success", "role", "detail"}, entry
    # The whole audit view, and the result handed to a caller, carry no content.
    everything = json.dumps(_audit_entries(world.client)) + json.dumps(result.__dict__)
    for needle in CONTENT:
        assert needle not in everything, needle
    assert len(_audit_entries(world.client)) >= before + 1


def test_no_key_destruction_happens(world):
    """Per-learner cryptographic erasure is a human-only decision. The key
    row is retained (and only its unwrapped cache entry evicted)."""
    one, _ = _scopes(world)

    async def key_row(s):
        return await s.get(StudentKey, one.storage_subject)
    assert _run(world.client, key_row) is not None
    _delete(world.client, world.campus_one, world.learner_one)
    assert _run(world.client, key_row) is not None
    assert STORAGE_SUBJECT_EXEMPT.keys() == {"student_keys"}
    src = Path(deletion.__file__).read_text(encoding="utf-8")
    assert "destroy(" not in src


# ── Concurrency (Postgres row locks) ────────────────────────────────────────

def _educator_auth(teacher: Teacher) -> dict:
    return {"role": "educator", "sub": teacher.id, "ev": teacher.ev, "auth_method": "webauthn_uv"}


def test_a_teacher_write_in_flight_is_deleted_with_everything_else(client):
    """The REAL write-path re-check holds FOR SHARE on the learner row, so a
    deletion started mid-write waits, then sees and removes that write."""
    if client.backend != "postgres":
        pytest.skip("Row locks are a Postgres property; SQLite serializes writers instead")
    import routers.pilot_assessments as pa
    w = World(client).seed()
    adm, _ = journey(w, w.campus_one, w.learner_one, w.teacher_one)

    async def scenario():
        async with client.db_factory() as teacher_db, client.db_factory() as admin_db:
            # Exactly what every write route does first: _scope resolves the
            # learner AND pins the request's authorization context, which the
            # write-time _recheck requires (G1 integration: no pinned context
            # fails closed).
            _, learner = await pa._scope(teacher_db, _educator_auth(w.teacher_one),
                                         w.campus_one, w.learner_one)
            await pa._recheck(teacher_db, _educator_auth(w.teacher_one), learner)
            teacher_db.add(models.PilotProgressMonitoringSchedule(
                id="0b8a7c1e-3d2f-4e5a-9b6c-7d8e9f0a1b2c", administration_id=adm,
                plan_id="0b8a7c1e-3d2f-4e5a-9b6c-7d8e9f0a1b2d", campus_id=w.campus_one,
                learner_id=w.learner_one, measure="PSF", planned_dates='["2031-10-06"]',
                created_by=w.teacher_one.id))
            await teacher_db.flush()
            task = asyncio.create_task(delete_pilot_learner(admin_db, w.campus_one, w.learner_one))
            await asyncio.sleep(1.0)
            blocked = not task.done()
            await teacher_db.commit()
            result = await asyncio.wait_for(task, timeout=10)
            return blocked, result
    blocked, result = client.portal.call(scenario)
    assert blocked, "deletion did not wait for the in-flight write's FOR SHARE lock"
    assert result.deleted["pilot_progress_monitoring_schedules"] == 2
    one, _ = _scopes(w)
    assert all(v == 0 for v in _learner_counts(client, one.learner_id, one.storage_subject).values())


def test_a_teacher_write_that_waits_on_a_deletion_is_refused(client):
    if client.backend != "postgres":
        pytest.skip("Row locks are a Postgres property; SQLite serializes writers instead")
    from fastapi import HTTPException
    import routers.pilot_assessments as pa
    w = World(client).seed()
    journey(w, w.campus_one, w.learner_one, w.teacher_one)

    async def scenario():
        reached, release = asyncio.Event(), asyncio.Event()

        async def hold(db, result):
            reached.set()
            await release.wait()

        async with client.db_factory() as teacher_db, client.db_factory() as admin_db:
            # The request started (and pinned its context through _scope)
            # before the deletion began; its write-time re-check runs after.
            _, learner = await pa._scope(teacher_db, _educator_auth(w.teacher_one),
                                         w.campus_one, w.learner_one)
            deleting = asyncio.create_task(delete_pilot_learner(
                admin_db, w.campus_one, w.learner_one, before_commit=hold))
            await asyncio.wait_for(reached.wait(), timeout=10)
            write = asyncio.create_task(pa._recheck(teacher_db, _educator_auth(w.teacher_one), learner))
            await asyncio.sleep(1.0)
            waited = not write.done()
            release.set()
            await asyncio.wait_for(deleting, timeout=10)
            try:
                await asyncio.wait_for(write, timeout=10)
                outcome = "allowed"
            except HTTPException as exc:
                outcome = exc.status_code
            return waited, outcome
    waited, outcome = client.portal.call(scenario)
    assert outcome == 404
    assert waited, "the write's re-check did not wait on the deletion's lock"


def _third_teacher_with_membership(client, w: World) -> str:
    """A campus-one member who does NOT yet hold a grant for learner one,
    so the grant under test is a fresh INSERT rather than a re-enable."""
    from services.educator_access import provision_educator

    async def make():
        async with client.db_factory() as s:
            return (await provision_educator(s, "synthetic.teacher.three", "synthetic-passphrase-three-x"))["id"]
    teacher = client.portal.call(make)
    r = client.post(f"/pilot/campuses/{w.campus_one}/educators/{teacher}", headers=ADMIN)
    assert r.status_code == 204, r.text
    return teacher


def _grant_rows(client, learner_id: str) -> int:
    return _run(client, lambda s: _scalar(s, select(func.count()).select_from(PilotRosterGrant)
                                           .where(PilotRosterGrant.learner_id == learner_id)))


async def _scalar(s, stmt):
    return (await s.execute(stmt)).scalar_one()


def test_a_grant_in_flight_is_deleted_with_everything_else(client):
    """Grant first, then delete: the REAL grant handler holds FOR SHARE on
    the learner row until it commits, so the deletion waits and then
    removes the new grant too."""
    if client.backend != "postgres":
        pytest.skip("Row locks are a Postgres property; SQLite serializes writers instead")
    import routers.pilot_campuses as g1
    w = World(client).seed()
    teacher = _third_teacher_with_membership(client, w)

    async def scenario():
        reached, release = asyncio.Event(), asyncio.Event()
        async with client.db_factory() as grant_db, client.db_factory() as admin_db:
            real_commit = grant_db.commit

            async def held_commit():
                reached.set()
                await release.wait()
                await real_commit()
            grant_db.commit = held_commit
            grant = asyncio.create_task(g1.approve_roster_grant(
                w.campus_one, teacher, w.learner_one, auth={"role": "parent", "auth_method": "webauthn_uv"},
                db=grant_db))
            await asyncio.wait_for(reached.wait(), timeout=10)
            deleting = asyncio.create_task(delete_pilot_learner(admin_db, w.campus_one, w.learner_one))
            await asyncio.sleep(1.0)
            blocked = not deleting.done()
            release.set()
            await asyncio.wait_for(grant, timeout=10)
            result = await asyncio.wait_for(deleting, timeout=10)
            return blocked, result
    blocked, result = client.portal.call(scenario)
    assert blocked, "deletion did not wait for the in-flight grant's FOR SHARE lock"
    assert result.deleted["pilot_roster_grants"] == 2  # seeded grant + the racing one
    assert _grant_rows(client, w.learner_one) == 0


def test_a_grant_that_waits_on_a_deletion_is_refused(client):
    """Delete first, then grant: the grant waits on the deletion's lock,
    then finds no learner and answers the uniform 404, writing nothing."""
    if client.backend != "postgres":
        pytest.skip("Row locks are a Postgres property; SQLite serializes writers instead")
    from fastapi import HTTPException
    import routers.pilot_campuses as g1
    w = World(client).seed()
    teacher = _third_teacher_with_membership(client, w)

    async def scenario():
        reached, release = asyncio.Event(), asyncio.Event()

        async def hold(db, result):
            reached.set()
            await release.wait()

        async with client.db_factory() as grant_db, client.db_factory() as admin_db:
            deleting = asyncio.create_task(delete_pilot_learner(
                admin_db, w.campus_one, w.learner_one, before_commit=hold))
            await asyncio.wait_for(reached.wait(), timeout=10)
            grant = asyncio.create_task(g1.approve_roster_grant(
                w.campus_one, teacher, w.learner_one, auth={"role": "parent", "auth_method": "webauthn_uv"},
                db=grant_db))
            await asyncio.sleep(1.0)
            waited = not grant.done()
            release.set()
            await asyncio.wait_for(deleting, timeout=10)
            try:
                await asyncio.wait_for(grant, timeout=10)
                outcome = "allowed"
            except HTTPException as exc:
                outcome = (exc.status_code, exc.detail)
            return waited, outcome
    waited, outcome = client.portal.call(scenario)
    assert outcome == (404, "Record not found")
    assert waited, "the grant did not wait on the deletion's lock"
    assert _grant_rows(client, w.learner_one) == 0


# ── Guards: the cascade cannot silently miss a table ────────────────────────

def test_every_learner_bearing_pilot_table_is_in_the_cascade():
    """All active pilot learner content must be cascaded, including G2. Only the
    content-free post-deletion receipt is intentionally retained."""
    learner_bearing = {t.name for t in Base.metadata.sorted_tables
                       if t.name.startswith("pilot_") and "learner_id" in t.c
                       and t.name != "pilot_deletion_receipts"}
    learner_bearing.add("pilot_learners")
    assert learner_bearing == {t.name for t in pilot_cascade()}
    assert pilot_cascade()[-1].name == "pilot_learners"


def test_every_name_keyed_table_is_cascaded_or_named_as_exempt():
    named = {t.name for t in Base.metadata.sorted_tables if "student_name" in t.c}
    assert named == {t.name for t in storage_subject_tables()} | set(STORAGE_SUBJECT_EXEMPT)
    assert {t.name for t in storage_subject_tables()} >= {
        "mastery_profiles", "learner_profiles", "lesson_bookmarks", "session_transcripts"}


def test_the_model_doc_lists_the_cascade_and_states_the_backup_limit():
    doc = (API.parent / "docs/CANONICAL_ASSESSMENT_MODEL.md").read_text(encoding="utf-8")
    section = doc.split("## Deleting a pilot learner", 1)[1]
    for t in pilot_cascade():
        assert f"`{t.name}`" in section, t.name
    assert "services/pilot_learner_deletion.py" in section
    assert "may still hold encrypted historical copies" in section
    assert "human-only" in section
