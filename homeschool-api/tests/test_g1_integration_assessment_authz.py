"""G1 integration: the canonical assessment routes (#607) authorize through
the shared pilot authorization context (#606), not a parallel lookup.

Two cross-lane properties neither lane could test alone:

1. A copied, valid learner UUID from another campus is refused on every
   assessment route by ``services.pilot_authz.resolve_campus_learner``, with
   the same byte-identical 404 as a UUID that never existed.
2. The write-time re-check (``routers.pilot_assessments._recheck``) is bound
   to the grant VERSION the request started under. A grant revoked and then
   re-approved while a write is in flight is a new grant version, so the
   write is refused even though a fresh lookup would find the grant enabled.
   Before integration the re-check re-resolved from scratch and passed.

Real HTTP through the assembled app, on SQLite and on Postgres as a
non-superuser role (the ``client`` fixture from
``test_canonical_assessment_api.py``; ``BEDE_REQUIRE_PG=1`` makes an
unreachable Postgres a failure). Synthetic data only.
"""
from __future__ import annotations

import pytest

import routers.pilot_campuses as g1
import services.pilot_authz as pilot_authz
from canonical_assessment_fixtures import ADMIN, boy_vendor_report
from core.audit import AuditEvent
from test_canonical_assessment_api import (  # noqa: F401 (fixtures, incl. the autouse limiter reset)
    _all_counts, _reset_rate_limiter, client, world,
)

ADMIN_CLAIMS = {"role": "parent", "auth_method": "webauthn_uv"}


def _journey(w):
    adm = w.administer()
    aid = adm["assessment_id"]
    w.finalize_with(aid, boy_vendor_report())
    w.evidence(aid)
    prop = w.proposal(aid)
    return aid, prop


def _decide_url(w, aid, pid, campus=None, learner=None):
    return f"{w.base(campus, learner)}/assessments/{aid}/proposals/{pid}/decision"


# ── 1. Copied cross-campus UUIDs go through the shared context ─────────────

def test_cross_campus_copied_uuid_is_denied_by_the_shared_context(world, monkeypatch):
    w = world
    aid, prop = _journey(w)
    other_aid = w.administer(teacher=w.teacher_two, campus=w.campus_two,
                             learner=w.learner_two)["assessment_id"]

    seen: list[tuple] = []
    real = pilot_authz.resolve_campus_learner

    async def spy(db, token, learner_id, action, claimed_campus_id=None):
        try:
            ctx = await real(db, token, learner_id, action, claimed_campus_id)
        except Exception as exc:
            seen.append((token.get("sub"), learner_id, claimed_campus_id, type(exc).__name__))
            raise
        seen.append((token.get("sub"), learner_id, claimed_campus_id, ctx.campus_id))
        return ctx

    monkeypatch.setattr(pilot_authz, "resolve_campus_learner", spy)
    # routers.pilot_campuses imported the name directly; patch it there too so
    # _assigned (the first gate) is observed as well.
    monkeypatch.setattr(g1, "resolve_campus_learner", spy)

    t1, t2 = w.teacher_one, w.teacher_two
    attempts = [
        # Teacher Two copies Learner One's valid UUID under Campus One's path.
        ("GET", f"{w.base()}/assessments", t2),
        ("GET", f"{w.base()}/assessments/{aid}", t2),
        ("GET", f"{w.base()}/data-day?cycle=valor_q1", t2),
        ("POST", _decide_url(w, aid, prop["proposal_id"]), t2),
        # Teacher Two on their OWN campus path with Learner One's UUID.
        ("GET", f"{w.base(w.campus_two, w.learner_one)}/assessments", t2),
        # Teacher One with Learner One's UUID under Campus Two's path.
        ("GET", f"{w.base(w.campus_two, w.learner_one)}/assessments", t1),
        ("POST", f"{w.base(w.campus_two, w.learner_one)}/assessments/{aid}/transitions", t1),
        # Teacher One with Learner Two's (same display name) record id.
        ("GET", f"{w.base()}/assessments/{other_aid}", t1),
    ]
    before = _all_counts(w.client)
    bodies = set()
    for method, url, teacher in attempts:
        body = None
        if url.endswith("/decision"):
            body = {"action": "approve", "expected_version": 1}
        elif url.endswith("/transitions"):
            # A VALID body, so the refusal is authorization, never validation.
            body = {"action": "mark_ready", "expected_state": "DRAFT", "resolution": None}
        r = w.client.request(method, url, json=body, headers=teacher.headers)
        assert r.status_code == 404, (method, url, r.status_code, r.text)
        bodies.add(r.content)
    assert len(bodies) == 1, bodies
    assert _all_counts(w.client) == before
    # Every refusal that reached a learner lookup was decided by the shared
    # context resolver, and it never resolved a context for a foreign learner.
    assert seen, "the shared pilot_authz resolver was never invoked"
    for sub, learner, _claimed, outcome in seen:
        if sub == t2.id and learner == w.learner_one:
            assert outcome == "HTTPException"

    # Control: the authorized teacher on the right path resolves a context
    # pinned to Campus One, and that context is what the route uses.
    seen.clear()
    r = w.client.get(f"{w.base()}/assessments/{aid}", headers=t1.headers)
    assert r.status_code == 200
    assert (t1.id, w.learner_one, w.campus_one, w.campus_one) in seen


