"""
Sends Bede's post-session diagnostic notes to a parent-provided email via
Resend (https://resend.com).

The email address is used for exactly one outbound send and is never
written anywhere — not the database, not the audit log (see
routers/tutor.py's /email-summary, which logs success/failure only, never
the recipient). Gracefully returns False when unconfigured or the request
fails; callers never raise on this — a failed email is disappointing, not a
reason to break the session.
"""
import html
import logging
import re

import httpx

from core.config import DEFAULT_RESEND_FROM_ADDRESS, settings

log = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"


def _summary_to_html_paragraphs(summary_text: str) -> str:
    """Converts generate_session_summary()'s lightly-markdown'd plain text
    (paragraphs, blank-line-separated, **bold** section headers) into safe
    HTML — escapes everything first, then re-adds only the **bold** markup
    the model itself produces, so nothing else the model wrote can smuggle
    real HTML into the email."""
    paragraphs = [p.strip() for p in summary_text.strip().split("\n\n") if p.strip()]
    html_paragraphs = []
    for p in paragraphs:
        escaped = html.escape(p)
        bolded = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        html_paragraphs.append(f"<p style=\"margin: 0 0 16px 0;\">{bolded}</p>")
    return "\n".join(html_paragraphs)


def build_summary_email_html(student_name: str, summary_text: str) -> str:
    """
    Wraps Bede's session summary in a plain, honest email template — the
    disclaimer is not boilerplate, it's the whole point: this is Bede's
    informal impression from one conversation, not a validated diagnostic,
    and it must never read as more authoritative than that.
    """
    safe_name = html.escape(student_name)
    body = _summary_to_html_paragraphs(summary_text)
    return f"""\
<!DOCTYPE html>
<html>
<body style="font-family: Georgia, 'Times New Roman', serif; color: #2d3142; max-width: 560px; margin: 0 auto; padding: 24px;">
  <h1 style="font-size: 20px; margin: 0 0 4px 0;">Bede's notes from {safe_name}'s session</h1>
  <p style="font-size: 13px; color: #6b7280; margin: 0 0 24px 0;">
    This is Bede's informal impression from a single conversation — not a benchmark-validated
    assessment, diagnostic test, or official evaluation. Treat it as a starting point for a
    conversation with your child, not a verdict on where they stand.
  </p>
  <div style="font-size: 15px; line-height: 1.6;">
    {body}
  </div>
  <p style="font-size: 12px; color: #9ca3af; margin-top: 32px; border-top: 1px solid #e5e7eb; padding-top: 16px;">
    You're receiving this because you asked Bede to send it, once, to this address.
    It isn't stored anywhere — not in a database, not in a log — and nothing here was ever
    shown to {safe_name}.
  </p>
</body>
</html>"""


def build_distress_alert_html(student_name: str, timestamp_iso: str, trigger_excerpt: str) -> str:
    """
    Urgent parent notification when check_safeguarding() (ai_service.py)
    matches a crisis signal in the child's message. Includes a short excerpt
    of the triggering text — deliberately, since a parent deciding how
    urgently to respond needs to know what was actually said, not just that
    "something" happened; the audit log already keeps the same excerpt
    (core/audit.py), so this isn't a new exposure, just the same signal
    delivered somewhere a parent will actually see it in the moment.
    """
    safe_name = html.escape(student_name)
    safe_excerpt = html.escape(trigger_excerpt)
    safe_ts = html.escape(timestamp_iso)
    return f"""\
<!DOCTYPE html>
<html>
<body style="font-family: Georgia, 'Times New Roman', serif; color: #2d3142; max-width: 560px; margin: 0 auto; padding: 24px;">
  <h1 style="font-size: 20px; margin: 0 0 4px 0; color: #b91c1c;">Bede paused {safe_name}'s session</h1>
  <p style="font-size: 13px; color: #6b7280; margin: 0 0 24px 0;">
    Something {safe_name} said matched a safety pattern (distress, danger, or a request for help),
    so Bede stopped tutoring immediately and told them to find a trusted adult right now.
    Please check in with {safe_name} as soon as you can.
  </p>
  <div style="font-size: 15px; line-height: 1.6; background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 16px;">
    <p style="margin: 0 0 8px 0; font-weight: bold;">What {safe_name} said:</p>
    <p style="margin: 0; font-style: italic;">&ldquo;{safe_excerpt}&rdquo;</p>
  </div>
  <p style="font-size: 12px; color: #9ca3af; margin-top: 24px;">Detected at {safe_ts}.</p>
  <p style="font-size: 12px; color: #9ca3af; margin-top: 8px; border-top: 1px solid #e5e7eb; padding-top: 16px;">
    This is an automated pattern match, not a professional assessment — it can be triggered by things
    that turn out to be harmless. Treat it as a prompt to check in, not a diagnosis.
  </p>
</body>
</html>"""


