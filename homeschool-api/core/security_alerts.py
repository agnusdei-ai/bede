"""Privacy-safe security notifications for blocked learner-data access.

No learner content, credentials, request bodies, or raw IP addresses in mail.
The default recipient is the Bede security mailbox; operators can override it.
"""
import hashlib
import logging
import os
import time

log = logging.getLogger(__name__)
_last_alert: dict[str, float] = {}


async def alert_blocked_access(reason: str, source_ip: str) -> bool:
    recipient = os.environ.get("BEDE_SECURITY_ALERT_EMAIL", "bede@agnusdei.ai").strip()
    if not recipient:
        return False
    fingerprint = hashlib.sha256(source_ip.encode("utf-8")).hexdigest()[:12]
    key = f"{reason}:{fingerprint}"
    now = time.monotonic()
    if now - _last_alert.get(key, float("-inf")) < 300:
        return False
    _last_alert[key] = now
    log.warning("security.access_blocked rule=%s source_fingerprint=%s", reason, fingerprint)
    try:
        from services.email_service import send_email
        return await send_email(
            recipient,
            subject="Bede blocked a learner-data access attempt",
            html_body=(
                "<p>Bede denied a prohibited data-access request.</p>"
                f"<p>Rule: {reason}<br>Source fingerprint: {fingerprint}</p>"
                "<p>No learner records or request content were included.</p>"
            ),
        )
    except Exception:
        log.exception("Unable to deliver blocked-access alert")
        return False
