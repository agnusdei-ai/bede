"""Who is told about a possible safety concern, once, and what happened.

`routers/tutor.py` raises a safeguarding concern when a child's message
matches a crisis pattern, or when a lesson picture is flagged as possibly
showing self-harm or sexual content (services/content_screen.py). The
SAFEGUARDING audit entry is written there, first and always. This module
decides who gets the real-time email, and records what became of it.

**Routing.** A family's session goes to the household's `PARENT_EMAIL`. A
session in school mode does not: a teacher-led session (the `educator`
role), or any session on a campus-licensed deployment (`BEDE_LOCATION_ID`
set), goes to `SCHOOL_SAFEGUARDING_EMAIL`, the address the school designates
for safeguarding concerns. If the school has set none, no email is sent at
all. It never falls back to `PARENT_EMAIL`, which on a school deployment is
the operator's address and not the school's safeguarding route. The teacher
in the session still sees the reply, and the audit log still holds the
concern.

**Duplicates.** The tutor client retries a turn whose connection dropped
(services/api.ts), and a retry re-sends the same message or picture. The
same concern for the same learner within `DUPLICATE_WINDOW_SECONDS` is
emailed once. Only a SHA-256 digest is kept in memory to recognise it,
never the picture or the message.

**Delivery.** Every concern ends in one `SAFEGUARDING_ALERT` audit entry
saying where it was routed and what happened (`sent`, `duplicate`,
`no_route`, `not_configured` or `failed`), never the address. A failed send
is visible there, and it never changes what the child was shown.
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone

from core.config import settings

log = logging.getLogger(__name__)

DUPLICATE_WINDOW_SECONDS = 1800
_MAX_REMEMBERED = 2048
_recent: dict[str, float] = {}


def school_mode(role: str | None) -> bool:
    return role == "educator" or bool(settings.bede_location_id)


def route_for(role: str | None) -> tuple[str, str]:
    """(route name, recipient address or "")."""
    if school_mode(role):
        return "school", settings.school_safeguarding_email
    return "parent", settings.parent_email


def _key(student_name: str, source: str) -> str:
    return hashlib.sha256(f"{student_name}\x00{source}".encode("utf-8")).hexdigest()


def _seen_recently(key: str, now: float) -> bool:
    for stale in [k for k, expires in _recent.items() if expires <= now]:
        _recent.pop(stale, None)
    if key in _recent:
        return True
    if len(_recent) >= _MAX_REMEMBERED:
        _recent.pop(min(_recent, key=_recent.get))
    _recent[key] = now + DUPLICATE_WINDOW_SECONDS
    return False


def _forget(key: str) -> None:
    _recent.pop(key, None)


async def deliver(*, role: str | None, student_name: str, trigger_excerpt: str,
                  dedupe_source: str, picture: str | None = None, audit: dict | None = None,
                  display_name: str | None = None) -> str:
    """Email the concern to its route once, then audit the outcome.

    `dedupe_source` is what identifies the same concern on a retry (the
    picture's base64, or the message). Only its digest is remembered.
    `display_name` is how the email body addresses the learner (a preferred
    name, when an adult set one); the dedupe key and the audit entry stay on
    `student_name`, the stable handle. Returns the outcome. Never raises.
    """
    from core.audit import AuditEvent, log_event
    from services.email_service import email_configured, send_distress_alert

    route, recipient = route_for(role)
    key = _key(student_name, dedupe_source)
    if _seen_recently(key, time.monotonic()):
        outcome = "duplicate"
    elif not recipient:
        outcome = "no_route"
    elif not email_configured():
        outcome = "not_configured"
    else:
        try:
            sent = await send_distress_alert(
                display_name or student_name, datetime.now(timezone.utc).isoformat(), trigger_excerpt,
                picture=picture, to_address=recipient,
            )
        except Exception:  # an alert must never break the child's turn
            log.warning("Safeguarding alert send raised; recipient omitted from this log")
            sent = False
        outcome = "sent" if sent else "failed"
        if not sent:
            _forget(key)  # a retry of the same concern may try again
    try:
        await log_event(
            AuditEvent.SAFEGUARDING_ALERT,
            role=role, student_name=student_name, success=outcome in ("sent", "duplicate"),
            detail=f"route={route} outcome={outcome}" + (" kind=picture" if picture else " kind=message"),
            **(audit or {}),
        )
    except Exception:
        log.warning("Safeguarding alert outcome could not be audited")
    return outcome
