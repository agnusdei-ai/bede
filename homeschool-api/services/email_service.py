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

from core.config import settings

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


def email_configured() -> bool:
    return bool(settings.resend_api_key and settings.resend_from_address)


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
