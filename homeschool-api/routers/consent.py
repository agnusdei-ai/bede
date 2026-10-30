"""
Parental consent, collection pause, and parent review/export for one child.

All routes here are parent-only (require_parent) and audited. Their contract:

  GET  /household/consent                    household status (install ack, per-student)
  POST /household/consent                    one acknowledgement for every configured child
  GET  /consent/notice                       the current notice text and its hash
  GET  /consent/{student}                    consent and pause status (no child content)
  POST /consent/{student}                    grant consent. Body: method, notice_hash,
                                             parent_label (optional alias)
  POST /consent/{student}/revoke             withdraw consent. Body: reason (optional).
                                             Stops collection; deletes nothing.
  POST /consent/{student}/pause              pause collection (423 on collection routes)
  POST /consent/{student}/resume             resume collection
  GET  /pod/students/{student}/review        everything held about the child, decrypted

Read routes, including this export, keep working while collection is paused.
The grant/revoke/pause/resume writes are audited with counts and UUIDs only,
never the child's name in the detail text.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core import consent
from core.audit import AuditEvent, audit_from_request, log_event
from core.database import get_db
from core.deps import require_parent

router = APIRouter(tags=["consent"])


class HouseholdConsentRequest(BaseModel):
    notice_hash: str = Field(min_length=1, max_length=128)
    parent_label: str = Field(default="Parent", min_length=1, max_length=50)


class GrantConsentRequest(BaseModel):
    method: str = Field(default=consent.DEFAULT_METHOD, min_length=1, max_length=64)
    # The hash of the notice the parent was shown. Required so a grant can be
    # tied to the text it was given against, rather than to whatever is current.
    notice_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    parent_label: str = Field(default="Parent", min_length=1, max_length=50)


class RevokeConsentRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=200)


def _refuse(exc: consent.ConsentError) -> HTTPException:
    return HTTPException(
        status_code=exc.http_status,
        detail={"error": exc.code, "message": exc.message},
    )


async def audit_consent_result(request: Request, result: dict) -> None:
    """Audit newly recorded consents. Method and notice prefix only."""
    for key in ("granted", "refreshed"):
        for name in result[key]:
            await log_event(
                AuditEvent.CONSENT_GRANTED,
                role="parent",
                student_name=name,
                detail=f"method={consent.DEFAULT_METHOD} notice={consent.notice_hash()[:12]} {key}",
                **audit_from_request(request),
            )


# Household routes live under /household/consent, declared before the
# /consent/{student_name} routes, so a student literally named "household"
# cannot collide with them.
@router.get("/household/consent")
async def get_household_consent(
    _: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await consent.household_status(db)


@router.post("/household/consent", status_code=status.HTTP_201_CREATED)
async def grant_household_consent(
    req: HouseholdConsentRequest,
    request: Request,
    _: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from sqlalchemy import select

    from core.database import StudentConfig

    names = [r[0] for r in (await db.execute(select(StudentConfig.student_name))).all()]
    try:
        result = await consent.ensure_consent(
            db, names, parent_label=req.parent_label, presented_notice_hash=req.notice_hash
        )
    except consent.ConsentError as exc:
        raise _refuse(exc)
    await audit_consent_result(request, result)
    return result


@router.get("/consent/notice")
async def get_notice(_: dict = Depends(require_parent)) -> dict:
    return {
        "version": consent.NOTICE_VERSION,
        "hash": consent.notice_hash(),
        "text": consent.NOTICE_TEXT,
        "methods": [
            {"id": m.id, "label": m.label, "available": m.wired and m.parent_selectable}
            for m in consent.METHODS.values()
        ],
        "default_method": consent.DEFAULT_METHOD,
    }


@router.get("/consent/{student_name}")
async def get_consent_status(
    student_name: str,
    _: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await consent.status_for(db, student_name)


@router.post("/consent/{student_name}", status_code=status.HTTP_201_CREATED)
async def grant_consent(
    student_name: str,
    req: GrantConsentRequest,
    request: Request,
    _: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        record, created = await consent.grant(
            db,
            student_name,
            parent_label=req.parent_label,
            method=req.method,
            presented_notice_hash=req.notice_hash,
        )
    except consent.ConsentError as exc:
        raise _refuse(exc)
    if created:
        await log_event(
            AuditEvent.CONSENT_GRANTED,
            role="parent",
            student_name=student_name,
            detail=f"method={record.method} notice={record.notice_hash[:12]}",
            **audit_from_request(request),
        )
    return {
        "granted": True,
        "created": created,
        "method": record.method,
        "notice_version": consent.NOTICE_VERSION,
        "granted_at": record.granted_at.isoformat(),
    }


@router.post("/consent/{student_name}/revoke", status_code=status.HTTP_200_OK)
async def revoke_consent(
    student_name: str,
    req: RevokeConsentRequest,
    request: Request,
    _: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    record = await consent.revoke(db, student_name, reason=req.reason)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "no_active_consent", "message": "There is no active consent to withdraw."},
        )
    await log_event(
        AuditEvent.CONSENT_REVOKED,
        role="parent",
        student_name=student_name,
        detail=f"method={record.method}",
        **audit_from_request(request),
    )
    return {"revoked": True, "revoked_at": record.revoked_at.isoformat()}


@router.post("/consent/{student_name}/pause", status_code=status.HTTP_200_OK)
async def pause_collection(
    student_name: str,
    request: Request,
    _: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    paused_at = await consent.set_paused(db, student_name, paused=True)
    await log_event(
        AuditEvent.COLLECTION_PAUSED,
        role="parent",
        student_name=student_name,
        detail="collection paused",
        **audit_from_request(request),
    )
    return {"collection_paused": True, "paused_at": paused_at.isoformat()}


@router.post("/consent/{student_name}/resume", status_code=status.HTTP_200_OK)
async def resume_collection(
    student_name: str,
    request: Request,
    _: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await consent.set_paused(db, student_name, paused=False)
    await log_event(
        AuditEvent.COLLECTION_RESUMED,
        role="parent",
        student_name=student_name,
        detail="collection resumed",
        **audit_from_request(request),
    )
    return {"collection_paused": False}


@router.get("/pod/students/{student_name}/review")
async def export_student_data(
    student_name: str,
    request: Request,
    _: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from services.student_export import export_student

    payload = await export_student(db, student_name)
    await log_event(
        AuditEvent.DATA_EXPORTED,
        role="parent",
        student_name=student_name,
        detail=f"tables={len(payload['counts'])} rows={sum(payload['counts'].values())}",
        **audit_from_request(request),
    )
    return payload
