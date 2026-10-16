"""Real HTTP and DB checks for the read-only source-backed pilot diagnostic.

Reuses canonical assessment's synthetic two-campus real-app fixture.
Every test is run on SQLite and (when configured) non-superuser Postgres;
an unavailable required Postgres backend fails via BEDE_REQUIRE_PG=1.
"""
from __future__ import annotations

import uuid

from test_canonical_assessment_api import (
    _reset_rate_limiter, client, world, full_journey,
)


def url(w, learner_id=None):
    return f"/pilot/me/learners/{learner_id or w.learner_one}/diagnostic"


def test_no_evidence_is_explicit_and_not_an_invented_diagnosis(world):
    r = world.client.get(url(world), headers=world.teacher_one.headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["learner_id"] == world.learner_one
    assert data["status"] == "no_evidence"
    assert data["sources"] == [] and data["has_more"] is False
    assert "No finalized" in data["message"]
    assert "score" not in data and "band" not in data


def test_real_finalized_source_is_cited_without_invented_score(world):
    aid, _ = full_journey(world)
    r = world.client.get(url(world), headers=world.teacher_one.headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "evidence_available" and len(d["sources"]) == 1
    src = d["sources"][0]
    assert src["assessment_id"] == aid
    assert src["instrument"] == "dibels8"
    assert src["administration_purpose"] == "benchmark"
    assert len(src["snapshot_sha256"]) == 64
    assert set(src) == {
        "evidence_id", "assessment_id", "instrument", "measure", "grade",
        "administered_at", "administration_purpose",
        "snapshot_sha256", "recorded_at",
    }
    assert "score" not in src and "placement" not in src
    assert "does not diagnose" in d["message"]


def test_identical_display_names_never_cross_campus_or_enumerate(world):
    full_journey(world)
    ref = world.client.get(url(world, str(uuid.uuid4())),
                           headers=world.teacher_two.headers)
    assert ref.status_code == 404
    foreign = world.client.get(url(world), headers=world.teacher_two.headers)
    assert foreign.status_code == 404 and foreign.content == ref.content
    own = world.client.get(url(world, world.learner_two),
                           headers=world.teacher_two.headers)
    assert own.status_code == 200
    assert own.json()["learner_id"] == world.learner_two
    assert own.json()["sources"] == []
    for bad in ("not-a-uuid", "00000000-0000-0000-0000-000000000000",
                world.learner_one.upper()):
        res = world.client.get(url(world, bad), headers=world.teacher_two.headers)
        assert res.status_code == 404 and res.content == ref.content


def test_revoke_makes_old_teacher_token_unusable(world):
    original = world.client.get(url(world), headers=world.teacher_one.headers)
    assert original.status_code == 200
    from canonical_assessment_fixtures import ADMIN
    revoked = world.client.delete(
        f"/pilot/campuses/{world.campus_one}/educators/{world.teacher_one.id}"
        f"/learners/{world.learner_one}", headers=ADMIN)
    assert revoked.status_code == 204, revoked.text
    after = world.client.get(url(world), headers=world.teacher_one.headers)
    assert after.status_code in (401, 404)
    # No success payload or data while the previous credential is stale.
    assert "sources" not in after.text


def test_fresh_grant_check_refuses_access_if_revoked_mid_read(world, monkeypatch):
    """Simulates a revoked grant after the initial read, before response release."""
    from services import pilot_authz

    async def no_longer_valid(_ctx):
        return False

    monkeypatch.setattr(pilot_authz, "revalidate", no_longer_valid)
    response = world.client.get(url(world), headers=world.teacher_one.headers)
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Record not found"}
    assert "sources" not in response.text


def test_tampered_source_never_leaves_the_diagnostic_route(world):
    """The response must not present a mismatched source hash as valid evidence."""
    from sqlalchemy import update
    from core.pilot_assessment_models import PilotAssessmentEvidence
    full_journey(world)

    async def tamper():
        async with world.client.db_factory() as session:
            await session.execute(update(PilotAssessmentEvidence).values(snapshot_sha256="0" * 64))
            await session.commit()

    world.client.portal.call(tamper)
    response = world.client.get(url(world), headers=world.teacher_one.headers)
    assert response.status_code == 409
    assert response.json() == {"detail": "Verified assessment evidence is unavailable"}
    assert "sources" not in response.text
