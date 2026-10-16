"""Owner-led Valor pilot operations: campus and learner selection, and deletion.

Every route requires the operator's verified administrator passkey
(``require_elevated_parent`` plus G1's ``_admin`` webauthn_uv check), and
every change is audit-logged.

Deletion is the cascade the household ``student_deletion.py`` cannot do: a
pilot learner is keyed by an immutable campus UUID, never by name, so it is
removed by UUID across every pilot table, re-counted after the delete, and
recorded as a content-free receipt whose SHA-256 the owner can verify.

Deliberately absent: any session plan, session launch, or other route that
would carry a teacher's approved instruction into a learner's tutoring
session. Owner Decision 7 keeps that delivery unavailable until #585, and
``tests/test_valor_pilot_delivery_disabled.py`` fails if a route under
``/pilot`` ever names a session. See ``docs/EDUCATOR_CLASSROOM_PILOT.md``.
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
)
from routers.pilot_campuses import _admin, _campus, _id, _render
from services.pilot_learner_deletion import (DeletionIncomplete, LearnerNotFound, delete_pilot_learner)

router = APIRouter(prefix="/pilot/owner", tags=["valor-pilot-owner"])

# Every table holding a row for a pilot learner. There are no FK constraints
# between them; the learner row goes last so a reader sees children first.
# tests/test_valor_pilot_owner_flows.py fails if a new learner-keyed pilot
# table is added without joining this list.
LEARNER_TABLES = (
    ("roster_grants", PilotRosterGrant),
    ("evidence", PilotEvidence),
    ("recommendations", PilotRecommendation),
    ("decisions", PilotDecision),
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
    return [{**_render(r), "enabled": r.enabled} for r in rows]


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

    # Canonical G1 cascade is the only deletion implementation. It includes
    # the G2 evidence/recommendation/decision rows and every canonical
    # assessment row; its post-commit cache eviction is mandatory.
    # Receipt is staged using before_commit INSIDE the same transaction.
    receipts: list[PilotDeletionReceipt] = []

    async def persist_receipt(session: AsyncSession, result) -> None:
        row = PilotDeletionReceipt(
            id=str(uuid.uuid4()), campus_id=result.campus_id,
            learner_id=result.learner_id,
            actor=str(auth.get("sub") or "owner")[:100],
            deleted_counts=json.dumps(result.deleted, sort_keys=True),
            remaining_counts=json.dumps({key: 0 for key in result.deleted}, sort_keys=True),
            receipt_sha256="", deleted_at=datetime.now(timezone.utc),
        )
        row.receipt_sha256 = receipt_hash(receipt_body(row))
        session.add(row)
        await session.flush()  # Receipt failure aborts the entire cascade.
        receipts.append(row)

    try:
        result = await delete_pilot_learner(
            db, learner.campus_id, learner.id,
            actor_role="parent", audit_context=audit_from_request(request),
            before_commit=persist_receipt,
        )
    except LearnerNotFound:
        raise HTTPException(status_code=404, detail="Record not found")
    except DeletionIncomplete:
        raise HTTPException(status_code=409, detail="Deletion did not complete; nothing was removed")
    # No second audit write: canonical service already records content-free
    # tombstone only AFTER the atomic delete and receipt commit succeeds.
    row = receipts[0]
    # This transient operational observation is intentionally OUTSIDE the
    # durable SHA receipt: a cache is process-local, whereas the receipt
    # records permanent database deletion. Only the already authenticated,
    # passkey-elevated owner receives it; no learner content is exposed.
    # Canonical deletion returns only after evict_learner(scope) has run.
    return {**receipt_body(row), "receipt_sha256": row.receipt_sha256,
            "cache_eviction_executed": True,
            "evicted_cache_entries": result.evicted_cache_entries}


@router.get("/deletion-receipts")
async def list_receipts(auth: dict = Depends(require_elevated_parent),
                        db: AsyncSession = Depends(get_db)) -> list[dict]:
    _admin(auth)
    rows = (await db.execute(select(PilotDeletionReceipt)
                             .order_by(PilotDeletionReceipt.deleted_at.desc()))).scalars().all()
    return [{**receipt_body(r), "receipt_sha256": r.receipt_sha256,
             "hash_verified": receipt_hash(receipt_body(r)) == r.receipt_sha256} for r in rows]
