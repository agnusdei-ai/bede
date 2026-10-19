"""Synthetic G3: a deliberate operator stop must revoke only its campus.

This is engineering validation, never production-school evidence or Pilot GO.
"""
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import select

import routers.pilot_owner as owner
from core.database import PilotCampus, PilotEducatorCampus, PilotLearner, PilotRosterGrant
from routers.pilot_campuses import get_my_learner, list_my_learners
from routers.pilot_owner import CampusStopConfirm, disable_pilot_campus, list_campuses
from test_valor_pilot_g2_journey import ADMIN, db, token, two_campuses  # noqa: F401


def req():
    return Request({"type": "http", "client": ("127.0.0.1", 1),
                    "headers": [(b"user-agent", b"synthetic-test")]})


@pytest.mark.asyncio
async def test_campus_stop_needs_admin_passkey_and_exact_typed_confirmation(db):
    ta, _, a, _, la, _ = await two_campuses(db)
    title = (await db.get(PilotCampus, a)).title
    confirmation = CampusStopConfirm(confirm_campus_id=a, confirm_title=title)
    with pytest.raises(HTTPException) as exc:
        await disable_pilot_campus(a, confirmation, req(),
            auth={"role": "parent", "auth_method": "password"}, db=db)
    assert exc.value.status_code == 403

    for bad in (CampusStopConfirm(confirm_campus_id=a, confirm_title="Wrong campus"),
                CampusStopConfirm(confirm_campus_id=a, confirm_title=title + " extra")):
        with pytest.raises(HTTPException) as exc:
            await disable_pilot_campus(a, bad, req(), auth=ADMIN, db=db)
        assert exc.value.status_code == 422

    assert (await db.get(PilotCampus, a)).enabled
    tok = await token(db, ta)
    assert (await get_my_learner(la, auth=tok, db=db))["learner_id"] == la


@pytest.mark.asyncio
async def test_emergency_stop_denies_old_and_fresh_tokens_without_deleting_other_campus(db, monkeypatch):
    ta, tb, a, b, la, lb = await two_campuses(db)
    old_a, old_b = await token(db, ta), await token(db, tb)
    campus = await db.get(PilotCampus, a)
    assert (await get_my_learner(la, auth=old_a, db=db))["learner_id"] == la
    assert (await get_my_learner(lb, auth=old_b, db=db))["learner_id"] == lb

    captured = []
    async def log(event, **details):
        captured.append((event, details))
    monkeypatch.setattr(owner, "log_event", log)

    out = await disable_pilot_campus(
        a, CampusStopConfirm(confirm_campus_id=a, confirm_title=campus.title),
        req(), auth=ADMIN, db=db)
    assert out["status"] == "disabled"
    assert out["prior_educator_sessions_invalidated"] is True
    assert out["learner_records_preserved"] is True
    assert out["grants_revoked"] == out["memberships_disabled"] == 1
    assert len(captured) == 1 and captured[0][0] == "pilot.campus_disabled"
    assert "Example Learner" not in captured[0][1]["detail"]

    for tok in (old_a, await token(db, ta)):
        with pytest.raises(HTTPException) as exc:
            await get_my_learner(la, auth=tok, db=db)
        assert exc.value.status_code in (401, 404)
    assert await list_my_learners(auth=await token(db, ta), db=db) == []

    # Records survive a stop, but every grant and membership is revoked.
    assert await db.get(PilotLearner, la) is not None
    member = (await db.execute(select(PilotEducatorCampus).where(
        PilotEducatorCampus.campus_id == a))).scalar_one()
    grant = (await db.execute(select(PilotRosterGrant).where(
        PilotRosterGrant.campus_id == a))).scalar_one()
    assert member.enabled is False
    assert grant.enabled is False and grant.version > 1

    assert (await get_my_learner(lb, auth=old_b, db=db))["learner_id"] == lb
    assert (await db.get(PilotCampus, b)).enabled is True
    campuses = await list_campuses(auth=ADMIN, db=db)
    assert {row["campus_id"]: row["enabled"] for row in campuses} == {a: False, b: True}

    # A second stop does not create a second operation or silently re-enable.
    with pytest.raises(HTTPException) as exc:
        await disable_pilot_campus(
            a, CampusStopConfirm(confirm_campus_id=a, confirm_title=campus.title),
            req(), auth=ADMIN, db=db)
    assert exc.value.status_code == 404
    assert len(captured) == 1
