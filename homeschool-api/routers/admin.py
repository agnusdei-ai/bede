"""
Parent-only admin endpoints.

All responses are read-only, size-capped, and filtered by ExfiltrationGuard.
No data export or download path exists.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit import AuditEvent, audit_from_request, log_event, read_audit_log
from core.api_usage import get_usage_summary
from core.config import settings
from core.database import get_db
from core.deps import require_parent
from core import licensing
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


@router.get("/status")
async def system_status(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_parent),
):
    """Return system health metadata. No sensitive data included."""
    profiles = await list_profiles(db)
    usage = await get_usage_summary(db)

    license_info = licensing.get_license(settings.license_key)
    license_status = None
    if license_info is not None:
        license_status = {
            "tier": license_info.tier,
            "licensee": license_info.licensee,
            "seats": license_info.seats,
            "expires": license_info.expires.isoformat() if license_info.expires else None,
            "days_remaining": license_info.days_remaining,
            "is_expired": license_info.is_expired,
        }

    return {
        "voice_profiles_enrolled": len(profiles),
        "student_names":  profiles,
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