_CATEGORY_LABELS = {
    "cx": "Customer experience",
    "ux": "Usability / interface",
    "content_quality": "Content quality (Bede's teaching)",
    "plans": "🎯 Interested in plans",
    "other": "Other",
    "beta_close": "💬 End-of-demo suggestion",
}


def _feedback_prefix(category: str) -> str:
    """"plans" is a demo lead, not product feedback — reads oddly under a
    "beta feedback" heading, so it gets its own prefix even though it
    shares every other part of this pipeline (same inbox, same template,
    same one-outbound-email contract) with routers/feedback.py's original
    cx/ux/content_quality/other categories."""
    return "Bede demo lead" if category == "plans" else "Bede beta feedback"


def build_feedback_email_html(
    category: str,
    message: str,
    role: str,
    rating: "int | None" = None,
    contact_email: "str | None" = None,
) -> str:
    """Wraps a beta feedback submission (see routers/feedback.py) in a plain
    HTML email to the operator. Escapes the free-text message — the only
    field a submitter fully controls — before embedding it."""
    safe_message = html.escape(message).replace("\n", "<br>")
    label = _CATEGORY_LABELS.get(category, category)
    stars = f"{'★' * rating}{'☆' * (5 - rating)}" if rating else "—"
    reply_line = (
        f'<p style="margin: 0 0 16px 0;"><strong>Reply-to:</strong> {html.escape(contact_email)}</p>'
        if contact_email else ""
    )
    return f"""\
<!DOCTYPE html>
<html>
<body style="font-family: Georgia, 'Times New Roman', serif; color: #2d3142; max-width: 560px; margin: 0 auto; padding: 24px;">
  <h1 style="font-size: 20px; margin: 0 0 16px 0;">{_feedback_prefix(category)} — {html.escape(label)}</h1>
  <p style="margin: 0 0 8px 0;"><strong>From:</strong> {html.escape(role)}</p>
  <p style="margin: 0 0 16px 0;"><strong>Rating:</strong> {stars}</p>
  {reply_line}
  <div style="font-size: 15px; line-height: 1.6; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px;">
    {safe_message}
  </div>
</body>
</html>"""


def feedback_configured() -> bool:
    return email_configured() and bool(settings.feedback_email)


async def send_feedback(
    category: str,
    message: str,
    role: str,
    rating: "int | None" = None,
    contact_email: "str | None" = None,
) -> bool:
    if not feedback_configured():
        return False
    html_body = build_feedback_email_html(category, message, role, rating, contact_email)
    label = _CATEGORY_LABELS.get(category, category)
    return await send_email(
        settings.feedback_email,
        subject=f"{_feedback_prefix(category)}: {label}",
        html_body=html_body,
    )


def email_configured() -> bool:
    """False whenever RESEND_API_KEY is unset OR RESEND_FROM_ADDRESS is
    still on its example.com placeholder — the latter looks configured
    (non-empty) but can never actually deliver mail, since example.com can
    never be a verified sending domain in a real Resend account. Treating
    it as unconfigured here means every caller (send_email, the diagnostic
    email button, the distress alert) fails fast and consistently instead
    of silently trying and failing per-send."""
    return bool(
        settings.resend_api_key
        and settings.resend_from_address
        and settings.resend_from_address != DEFAULT_RESEND_FROM_ADDRESS
    )


async def send_email(to_address: str, subject: str, html_body: str) -> bool:
    """Returns True if Resend accepted the send request. Never logs
    to_address — only the caller decides what's safe to log, and even then
    should never include the address itself."""
    if not email_configured():
        return False

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _RESEND_URL,
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": settings.resend_from_address,
                    "to": [to_address],
                    "subject": subject,
                    "html": html_body,
                },
            )
            resp.raise_for_status()
            return True
    except httpx.HTTPError:
        log.warning("Resend send failed (recipient omitted from this log by design)")
        return False


def distress_alert_configured() -> bool:
    return email_configured() and bool(settings.parent_email)


async def send_distress_alert(student_name: str, timestamp_iso: str, trigger_excerpt: str) -> bool:
    """
    Best-effort urgent notification to the configured PARENT_EMAIL when
    check_safeguarding() (ai_service.py) fires. Returns False silently (never
    raises) when PARENT_EMAIL/Resend aren't configured — the safeguarding
    event is always recorded in the encrypted audit log regardless, this is
    just the active, real-time notification on top of that passive record.
    """
    if not distress_alert_configured():
        return False
    html_body = build_distress_alert_html(student_name, timestamp_iso, trigger_excerpt)
    return await send_email(
        settings.parent_email,
        subject=f"Bede paused {student_name}'s session — please check in",
        html_body=html_body,
    )
