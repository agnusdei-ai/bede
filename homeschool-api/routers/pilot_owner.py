"""Owner-led Valor pilot operations: session plans and learner deletion.

Every route requires the operator's verified administrator passkey
(``require_elevated_parent`` plus G1's ``_admin`` webauthn_uv check). These
are the two acts the owner performs personally on the real build and keeps
evidence of; nothing here is simulated or automatic.

Deletion is the cascade the household ``student_deletion.py`` cannot do: a
pilot learner is keyed by an immutable campus UUID, never by name, so it is
removed by UUID across every G1/G2 table, re-counted after the delete, and
recorded as a content-free receipt whose SHA-256 the owner can verify.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit import AuditEvent, audit_from_request, log_event
from core.database import (
    ClassicalEducator, PilotCampus, PilotLearner, PilotRosterGrant, get_db,
)
from core.deps import require_elevated_parent
from core.pilot_journey_models import (
    PilotDecision, PilotDeletionReceipt, PilotEvidence, PilotRecommendation,
    PilotSessionLaunch, PilotSessionPlan,
)
from routers.pilot_campuses import _admin, _campus, _id, _render
from services.pilot_session import (
    SessionPlanInput, load_plan, render_launch, save_plan, validated_plan,
)

router = APIRouter(prefix="/pilot/owner", tags=["valor-pilot-owner"])

# Every table holding a row for a pilot learner. Order matters only for
# readability; there are no FK constraints between them.
LEARNER_TABLES = (
    ("roster_grants", PilotRosterGrant),
    ("evidence", PilotEvidence),
    ("recommendations", PilotRecommendation),
    ("decisions", PilotDecision),
    ("session_plans", PilotSessionPlan),
    ("session_launches", PilotSessionLaunch),
    ("learners", PilotLearner),
)


def _learner_col(model):
    return model.id if model is PilotLearner else model.learner_id


async def _learner_in_campus(db: AsyncSession, campus_id: str, learner_id: str) -> PilotLearner:
    campus = await _campus(db, campus_id)
    row = await db.get(PilotLearner, _id(learner_id))
    if row is None or row.campus_id != campus.id:
        raise HTTPException(status_code=404, detail="Record not found")
    return row


@router.get("/campuses")
async def list_campuses(auth: dict = Depends(require_elevated_parent),
                        db: AsyncSession = Depends(get_db)) -> list[dict]:
    _admin(auth)
    rows = (await db.execute(select(PilotCampus).order_by(PilotCampus.title))).scalars().all()
    return [{"campus_id": r.id, "title": r.title, "enabled": r.enabled} for r in rows]


@router.get("/campuses/{campus_id}/learners")
async def list_learners(campus_id: str, auth: dict = Depends(require_elevated_parent),
                        db: AsyncSession = Depends(get_db)) -> list[dict]:
    _admin(auth)
    campus = await _campus(db, campus_id)
    rows = (await db.execute(select(PilotLearner).where(PilotLearner.campus_id == campus.id)
                             .order_by(PilotLearner.id))).scalars().all()
    planned = set((await db.execute(select(PilotSessionPlan.learner_id)
                                    .where(PilotSessionPlan.campus_id == campus.id))).scalars())
    return [{**_render(r), "enabled": r.enabled, "has_plan": r.id in planned} for r in rows]


@router.get("/campuses/{campus_id}/learners/{learner_id}/plan")
async def get_plan(campus_id: str, learner_id: str,
                   auth: dict = Depends(require_elevated_parent),
                   db: AsyncSession = Depends(get_db)) -> dict:
    _admin(auth)
    learner = await _learner_in_campus(db, campus_id, learner_id)
    return {"learner_id": learner.id, "plan": await load_plan(db, learner)}


@router.put("/campuses/{campus_id}/learners/{learner_id}/plan")
async def set_plan(campus_id: str, learner_id: str, payload: SessionPlanInput,
                   request: Request, auth: dict = Depends(require_elevated_parent),
                   db: AsyncSession = Depends(get_db)) -> dict:
    _admin(auth)
    learner = await _learner_in_campus(db, campus_id, learner_id)
    plan = validated_plan(_render(learner)["display_name"], payload)
    await save_plan(db, learner, plan)
    await db.commit()
    await log_event(AuditEvent.PILOT_PLAN_SET,
                    role="parent", success=True,
                    detail=f"pilot_session_plan_set learner={learner.id}",
                    **audit_from_request(request))
    return {"learner_id": learner.id, "plan": plan}


@router.get("/campuses/{campus_id}/learners/{learner_id}/sessions")
async def learner_sessions(campus_id: str, learner_id: str,
                           auth: dict = Depends(require_elevated_parent),
                           db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Session receipts for the owner's evidence record."""
    _admin(auth)
    learner = await _learner_in_campus(db, campus_id, learner_id)
    rows = (await db.execute(select(PilotSessionLaunch)
                             .where(PilotSessionLaunch.learner_id == learner.id)
                             .order_by(PilotSessionLaunch.started_at.desc()))).scalars().all()
    return [render_launch(r) for r in rows]


