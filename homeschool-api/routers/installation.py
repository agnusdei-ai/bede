"""
Installation authorization: current receipt state, withdrawal, and the
(unavailable) verification stubs. docs/INSTALLATION_AUTHORIZATION_FLOW.md.

  GET  /installation/status                 state, chain validity, processing enabled
  POST /installation/withdraw               appends a `withdrawn` record
  POST /installation/verification/start     409 verification_method_unavailable
  POST /installation/verification/complete  409 verification_method_unavailable

Status and withdrawal depend only on the local receipt: a license-server or
console outage changes nothing here, and a local withdrawal takes effect on the
next request. No endpoint here can mark a receipt verified.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core import installation_receipt as ir
from core.audit import AuditEvent, audit_from_request, log_event
from core.database import InstallationInventory, get_db
from core.deps import require_installation_actor

router = APIRouter(prefix="/installation", tags=["installation"])

# No parental-verification method is approved (docs/PARENTAL_VERIFICATION_PROPOSAL.md).
VERIFICATION_METHOD_AVAILABLE = False


def _unavailable() -> JSONResponse:
    return JSONResponse(status_code=409, content={
        "error": "verification_method_unavailable",
        "message": "No parental verification method is approved yet, so the receipt stays "
                   "pending and child-data processing stays off.",
    })


@router.get("/status")
async def installation_status(
    auth: dict = Depends(require_installation_actor), db: AsyncSession = Depends(get_db),
) -> dict:
    st = ir.current()
    inv = (await db.execute(
        select(InstallationInventory).order_by(InstallationInventory.registered_at.desc()).limit(1)
    )).scalar_one_or_none()
    return {
        "state": st.state,
        "mode": st.mode,
        "receipt_id": st.receipt_id,
        "chain_valid": st.chain_valid,
        "reasons": list(st.reasons),
        "records": st.record_count,
        "processing_enabled": st.processing_enabled,
        "accepted_at": st.accepted_at,
        "location_id": st.location_id,
        "verification_method_available": VERIFICATION_METHOD_AVAILABLE,
        "registered": None if inv is None else {
            "receipt_id": inv.receipt_id,
            "registered_at": inv.registered_at.isoformat(),
            "license_server_outcome": inv.license_server_outcome,
        },
    }


@router.post("/withdraw")
async def withdraw(
    request: Request, auth: dict = Depends(require_installation_actor),
    db: AsyncSession = Depends(get_db),
):
    st = ir.current()
    role = auth.get("role")
    if st.mode == "family" and role != "parent":
        raise HTTPException(status_code=403, detail="Only the parent can withdraw a family authorization")
    try:
        new = ir.append_withdrawal(by_role=role or "unknown")
    except ir.ReceiptError as exc:
        return JSONResponse(status_code=exc.http_status,
                            content={"error": exc.code, "message": exc.message})
    if st.mode == "school" and st.location_id:
        # Stop campus storage too; the runtime school panel is the same gate.
        from core import school_authorization as sa
        from core.database import PilotCampus
        if await db.get(PilotCampus, st.location_id) is not None:
            await sa.revoke(db, st.location_id, reason="installation receipt withdrawn")
    await log_event(
        AuditEvent.INSTALLATION_WITHDRAWN, role=role, success=True,
        detail=f"mode={st.mode} receipt={st.receipt_id}", **audit_from_request(request),
    )
    return {"state": new.state, "processing_enabled": new.processing_enabled, "receipt_id": new.receipt_id}


@router.post("/verification/start")
async def verification_start(auth: dict = Depends(require_installation_actor)):
    return _unavailable()


@router.post("/verification/complete")
async def verification_complete(auth: dict = Depends(require_installation_actor)):
    return _unavailable()
