"""
Encrypted audit log backed by managed PostgreSQL.

Each event is independently AES-256-GCM encrypted before the row is inserted,
so the database provider sees only opaque BYTEA values — never plaintext.

log_event() opens its own session so callers do not need to pass one in.
This keeps audit writes independent of the main request transaction and
means a rollback in a route handler will not suppress the audit entry.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ── Audit event constants ────────────────────────────────────────────────────

class AuditEvent:
    AUTH_SUCCESS             = "auth.success"
    AUTH_FAILURE             = "auth.failure"
    VOICE_ENROLL             = "voice.enroll"
    VOICE_VERIFY_PASS        = "voice.verify.pass"
    VOICE_VERIFY_FAIL        = "voice.verify.fail"
    VOICE_OVERRIDE           = "voice.parent_override"
    SESSION_START            = "session.start"
    SESSION_END              = "session.end"
    TUTOR_CHAT               = "tutor.chat"
    ADMIN_VIEW_AUDIT         = "admin.view_audit"
    ACCESS_DENIED            = "access.denied"
    TOKEN_INVALID            = "token.invalid"
    TOKEN_FINGERPRINT_MISMATCH = "token.fingerprint_mismatch"
    RATE_LIMITED             = "rate_limited"
    SUSPICIOUS_REQUEST       = "suspicious_request"
    SAFEGUARDING             = "safeguarding.alert"
    SUMMARY_EMAILED          = "summary.emailed"
    DIAGNOSTIC_VIEW          = "diagnostic.view"
    FEEDBACK_SUBMITTED       = "feedback.submitted"
    PARENT_AGREEMENT_ACCEPTED = "parent.agreement_accepted"


# ── Write ────────────────────────────────────────────────────────────────────

async def log_event(
    event: str,
    *,
    ip: str = "unknown",
    user_agent: str = "",
    role: Optional[str] = None,
    student_name: Optional[str] = None,
    success: bool = True,
    detail: str = "",
) -> None:
    """
    Encrypt and persist one audit event. Creates its own short-lived DB session
    so callers don't need to manage transaction boundaries for audit writes.
    Failures are caught and logged locally — never propagated to the caller.
    """
    from core.database import AsyncSessionLocal, AuditLog
    from core.encryption import encrypt

    entry: dict = {
        "ts": _now_iso(),
        "event": event,
        "ip": ip,
        "ua": user_agent[:200],
        "success": success,
    }
    if role:
        entry["role"] = role
    if student_name:
        entry["student"] = student_name
    if detail:
        entry["detail"] = detail[:500]

    try:
        blob = encrypt(json.dumps(entry, separators=(",", ":")).encode())
        async with AsyncSessionLocal() as db:
            db.add(AuditLog(event_enc=blob))
            await db.commit()
    except Exception as exc:
        # Audit failure must never crash the request
        log.warning("Audit write failed: %s", exc)


# ── Read ─────────────────────────────────────────────────────────────────────

async def read_audit_log(db, limit: int = 100) -> list[dict]:
    """
    Decrypt and return the most recent audit entries.
    Returns only safe display fields — never raw embeddings or key material.
    """
    from core.database import AuditLog
    from core.encryption import decrypt

    result = await db.execute(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(min(limit, 200))
    )
    rows = result.scalars().all()

    safe_fields = {"ts", "event", "ip", "ua", "success", "role", "student", "detail"}
    entries = []
    for row in rows:
        try:
            entry = json.loads(decrypt(row.event_enc))
            entries.append({k: v for k, v in entry.items() if k in safe_fields})
        except Exception:
            entries.append({"_corrupt": True})
    return entries


# ── Request context helper ────────────────────────────────────────────────────

def audit_from_request(request) -> dict:
    """Extract loggable fields from a FastAPI Request."""
    return {
        "ip": (request.client.host if request.client else "unknown"),
        "user_agent": request.headers.get("user-agent", ""),
    }
