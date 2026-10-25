"""Privacy-safe security notifications for blocked learner-data access.

No learner content, credentials, request bodies, or raw IP addresses in mail.
The default recipient is the Bede security mailbox; operators can override it.
"""
import hashlib
import hmac
import logging
import os
import secrets
import time

log = logging.getLogger(__name__)
# A plain SHA-256 hash of an IPv4 address is reversible by enumeration.
# Use a private per-process HMAC key so alert fingerprints remain stable for
# in-process deduplication but cannot be recovered from mail/logs by guessing
# addresses. Rotation on restart is intentional: no persistent tracking ID.
_FINGERPRINT_KEY = secrets.token_bytes(32)
_last_alert: dict[str, float] = {}


async def _send_alert_email(recipient: str, subject: str, html_body: str) -> bool:
    """Keep optional email transport imports outside the lightweight security gate."""
    from services.email_service import send_email
    return await send_email(recipient, subject=subject, html_body=html_body)


async def alert_blocked_access(reason: str, source_ip: str) -> bool:
    recipient = os.environ.get("BEDE_SECURITY_ALERT_EMAIL", "bede@agnusdei.ai").strip()
    if not recipient:
        return False
    fingerprint = hmac.new(_FINGERPRINT_KEY, source_ip.encode("utf-8"), hashlib.sha256).hexdigest()[:12]
    key = f"{reason}:{fingerprint}"
    now = time.monotonic()
    if now - _last_alert.get(key, float("-inf")) < 300:
        return False
    log.warning("security.access_blocked rule=%s source_fingerprint=%s", reason, fingerprint)
    try:
        delivered = await _send_alert_email(
            recipient,
            subject="Bede blocked a learner-data access attempt",
            html_body=(
                "<p>Bede denied a prohibited data-access request.</p>"
                f"<p>Rule: {reason}<br>Source fingerprint: {fingerprint}</p>"
                "<p>No learner records or request content were included.</p>"
            ),
        )
        if delivered:
            _last_alert[key] = now
        return delivered
    except Exception:
        log.exception("Unable to deliver blocked-access alert")
        return False
