"""Invite-only Valor pilot campus registry, deliberately isolated from households.

All educator reads are scoped at the query level to an active campus,
active membership, and individually granted immutable learner UUID.
There is no fallback to student_name, demo, parent, or public access.
"""
from __future__ import annotations

import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit import AuditEvent, audit_from_request, log_event
from core.config import settings
from core.database import (
    ClassicalEducator, PilotCampus, PilotEducatorCampus, PilotLearner,
    PilotRosterGrant, get_db,
)
from core import school_authorization as school_auth
from core.deps import _bearer, _validate_token, require_educator, require_elevated_parent
from core.encryption import aad_for, decrypt_json, encrypt_json
from core.learner_scope import LearnerScope, evict_learner
from services.educator_access import live_educator
from services.pilot_authz import ACTION_LEARNER_READ, resolve_campus_learner

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


async def _audit_grant_change(event: str, request: Optional[Request], **ids) -> None:
    """Durable evidence of an administrator's grant or membership change.
    UUIDs and versions only: never a display name. Written after the commit,
    by the admin action itself; a failed audit write never undoes the change
    (log_event swallows its own errors)."""
    detail = " ".join(f"{k}={v}" for k, v in ids.items())
    await log_event(event, role="parent", success=True, detail=detail,
                    **(audit_from_request(request) if request is not None else {}))


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
    # Every query must check ALL grant links, not trust a supplied campus
    # claim. services/pilot_authz.py is the one place that join lives, so a
    # learner read, a voice session and a tutoring turn all ask the same
    # question.
    ctx = await resolve_campus_learner(db, auth, learner_id, ACTION_LEARNER_READ)
    row = await db.get(PilotLearner, ctx.learner_id)
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
    # Storing a display name is storing learner data.
    await school_auth.require_authorized(db, campus.id)
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
    request: Request = None,
    auth: dict = Depends(require_elevated_parent),
    db: AsyncSession = Depends(get_db),
) -> None:
    _admin(auth)
    campus = await _campus(db, campus_id)
    # A grant links an educator to a learner's records; it is part of the
    # learner-data surface the school must have authorized.
    await school_auth.require_authorized(db, campus.id)
    teacher_id, learner_id = _id(educator_id), _id(learner_id)
    membership = await db.get(PilotEducatorCampus, (teacher_id, campus.id))
    teacher = await db.get(ClassicalEducator, teacher_id)
    # Hold the learner row FOR SHARE until the grant commits. Learner
    # deletion (services/pilot_learner_deletion.py) takes FOR UPDATE on it,
    # so a grant either commits before the deletion counts (and is deleted
    # with everything else) or waits and then finds no learner. A no-op on
    # SQLite, whose single writer lock serializes the two instead.
    pupil = (await db.execute(
        select(PilotLearner).where(PilotLearner.id == learner_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if (membership is None or not membership.enabled
            or teacher is None or not teacher.enabled
            or pupil is None or not pupil.enabled or pupil.campus_id != campus.id):
        raise HTTPException(status_code=404, detail="Record not found")
    grant = await db.get(PilotRosterGrant, (teacher_id, campus.id, pupil.id))
    changed, version = True, 1
    if grant is None:
        db.add(PilotRosterGrant(
            educator_id=teacher_id, campus_id=campus.id, learner_id=pupil.id,
        ))
    elif not grant.enabled:
        # A re-approval is a NEW grant version. Anything minted under the
        # version that was revoked must never revalidate (pilot_authz).
        grant.enabled = True
        grant.version += 1
        version = grant.version
    else:
        changed = False
    campus_uuid, learner_uuid = campus.id, pupil.id
    await db.commit()
    if changed:
        await _audit_grant_change(AuditEvent.PILOT_GRANT_APPROVED, request, campus=campus_uuid,
                                  educator=teacher_id, learner=learner_uuid, v=version)


@router.delete("/campuses/{campus_id}/educators/{educator_id}/learners/{learner_id}", status_code=204)
async def revoke_roster_grant(
    campus_id: str, educator_id: str, learner_id: str,
    request: Request = None,
    auth: dict = Depends(require_elevated_parent),
    db: AsyncSession = Depends(get_db),
) -> None:
    _admin(auth)
    teacher_id, campus_id, learner_id = _id(educator_id), _id(campus_id), _id(learner_id)
    grant = await db.get(PilotRosterGrant, (teacher_id, campus_id, learner_id))
    if grant is None:
        raise HTTPException(status_code=404, detail="Record not found")
    grant.enabled = False
    grant.version += 1
    # Invalidate every prior bearer token immediately, not only the UI cache.
    teacher = await db.get(ClassicalEducator, teacher_id)
    if teacher:
        teacher.credential_version += 1
    grant_uuid, version = grant.grant_id, grant.version
    await db.commit()
    # Drop every per-learner cache entry and the unwrapped data key, so
    # nothing derived for this learner outlives the grant in this process.
    evict_learner(LearnerScope.institutional(campus_id, learner_id))
    await _audit_grant_change(AuditEvent.PILOT_GRANT_REVOKED, request, campus=campus_id,
                              educator=teacher_id, learner=learner_id, grant=grant_uuid, v=version)


@router.post("/campuses/{campus_id}/educators/{educator_id}/disable", status_code=204)
async def disable_campus_membership(
    campus_id: str, educator_id: str,
    request: Request = None,
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
    grants = (await db.execute(
        select(PilotRosterGrant).where(
            PilotRosterGrant.educator_id == teacher_id,
            PilotRosterGrant.campus_id == campus_id,
        )
    )).scalars().all()
    # Every grant this membership carried becomes a new version, exactly as a
    # single revoke does, so no pilot_authz context minted before the disable
    # can ever revalidate, even if the membership is later re-approved and
    # the credential-version pin were somehow not enough on its own.
    for grant in grants:
        grant.version += 1
    granted = [grant.learner_id for grant in grants]
    await db.commit()
    await _audit_grant_change(AuditEvent.PILOT_MEMBERSHIP_DISABLED, request, campus=campus_id,
                              educator=teacher_id, grants=len(granted))
    # Same eviction as a single-grant revoke, for every learner this
    # educator held a grant for on this campus.
    for learner_id in granted:
        evict_learner(LearnerScope.institutional(campus_id, learner_id))


class LearnerSearch(BaseModel):
    # In the body, never a query string: a learner's name in a URL is
    # written into every access log and Referer header on the way here.
    query: str = Field(min_length=1, max_length=100)


async def _my_learner_rows(db: AsyncSession, auth: dict) -> list[PilotLearner]:
    _enabled()
    teacher = await live_educator(db, auth)
    return (await db.execute(
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


@router.get("/me/learners")
async def list_my_learners(
    auth: dict = Depends(require_educator), db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return [_render(row) for row in await _my_learner_rows(db, auth)]


@router.post("/me/learners/search")
async def search_my_learners(
    payload: LearnerSearch,
    auth: dict = Depends(require_educator), db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Name search / autocomplete over ONLY the learners this teacher holds a
    live grant for. Every result carries the learner's UUID and campus UUID,
    and every later protected operation takes the UUID: a name is never an
    authorization key. Two learners with the same name on two campuses are
    two results with two UUIDs, never a merged record. Ordered by UUID, so
    the order says nothing about how well a name matched."""
    needle = payload.query.strip().casefold()
    if not needle:
        return []
    return [
        item for item in (_render(row) for row in await _my_learner_rows(db, auth))
        if needle in item["display_name"].casefold()
    ]


@router.get("/me/learners/{learner_id}")
async def get_my_learner(
    learner_id: str, auth: dict = Depends(require_educator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return _render(await _assigned(db, auth, learner_id))


# ── School data authorization (see core/school_authorization.py) ────────────

class DataAuthorizationInput(BaseModel):
    notice_hash: str = Field(min_length=1, max_length=128)
    authorizer_name: str = Field(min_length=1, max_length=100)
    authorizer_role: Literal["administrator", "teacher"]


class DataAuthorizationRevoke(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


async def _admin_or_educator(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The verified administrator OR a live educator; the guard that
    matches the token's own role does the full validation."""
    payload = await _validate_token(request, credentials)
    if payload.get("role") == "educator":
        return await require_educator(request, credentials)
    return await require_elevated_parent(request, credentials, db)


async def _authorization_campus(db: AsyncSession, auth: dict, campus_id: str) -> PilotCampus:
    """The campus, if the caller is the administrator or an enabled member
    of it. Anyone else gets the uniform 404 the pilot code uses."""
    _enabled()
    if auth.get("role") == "educator":
        teacher = await live_educator(db, auth)
        campus = await _campus(db, campus_id)
        link = await db.get(PilotEducatorCampus, (teacher.id, campus.id))
        if link is None or not link.enabled:
            raise HTTPException(status_code=404, detail="Record not found")
        return campus
    _admin(auth)
    return await _campus(db, campus_id)


@router.get("/campuses/{campus_id}/data-authorization")
async def get_data_authorization(
    campus_id: str, auth: dict = Depends(_admin_or_educator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    campus = await _authorization_campus(db, auth, campus_id)
    return await school_auth.status_for(db, campus.id)


@router.post("/campuses/{campus_id}/data-authorization")
async def post_data_authorization(
    campus_id: str, payload: DataAuthorizationInput, request: Request,
    auth: dict = Depends(_admin_or_educator), db: AsyncSession = Depends(get_db),
):
    campus = await _authorization_campus(db, auth, campus_id)
    is_teacher = auth.get("role") == "educator"
    # A teacher records 'teacher', the administrator 'administrator'. A
    # mismatch is the uniform 404, not a distinguishing error.
    if payload.authorizer_role != ("teacher" if is_teacher else "administrator"):
        raise HTTPException(status_code=404, detail="Record not found")
    ref = auth["sub"] if is_teacher else school_auth.ADMIN_REF
    try:
        record, created = await school_auth.grant(
            db, campus.id, authorizer_role=payload.authorizer_role, authorizer_ref=ref,
            authorizer_name=payload.authorizer_name.strip(),
            presented_notice_hash=payload.notice_hash,
        )
    except school_auth.SchoolAuthorizationError as exc:
        return JSONResponse(status_code=exc.http_status,
                            content={"error": exc.code, "message": exc.message})
    if created:
        await log_event(
            AuditEvent.SCHOOL_DATA_AUTHORIZED, role=auth.get("role"), success=True,
            detail=f"campus={campus.id} authorizer_role={record.authorizer_role} "
                   f"notice={record.notice_hash[:12]}",
            **audit_from_request(request),
        )
    body = await school_auth.status_for(db, campus.id)
    return JSONResponse(status_code=201 if created else 200, content=body)


@router.post("/campuses/{campus_id}/data-authorization/revoke")
async def revoke_data_authorization(
    campus_id: str, payload: DataAuthorizationRevoke, request: Request,
    auth: dict = Depends(require_elevated_parent), db: AsyncSession = Depends(get_db),
) -> dict:
    """Administrator only. Stops further storage; deletes nothing."""
    _admin(auth)
    campus = await _campus(db, campus_id)
    row = await school_auth.revoke(db, campus.id, reason=(payload.reason or "").strip() or None)
    if row is not None:
        await log_event(
            AuditEvent.SCHOOL_DATA_AUTH_REVOKED, role="parent", success=True,
            detail=f"campus={campus.id} authorizer_role={row.authorizer_role} "
                   f"notice={row.notice_hash[:12]}",
            **audit_from_request(request),
        )
    return await school_auth.status_for(db, campus.id)
