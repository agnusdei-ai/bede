"""
Parent-only admin endpoints.

All responses are read-only, size-capped, and filtered by ExfiltrationGuard.
No data export or download path exists.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel, Field

from core.audit import AuditEvent, audit_from_request, log_event, read_audit_log
from core.api_usage import get_usage_summary
from core.config import settings
from core.database import LicenseConfig, get_db
from core.deps import require_parent
from core import license_state, licensing
from models.schemas import UsageSummary
from services.voice_auth import list_profiles

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/audit")
async def view_audit_log(
    request: Request,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_parent),
):
    """View recent audit log entries (parent only, inline display, max 200 records)."""
    safe_limit = min(limit, 200)
    entries = await read_audit_log(db, safe_limit)
    await log_event(
        AuditEvent.ADMIN_VIEW_AUDIT,
        role="parent",
        detail=f"limit={safe_limit}",
        **audit_from_request(request),
    )
    return {"entries": entries, "count": len(entries)}


def _license_status_payload() -> dict | None:
    """The effective license (core/license_state.py — DB-applied key wins
    over env) rendered for the parent UI. None when nothing is configured
    and nothing is required (dev / demo)."""
    s = license_state.current()
    if s.info is None and s.ok:
        return None
    payload = {
        "ok": s.ok,
        "required": s.required,
        "source": s.source,
        "problem": s.problem,
    }
    if s.info is not None:
        payload.update({
            "tier": s.info.tier,
            "licensee": s.info.licensee,
            "seats": s.info.seats,
            "expires": s.info.expires.isoformat() if s.info.expires else None,
            "days_remaining": s.info.days_remaining,
            "is_expired": s.info.is_expired,
        })
    return payload


class ApplyLicenseRequest(BaseModel):
    license_key: str = Field(..., min_length=1, max_length=4096)


@router.get("/license")
async def license_status(_: dict = Depends(require_parent)):
    """Current effective license, for the parent settings card."""
    return {"license": _license_status_payload()}


@router.post("/license")
async def apply_license(
    body: ApplyLicenseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_parent),
):
    """Apply a new license key from the parent UI — the renewal/upgrade
    path that needs no .env edit and no restart. The key is verified
    offline (signature + expiry) before anything is stored; a valid key is
    persisted to the DB and takes effect immediately, lifting the
    license-required gate if it was up."""
    key = body.license_key.strip()
    try:
        info = licensing.verify_license(key)
    except licensing.InvalidLicenseError as exc:
        raise HTTPException(status_code=422, detail=f"That license key is not valid: {exc}") from exc
    if info.is_expired:
        raise HTTPException(
            status_code=422,
            detail=(
                f"That license expired on {info.expires.isoformat()} — "
                "paste a current one, or contact support for a renewal."
            ),
        )

    row = await db.get(LicenseConfig, "license")
    if row is None:
        db.add(LicenseConfig(key="license", license_text=key))
    else:
        row.license_text = key
    await db.commit()

    state = license_state.refresh(
        settings.license_key, key,
        required=settings.is_production and not settings.is_demo_deployment,
    )
    await log_event(
        AuditEvent.LICENSE_APPLIED,
        role="parent",
        detail=f"tier={info.tier} licensee={info.licensee!r} seats={info.seats} expires={info.expires}",
        **audit_from_request(request),
    )
    return {"license": _license_status_payload(), "gated": not state.ok}


@router.get("/status")
async def system_status(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_parent),
):
    """Return system health metadata. No sensitive data included."""
    profiles = await list_profiles(db)
    usage = await get_usage_summary(db)

    license_status = _license_status_payload()

    return {
        "voice_profiles_enrolled": len(profiles),
        "student_names":  profiles,
        "locale":         settings.locale,
        "encryption":     "AES-256-GCM",
        "key_storage":    "KEK-wrapped DATA_KEY in managed PostgreSQL",
        "audit_log":      "AES-256-GCM encrypted rows in managed PostgreSQL",
        "usage": usage,
        "license": license_status,
    }


@router.get("/usage/{student_name}", response_model=UsageSummary)
async def student_usage(
    student_name: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_parent),
) -> UsageSummary:
    """
    Per-student Anthropic API usage/cost estimate — see core/api_usage.py.
    Always 200s, even with zero recorded usage yet (an all-zero
    UsageSummary), rather than 404ing — this is an estimate dashboard,
    not evidence-gated content like the diagnostic summary endpoints.
    """
    usage = await get_usage_summary(db, student_name)
    return UsageSummary(**usage)
