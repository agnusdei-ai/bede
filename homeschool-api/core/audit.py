"""
Encrypted audit log backed by managed PostgreSQL.

Each event is independently AES-256-GCM encrypted before the row is inserted,
so the database provider sees only opaque BYTEA values — never plaintext.

log_event() opens its own session so callers do not need to pass one in.
This keeps audit writes independent of the main request transaction and
means a rollback in a route handler will not suppress the audit entry.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

log = logging.getLogger(__name__)

# Holds strong references to in-flight log_event_nowait() tasks — asyncio
# only keeps a WEAK reference to a task once nothing else holds one, so a
# fire-and-forget call with nothing tracking it can get garbage-collected
# mid-write on a busy event loop. Discarded via the task's own done
# callback once it finishes, so this never grows unbounded.
_background_tasks: set[asyncio.Task] = set()


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
    STUDENT_DATA_DELETED     = "student.data_deleted"
    LICENSE_APPLIED          = "license.applied"
    ANOMALY_ALERT            = "security.anomaly_alert"
    MODERATION_FLAGGED       = "moderation.flagged"
    TOOL_INVOKED             = "tool.invoked"
    TOOL_CALL_SUPPRESSED     = "tool.call_suppressed"


# ── Anomaly detection (AIUC-1 E009) ─────────────────────────────────────────
# The audit log used to be write-only — every security event was durably
# recorded but nothing ever looked back at the pattern. This is a lightweight,
# in-process sliding-window watch over specific security-relevant event
# types, mirroring core/middleware.py's RateLimitMiddleware bucket approach
# (no new infra, no persistence across restarts, resets on redeploy). It's
# sized for what it actually is: a defense-in-depth signal for a self-hosted
# single-family deployment, not a SIEM — the goal is the parent finding out
# about a sustained brute-force/probing attempt in real time, not forensic-
# grade anomaly detection.

_ANOMALY_RULES: dict[str, tuple[int, float]] = {
    # event -> (occurrences, window_seconds) that trigger an alert from one IP
    AuditEvent.AUTH_FAILURE: (5, 600),
    AuditEvent.TOKEN_FINGERPRINT_MISMATCH: (3, 600),
    AuditEvent.ACCESS_DENIED: (8, 600),
    AuditEvent.VOICE_VERIFY_FAIL: (5, 600),
    AuditEvent.SUSPICIOUS_REQUEST: (1, 1),  # ExfiltrationGuard hits are alert-worthy on their own
    # 3 in 10 min, not 1 — a single moderation flag is routine (a blocked
    # turn already redirects the child in the moment); a repeated pattern
    # from one address is the part worth a parent's attention.
    AuditEvent.MODERATION_FLAGGED: (3, 600),
    # A generous ceiling on ordinary tool use — a busy, multi-subject
    # session can legitimately rack up dozens of request_narration/
    # celebrate_discovery/etc. calls over a couple of hours — sized to
    # sit well above that while still catching a scripted abuse pattern
    # or a jailbroken model stuck calling tools in a loop across turns.
    AuditEvent.TOOL_INVOKED: (40, 600),
    # A single trip of stream_tutor_response's own per-turn tool-call cap
    # (see _MAX_TOOL_CALLS_PER_TURN) is already anomalous by construction —
    # one legitimate turn has never needed this many tool calls — so it
    # alerts immediately, same as ExfiltrationGuard's suspicious_request.
    AuditEvent.TOOL_CALL_SUPPRESSED: (1, 1),
}
_ANOMALY_ALERT_COOLDOWN_SECONDS = 1800  # don't re-alert the same (ip, event) pattern for 30 min

_anomaly_windows: dict[tuple[str, str], list[float]] = {}
_anomaly_last_alert: dict[tuple[str, str], float] = {}


def _check_anomaly(event: str, ip: str) -> Optional[int]:
    """Returns the occurrence count if `event` from `ip` just crossed its
    threshold (and isn't still in cooldown from a prior alert on the same
    pattern), else None. Not async / has no side effects beyond its own
    module-level dicts — safe to call synchronously from log_event()."""
    rule = _ANOMALY_RULES.get(event)
    if rule is None or ip in ("unknown", ""):
        return None
    threshold, window = rule
    key = (ip, event)
    now = time.monotonic()

    last_alert = _anomaly_last_alert.get(key)
    if last_alert is not None and now - last_alert < _ANOMALY_ALERT_COOLDOWN_SECONDS:
        return None

    timestamps = [t for t in _anomaly_windows.get(key, []) if now - t < window]
    timestamps.append(now)

    if len(timestamps) >= threshold:
        _anomaly_last_alert[key] = now
        _anomaly_windows[key] = []
        return len(timestamps)

    _anomaly_windows[key] = timestamps
    return None


async def _fire_anomaly_alert(event: str, ip: str, count: int) -> None:
    """Fire-and-forget: records the alert itself in the audit log (so the
    alert is part of the durable trail, not just implied by the events that
    triggered it) and best-effort emails the parent — same pattern as
    ai_service.py's safeguarding alert."""
    from services.email_service import security_alert_configured, send_security_alert

    await log_event(
        AuditEvent.ANOMALY_ALERT, ip=ip, success=True,
        detail=f"{event} x{count} from {ip}",
    )
    if security_alert_configured():
        await send_security_alert(event, ip, count)


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

    # Anomaly watch runs regardless of whether the write above succeeded —
    # the pattern lives in this process's in-memory window either way.
    # Fire-and-forget, same reasoning as the safeguarding alert: the request
    # this call is part of must never wait on an outbound email.
    trigger_count = _check_anomaly(event, ip)
    if trigger_count is not None:
        asyncio.create_task(_fire_anomaly_alert(event, ip, trigger_count))


def log_event_nowait(*args, **kwargs) -> None:
    """
    Fire-and-forget log_event() — for hot paths (login, voice verify) where
    the audit write's own DB round-trip must not add to user-facing
    latency. Safe specifically because log_event() already treats its own
    failures as non-fatal and never propagates them (see its docstring) —
    detaching it here only trades an infinitesimal risk of losing one
    audit line, if the process crashes in the instant between the
    response being sent and this task finishing, for removing a full DB
    round-trip from that response's critical path.
    """
    task = asyncio.create_task(log_event(*args, **kwargs))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


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
