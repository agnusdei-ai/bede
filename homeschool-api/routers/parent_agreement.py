"""
Gates ParentSetup and the rest of the parent-only UI behind the
platform-scope disclaimer/waiver in core/parent_agreement.py — see that
module's docstring for the full context (no diagnosis/screening,
reduced-supervision session format, DRAFT/pending-legal-review status).
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit import AuditEvent, audit_from_request, log_event
from core.database import ParentAgreement, get_db
from core.deps import require_parent
from core.parent_agreement import CURRENT_VERSION, SECTIONS
from models.schemas import ParentAgreementAcceptResponse, ParentAgreementStatus

router = APIRouter(prefix="/parent-agreement", tags=["parent-agreement"])

_ROW_KEY = "agreement"


@router.get("/status", response_model=ParentAgreementStatus)
async def get_status(
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> ParentAgreementStatus:
    row = await db.get(ParentAgreement, _ROW_KEY)
    accepted = bool(row and row.accepted_version == CURRENT_VERSION)
    return ParentAgreementStatus(
        version=CURRENT_VERSION,
        sections=SECTIONS,
        accepted=accepted,
        accepted_at=row.accepted_at.isoformat() if (row and accepted) else None,
    )


@router.post("/accept", response_model=ParentAgreementAcceptResponse)
async def accept(
    request: Request,
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> ParentAgreementAcceptResponse:
    row = await db.get(ParentAgreement, _ROW_KEY)
    if row is None:
        db.add(ParentAgreement(key=_ROW_KEY, accepted_version=CURRENT_VERSION))
    else:
        row.accepted_version = CURRENT_VERSION
    await db.commit()

    await log_event(
        AuditEvent.PARENT_AGREEMENT_ACCEPTED,
        role=auth.get("role"),
        detail=f"version={CURRENT_VERSION}",
        **audit_from_request(request),
    )
    return ParentAgreementAcceptResponse(accepted=True, version=CURRENT_VERSION)
