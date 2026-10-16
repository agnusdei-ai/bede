"""G1: the shared authorization context and its fail-closed revalidation.

Drives the assembled app over real HTTP (tests/g1_harness.py). Runs on SQLite
by default and on Postgres when G1_TEST_DATABASE_URL is set. Synthetic
identities only.
"""
import pytest
from fastapi import HTTPException

import services.pilot_authz as pilot_authz
from g1_harness import SAME_NAME, legacy_config, legacy_world, world  # noqa: F401 (fixtures)


def _resolve(w, teacher_id, learner, campus=None):
    """Resolve a context with the claims a passkey login issues, at the
    teacher's current credential version."""
    claims = {"role": "educator", "sub": teacher_id, "auth_method": "webauthn_uv",
              "ev": w.credential_version(teacher_id)}

    async def go():
        async with w.factory() as s:
            return await pilot_authz.resolve_campus_learner(
                s, claims, learner, pilot_authz.ACTION_LEARNER_READ, claimed_campus_id=campus,
            )
    return w.run(go)


def test_same_campus_read_succeeds_and_cross_campus_reads_are_denied(world):
    w = world
    own = w.client.get(f"/pilot/me/learners/{w.learner_one}", headers=w.teacher(w.teacher_one))
    assert own.status_code == 200
    assert own.json() == {"learner_id": w.learner_one, "campus_id": w.campus_one,
                          "display_name": SAME_NAME}
    denied = w.client.get(f"/pilot/me/learners/{w.learner_one}", headers=w.teacher(w.teacher_two))
    assert (denied.status_code, denied.json()) == (404, {"detail": "Record not found"})
    listing = w.client.get("/pilot/me/learners", headers=w.teacher(w.teacher_two)).json()
    assert [r["learner_id"] for r in listing] == [w.learner_two]


def test_context_carries_server_resolved_campus_and_grant_identity(world):
    w = world
    ctx = _resolve(w, w.teacher_one, w.learner_one)
    assert ctx.principal_id == w.teacher_one
    assert ctx.campus_id == w.campus_one
    assert ctx.learner_id == w.learner_one
    assert ctx.grant_version == 1 and len(ctx.grant_id) == 36
    # A client-supplied campus is only ever compared, never trusted.
    with pytest.raises(HTTPException) as exc:
        _resolve(w, w.teacher_one, w.learner_one, campus=w.campus_two)
    assert (exc.value.status_code, exc.value.detail) == (404, "Record not found")
    assert _resolve(w, w.teacher_one, w.learner_one, campus=w.campus_one).campus_id == w.campus_one


def test_revalidation_ends_on_revoke_and_never_returns_after_regrant(world):
    w = world
    ctx = _resolve(w, w.teacher_one, w.learner_one)
    assert w.run(pilot_authz.revalidate, ctx) is True
    w.revoke(w.campus_one, w.teacher_one, w.learner_one)
    assert w.run(pilot_authz.revalidate, ctx) is False
    # Re-approving the grant makes a NEW version. The old context stays dead.
    w.grant(w.campus_one, w.teacher_one, w.learner_one)
    assert w.run(pilot_authz.revalidate, ctx) is False
    fresh = _resolve(w, w.teacher_one, w.learner_one)
    assert fresh.grant_id == ctx.grant_id
    # 1 -> revoke 2 -> re-approve 3: both routes advance the version.
    assert (ctx.grant_version, fresh.grant_version) == (1, 3)
    assert w.run(pilot_authz.revalidate, fresh) is True


def test_a_grant_version_change_alone_ends_the_context(world):
    """Independent of the credential version: if anything advances the
    grant's version, every context minted under the old one is dead."""
    w = world
    ctx = _resolve(w, w.teacher_one, w.learner_one)

    async def bump():
        from sqlalchemy import update
        from core.database import PilotRosterGrant
        async with w.factory() as s:
            await s.execute(update(PilotRosterGrant)
                            .where(PilotRosterGrant.grant_id == ctx.grant_id)
                            .values(version=PilotRosterGrant.version + 1))
            await s.commit()
    w.run(bump)
    assert w.credential_version(w.teacher_one) == ctx.credential_version
    assert w.run(pilot_authz.revalidate, ctx) is False


def test_revalidation_fails_closed_when_the_database_cannot_answer(world, monkeypatch):
    w = world
    ctx = _resolve(w, w.teacher_one, w.learner_one)

    class Broken:
        def __call__(self):
            raise RuntimeError("database unavailable")

    import core.database as database
    monkeypatch.setattr(database, "AsyncSessionLocal", Broken())
    assert w.run(pilot_authz.revalidate, ctx) is False


def test_legacy_name_routes_are_denied_over_http_once_any_campus_exists(world):
    w = world
    for path in ("/educators/me/roster", "/educators/me/locuto-capacity",
                 f"/educators/me/students/{SAME_NAME}/config",
                 f"/educators/me/students/{SAME_NAME}/assessments",
                 f"/educators/me/students/{SAME_NAME}/activity",
                 f"/educators/me/students/{SAME_NAME}/diagnostic",
                 f"/educators/me/students/{SAME_NAME}/dibels-progress"):
        r = w.client.get(path, headers=w.teacher(w.teacher_one))
        assert r.status_code == 404, (path, r.status_code, r.text)
    # The admin-side legacy roster import is closed too.
    r = w.client.put(f"/educators/accounts/{w.teacher_one}/roster",
                     json={"configs": [legacy_config(SAME_NAME)]}, headers=w.admin())
    assert r.status_code == 404


def test_disabling_every_campus_does_not_reopen_legacy_name_routes(world):
    w = world

    async def disable_all():
        from sqlalchemy import update
        from core.database import PilotCampus
        async with w.factory() as s:
            await s.execute(update(PilotCampus).values(enabled=False))
            await s.commit()
    w.run(disable_all)
    r = w.client.get("/educators/me/roster", headers=w.teacher(w.teacher_one))
    assert r.status_code == 404


def test_legacy_roster_replacement_that_removes_a_learner_revokes(legacy_world):
    w = legacy_world
    one = w.teacher_one
    before = w.credential_version(one)
    token = w.teacher(one)
    assert w.client.get("/educators/me/roster", headers=token).status_code == 200

    # Adding a learner is not a revocation: the version is unchanged.
    r = w.client.put(f"/educators/accounts/{one}/roster", headers=w.admin(), json={
        "configs": [legacy_config(w.extra["name_one"]), legacy_config("Synthetic Learner Three")]})
    assert r.status_code == 200
    assert w.credential_version(one) == before
    assert w.client.get("/educators/me/roster", headers=token).status_code == 200

    # Removing one IS a revocation, exactly as the pilot revoke route is.
    r = w.client.put(f"/educators/accounts/{one}/roster", headers=w.admin(), json={
        "configs": [legacy_config("Synthetic Learner Three")]})
    assert r.status_code == 200
    assert w.credential_version(one) == before + 1
    assert w.client.get("/educators/me/roster", headers=token).status_code == 401
    fresh = w.client.get("/educators/me/roster", headers=w.teacher(one))
    assert [c["student_name"] for c in fresh.json()] == ["Synthetic Learner Three"]
