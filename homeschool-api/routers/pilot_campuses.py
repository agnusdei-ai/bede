"""Invite-only Valor pilot campus registry, deliberately isolated from households.

All educator reads are scoped at the query level to an active campus,
active membership, and individually granted immutable learner UUID.
There is no fallback to student_name, demo, parent, or public access.
"""
from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import (
    ClassicalEducator, PilotCampus, PilotEducatorCampus, PilotLearner,
    PilotRosterGrant, get_db,
)
from core.deps import require_educator, require_elevated_parent
from core.encryption import aad_for, decrypt_json, encrypt_json
from core.learner_scope import LearnerScope, evict_learner
from services.educator_access import live_educator

router = APIRouter(prefix="/pilot", tags=["valor-pilot"])


class CampusInput(BaseModel):
    title: str = Field(min_length=2, max_length=100)


class LearnerInput(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)


def _enabled() -> None:
    if not settings.educator_pilot_enabled or settings.is_demo_deployment:
        raise HTTPException(status_code=403, detail="Institutional pilot is disabled")


def _id(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError("Noncanonical UUID")
    except (ValueError, AttributeError, TypeError):
        # No enumeration of absent or malformed learner IDs.
        raise HTTPException(status_code=404, detail="Record not found")
    return str(parsed)


def _admin(auth: dict) -> None:
    _enabled()
    if auth.get("role") != "parent" or auth.get("auth_method") != "webauthn_uv":
        raise HTTPException(status_code=403, detail="Verified administrator passkey required")


async def _campus(db: AsyncSession, campus_id: str) -> PilotCampus:
    row = await db.get(PilotCampus, _id(campus_id))
    if row is None or not row.enabled:
        raise HTTPException(status_code=404, detail="Record not found")
    return row


def _learner_aad(campus_id: str, learner_id: str) -> bytes:
    return aad_for("pilot_learners", "display_enc", f"{campus_id}:{learner_id}")


async def _assigned(db: AsyncSession, auth: dict, learner_id: str) -> PilotLearner:
    _enabled()
    teacher = await live_educator(db, auth)
    # Every query must check ALL grant links, not trust a supplied campus claim.
    row = (await db.execute(
        select(PilotLearner)
        .join(PilotCampus, PilotCampus.id == PilotLearner.campus_id)
        .join(PilotEducatorCampus,
              (PilotEducatorCampus.campus_id == PilotLearner.campus_id)
              & (PilotEducatorCampus.educator_id == teacher.id))
        .join(PilotRosterGrant,
              (PilotRosterGrant.campus_id == PilotLearner.campus_id)
              & (PilotRosterGrant.learner_id == PilotLearner.id)
              & (PilotRosterGrant.educator_id == teacher.id))
        .where(PilotLearner.id == _id(learner_id))
        .where(PilotLearner.enabled.is_(True),
               PilotCampus.enabled.is_(True),
               PilotEducatorCampus.enabled.is_(True),
               PilotRosterGrant.enabled.is_(True))
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return row


def _render(row: PilotLearner) -> dict:
    detail = decrypt_json(row.display_enc, _learner_aad(row.campus_id, row.id))
    return {"learner_id": row.id, "campus_id": row.campus_id,
            "display_name": detail["display_name"]}


@router.post("/campuses", status_code=201)
async def create_campus(
    payload: CampusInput, auth: dict = Depends(require_elevated_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _admin(auth)
    row = PilotCampus(id=str(uuid.uuid4()), title=payload.title.strip())
    db.add(row)
    await db.commit()
    return {"campus_id": row.id, "title": row.title}


@router.post("/campuses/{campus_id}/learners", status_code=201)
async def create_learner(
    campus_id: str, payload: LearnerInput,
    auth: dict = Depends(require_elevated_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _admin(auth)
    campus = await _campus(db, campus_id)
    learner_id = str(uuid.uuid4())
    row = PilotLearner(
        id=learner_id, campus_id=campus.id,
        display_enc=encrypt_json(
            {"display_name": payload.display_name.strip()},
            _learner_aad(campus.id, learner_id),
        ),
    )
    db.add(row)
    await db.commit()
    return _render(row)


@router.post("/campuses/{campus_id}/educators/{educator_id}", status_code=204)
async def approve_educator_membership(
    campus_id: str, educator_id: str,
    auth: dict = Depends(require_elevated_parent),
    db: AsyncSession = Depends(get_db),
) -> None:
    _admin(auth)
    campus = await _campus(db, campus_id)
    teacher = await db.get(ClassicalEducator, _id(educator_id))
    if teacher is None or not teacher.enabled:
        raise HTTPException(status_code=404, detail="Record not found")
    link = await db.get(PilotEducatorCampus, (teacher.id, campus.id))
    if link is None:
        db.add(PilotEducatorCampus(educator_id=teacher.id, campus_id=campus.id))
    else:
        link.enabled = True
    await db.commit()


@router.post("/campuses/{campus_id}/educators/{educator_id}/learners/{learner_id}", status_code=204)
async def approve_roster_grant(
    campus_id: str, educator_id: str, learner_id: str,
    auth: dict = Depends(require_elevated_parent),
    db: AsyncSession = Depends(get_db),
) -> None:
    _admin(auth)
    campus = await _campus(db, campus_id)
    teacher_id, learner_id = _id(educator_id), _id(learner_id)
    membership = await db.get(PilotEducatorCampus, (teacher_id, campus.id))
    teacher = await db.get(ClassicalEducator, teacher_id)
    pupil = await db.get(PilotLearner, learner_id)
    if (membership is None or not membership.enabled
            or teacher is None or not teacher.enabled
            or pupil is None or not pupil.enabled or pupil.campus_id != campus.id):
        raise HTTPException(status_code=404, detail="Record not found")
    grant = await db.get(PilotRosterGrant, (teacher_id, campus.id, pupil.id))
    if grant is None:
        db.add(PilotRosterGrant(
            educator_id=teacher_id, campus_id=campus.id, learner_id=pupil.id,
        ))
    else:
        grant.enabled = True
    await db.commit()


@router.delete("/campuses/{campus_id}/educators/{educator_id}/learners/{learner_id}", status_code=204)
async def revoke_roster_grant(
    campus_id: str, educator_id: str, learner_id: str,
    auth: dict = Depends(require_elevated_parent),
    db: AsyncSession = Depends(get_db),
) -> None:
    _admin(auth)
    teacher_id, campus_id, learner_id = _id(educator_id), _id(campus_id), _id(learner_id)
    grant = await db.get(PilotRosterGrant, (teacher_id, campus_id, learner_id))
    if grant is None:
        raise HTTPException(status_code=404, detail="Record not found")
    grant.enabled = False
    # Invalidate every prior bearer token immediately, not only the UI cache.
    teacher = await db.get(ClassicalEducator, teacher_id)
    if teacher:
        teacher.credential_version += 1
    await db.commit()
    # Drop every per-learner cache entry and the unwrapped data key, so
    # nothing derived for this learner outlives the grant in this process.
    evict_learner(LearnerScope.institutional(campus_id, learner_id))


@router.post("/campuses/{campus_id}/educators/{educator_id}/disable", status_code=204)
async def disable_campus_membership(
    campus_id: str, educator_id: str,
    auth: dict = Depends(require_elevated_parent),
    db: AsyncSession = Depends(get_db),
) -> None:
    _admin(auth)
    teacher_id, campus_id = _id(educator_id), _id(campus_id)
    link = await db.get(PilotEducatorCampus, (teacher_id, campus_id))
    if link is None:
        raise HTTPException(status_code=404, detail="Record not found")
    link.enabled = False
    teacher = await db.get(ClassicalEducator, teacher_id)
    if teacher:
        teacher.credential_version += 1
    granted = (await db.execute(
        select(PilotRosterGrant.learner_id).where(
            PilotRosterGrant.educator_id == teacher_id,
            PilotRosterGrant.campus_id == campus_id,
        )
    )).scalars().all()
    await db.commit()
    # Same eviction as a single-grant revoke, for every learner this
    # educator held a grant for on this campus.
    for learner_id in granted:
        evict_learner(LearnerScope.institutional(campus_id, learner_id))


@router.get("/me/learners")
async def list_my_learners(
    auth: dict = Depends(require_educator), db: AsyncSession = Depends(get_db),
) -> list[dict]:
    _enabled()
    teacher = await live_educator(db, auth)
    rows = (await db.execute(
        select(PilotLearner)
        .join(PilotCampus, PilotCampus.id == PilotLearner.campus_id)
        .join(PilotEducatorCampus,
              (PilotEducatorCampus.campus_id == PilotLearner.campus_id)
              & (PilotEducatorCampus.educator_id == teacher.id))
        .join(PilotRosterGrant,
              (PilotRosterGrant.learner_id == PilotLearner.id)
              & (PilotRosterGrant.campus_id == PilotLearner.campus_id)
              & (PilotRosterGrant.educator_id == teacher.id))
        .where(PilotLearner.enabled.is_(True),
               PilotCampus.enabled.is_(True),
               PilotEducatorCampus.enabled.is_(True),
               PilotRosterGrant.enabled.is_(True))
        .order_by(PilotLearner.id)
    )).scalars().all()
    return [_render(row) for row in rows]


@router.get("/me/learners/{learner_id}")
async def get_my_learner(
    learner_id: str, auth: dict = Depends(require_educator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return _render(await _assigned(db, auth, learner_id))