class DeletionConfirm(BaseModel):
    # Both must match: the id guards against deleting the wrong row, the
    # typed name guards against a confirmation clicked without reading.
    confirm_learner_id: str = Field(min_length=36, max_length=36)
    confirm_display_name: str = Field(min_length=1, max_length=100)


def receipt_body(row: PilotDeletionReceipt) -> dict:
    return {
        "receipt_id": row.id, "campus_id": row.campus_id, "learner_id": row.learner_id,
        "actor": row.actor, "deleted_counts": json.loads(row.deleted_counts),
        "remaining_counts": json.loads(row.remaining_counts),
        "deleted_at": _canonical_utc(row.deleted_at),
    }


def _canonical_utc(value: datetime) -> str:
    """One text form for the hashed timestamp however the driver returns it:
    some return the stored value timezone-aware, others naive. Hashing the raw
    isoformat made a receipt fail its own check on read-back."""
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def receipt_hash(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


async def _counts(db: AsyncSession, learner_id: str) -> dict:
    out = {}
    for name, model in LEARNER_TABLES:
        out[name] = (await db.execute(select(func.count()).select_from(model)
                                      .where(_learner_col(model) == learner_id))).scalar_one()
    return out


@router.post("/campuses/{campus_id}/learners/{learner_id}/delete")
async def delete_learner(campus_id: str, learner_id: str, payload: DeletionConfirm,
                         request: Request, auth: dict = Depends(require_elevated_parent),
                         db: AsyncSession = Depends(get_db)) -> dict:
    _admin(auth)
    learner = await _learner_in_campus(db, campus_id, learner_id)
    display = _render(learner)["display_name"]
    if payload.confirm_learner_id != learner.id or payload.confirm_display_name.strip() != display:
        raise HTTPException(status_code=422,
                            detail="Confirmation does not match this learner's id and name")

    # End every session that could still reach this learner, immediately.
    holders = (await db.execute(select(PilotRosterGrant.educator_id)
                                .where(PilotRosterGrant.learner_id == learner.id))).scalars().all()
    for educator_id in set(holders):
        teacher = await db.get(ClassicalEducator, educator_id)
        if teacher:
            teacher.credential_version += 1

    deleted = await _counts(db, learner.id)
    for _, model in LEARNER_TABLES:
        await db.execute(delete(model).where(_learner_col(model) == learner.id))
    await db.flush()
    remaining = await _counts(db, learner.id)
    if any(remaining.values()):
        await db.rollback()
        raise HTTPException(status_code=500, detail="Deletion did not complete; nothing was removed")

    row = PilotDeletionReceipt(
        id=str(uuid.uuid4()), campus_id=learner.campus_id, learner_id=learner.id,
        actor=str(auth.get("sub") or "owner")[:100],
        deleted_counts=json.dumps(deleted, sort_keys=True),
        remaining_counts=json.dumps(remaining, sort_keys=True),
        receipt_sha256="", deleted_at=datetime.now(timezone.utc),
    )
    row.receipt_sha256 = receipt_hash(receipt_body(row))
    db.add(row)
    await db.commit()
    # No display name in the audit trail: the receipt id and UUID suffice.
    await log_event(AuditEvent.STUDENT_DATA_DELETED, role="parent", success=True,
                    detail=f"pilot_learner_deleted learner={learner.id} receipt={row.id}",
                    **audit_from_request(request))
    return {**receipt_body(row), "receipt_sha256": row.receipt_sha256}


@router.get("/deletion-receipts")
async def list_receipts(auth: dict = Depends(require_elevated_parent),
                        db: AsyncSession = Depends(get_db)) -> list[dict]:
    _admin(auth)
    rows = (await db.execute(select(PilotDeletionReceipt)
                             .order_by(PilotDeletionReceipt.deleted_at.desc()))).scalars().all()
    return [{**receipt_body(r), "receipt_sha256": r.receipt_sha256,
             "hash_verified": receipt_hash(receipt_body(r)) == r.receipt_sha256} for r in rows]