# ── 2. Revoke + re-grant mid-request is refused at write time ───────────────

def _mid_request(w, monkeypatch, action):
    """Run ``action`` (a coroutine on a FRESH session) mid-request: after
    ``_scope`` has pinned the request's authorization context and checked
    the educator, before the handler stages any write or re-checks.

    Hooked on the ``live_educator`` call that ends ``_scope`` (it runs the
    real check first, then the action). Interleaving later, at ``_recheck``,
    cannot work on SQLite: the request then already holds the database's
    single write lock, so a concurrent revoke cannot commit at all. That is
    SQLite serializing the two, not the guard under test."""
    import routers.pilot_assessments as pa
    real = pa.live_educator
    calls = {"n": 0}

    async def interleave(db, auth):
        calls["n"] += 1
        teacher = await real(db, auth)
        assert db.info.get(pa._CTX_KEY) is not None  # pinned before the change
        if calls["n"] == 1:
            async with w.client.db_factory() as s:
                await action(s)
        return teacher

    monkeypatch.setattr(pa, "live_educator", interleave)
    calls["restore"] = lambda: monkeypatch.setattr(pa, "live_educator", real)
    return calls


def _revoked_in_flight(w):
    async def read():
        from core.audit import read_audit_log
        async with w.client.db_factory() as s:
            return await read_audit_log(s, limit=500)
    return [e for e in w.client.portal.call(read)
            if e.get("event") == AuditEvent.AUTHZ_REVOKED_IN_FLIGHT]


def _decide(w, aid, prop):
    return w.client.post(_decide_url(w, aid, prop["proposal_id"]),
                         json={"action": "approve", "expected_version": 1},
                         headers=w.teacher_one.headers)


def test_revoke_and_regrant_through_the_real_handlers_mid_request_is_refused(world, monkeypatch):
    """End to end with the REAL admin handlers. The revoke also bumps the
    educator's credential version, so more than one check refuses here; the
    next test isolates the grant-version pin on its own."""
    w = world
    aid, prop = _journey(w)
    before = _all_counts(w.client)

    async def revoke_then_regrant(s):
        await g1.revoke_roster_grant(w.campus_one, w.teacher_one.id, w.learner_one,
                                     auth=dict(ADMIN_CLAIMS), db=s)
        await g1.approve_roster_grant(w.campus_one, w.teacher_one.id, w.learner_one,
                                      auth=dict(ADMIN_CLAIMS), db=s)

    calls = _mid_request(w, monkeypatch, revoke_then_regrant)
    r = _decide(w, aid, prop)
    calls["restore"]()
    assert calls["n"] == 1
    assert (r.status_code, r.json()) == (404, {"detail": "Record not found"})
    assert _all_counts(w.client) == before

    # The re-grant itself is real: a NEW request under the new grant version
    # (a new token, since the revoke bumped the credential version) succeeds.
    w.teacher_one.ev += 1
    w.decide(aid, prop["proposal_id"], {"action": "approve", "expected_version": 1})


def test_grant_level_revoke_and_regrant_mid_request_is_refused_by_the_version_pin(world, monkeypatch):
    """Only the GRANT moves: disabled (version +1), then re-enabled (version
    +1). The educator's credential version is untouched, so the token, the
    account and a fresh lookup all still pass; the grant is enabled again.
    The one thing that refuses this write is the pinned grant version."""
    w = world
    aid, prop = _journey(w)
    before = _all_counts(w.client)

    async def regrant_at_grant_level(s):
        from core.database import PilotRosterGrant
        key = (w.teacher_one.id, w.campus_one, w.learner_one)
        grant = await s.get(PilotRosterGrant, key)
        grant.enabled, grant.version = False, grant.version + 1
        await s.commit()
        grant.enabled, grant.version = True, grant.version + 1
        await s.commit()

    calls = _mid_request(w, monkeypatch, regrant_at_grant_level)
    r = _decide(w, aid, prop)
    calls["restore"]()
    assert calls["n"] == 1
    assert (r.status_code, r.json()) == (404, {"detail": "Record not found"})
    assert _all_counts(w.client) == before
    assert any("stage=assessment.write" in e.get("detail", "") for e in _revoked_in_flight(w))
    # Same token, new request: resolves the NEW grant version and succeeds.
    w.decide(aid, prop["proposal_id"], {"action": "approve", "expected_version": 1})


def test_an_unrelated_change_mid_request_still_commits(world, monkeypatch):
    """Control: the pin refuses a moved grant, not every concurrent change.
    Teacher Two's grant on Campus Two moving leaves this request's grant alone."""
    w = world
    aid, prop = _journey(w)

    async def unrelated(s):
        from core.database import PilotRosterGrant
        other = await s.get(PilotRosterGrant, (w.teacher_two.id, w.campus_two, w.learner_two))
        other.version += 1
        await s.commit()

    calls = _mid_request(w, monkeypatch, unrelated)
    r = _decide(w, aid, prop)
    calls["restore"]()
    assert calls["n"] == 1 and r.status_code == 200, r.text
