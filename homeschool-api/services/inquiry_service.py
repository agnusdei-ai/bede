"""One owner-facing email per accepted inquiry, using existing Resend configuration."""
import html

from models.inquiries import InquiryRequest
from services.email_service import email_configured, send_email

AUDIENCE_LABELS = {
    "homeschool": "Homeschool family",
    "coop": "Co-op",
    "charter_school": "Charter school",
}
INQUIRY_RECIPIENTS = {
    "homeschool": "bede@agnusdei.ai",
    "coop": "info@agnusdei.ai",
    "charter_school": "info@agnusdei.ai",
}


def inquiry_recipient(audience: str) -> str:
    # Fixed owner inboxes, independent of the legacy SALES_EMAIL setting
    # for demo leads. The visitor can never supply a recipient.
    return INQUIRY_RECIPIENTS[audience]


def inquiry_configured(audience: str) -> bool:
    return audience in INQUIRY_RECIPIENTS and email_configured()


def build_inquiry_email(req: InquiryRequest) -> str:
    rows = [
        ("Inquiry type", AUDIENCE_LABELS[req.audience]),
        ("Contact", req.name), ("Reply email", str(req.email)),
        ("Organization", req.organization or "Individual household"),
        ("Role", req.role), ("City / state", req.location or "Not provided"),
        ("Estimated learners", req.learners), ("Grade bands", ", ".join(req.grades)),
        ("Estimated families", req.families), ("Educators / staff", req.educators),
        ("Locations / campuses", req.sites), ("Requested help", ", ".join(req.interests)),
        ("Target timing", req.timing), ("Deployment preference", req.deployment),
        ("Context / procurement / technical needs", req.notes or "Not provided"),
    ]
    body = "".join(
        '<tr><th scope="row" style="text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid #dfd5bf;">'
        + html.escape(label) + '</th><td style="padding:10px;white-space:pre-wrap;border-bottom:1px solid #dfd5bf;">'
        + html.escape(str(value)) + "</td></tr>"
        for label, value in rows if value is not None
    )
    return (
        '<!doctype html><html lang="en-US"><body style="margin:0;background:#f8f4ea;color:#263746;'
        'font:16px/1.6 Georgia,serif;"><main style="max-width:680px;margin:auto;padding:28px;">'
        '<p style="color:#6e5220;letter-spacing:.08em;">BEDE BY AGNUS DEI</p>'
        '<h1>New ' + html.escape(AUDIENCE_LABELS[req.audience].lower()) + ' inquiry</h1>'
        '<p>Requested scope and next steps. Counts are estimates, not enrollment records.</p>'
        '<table style="border-collapse:collapse;width:100%;">' + body + '</table>'
        '<p>The sender agreed to email this inquiry and receive a response. No enrollment, '
        'purchase, or implementation commitment has been made.</p></main></body></html>'
    )


async def send_inquiry(req: InquiryRequest) -> bool:
    if not inquiry_configured(req.audience):
        return False
    return await send_email(
        inquiry_recipient(req.audience),
        subject=f"Bede inquiry: {AUDIENCE_LABELS[req.audience]}",
        html_body=build_inquiry_email(req),
        reply_to=str(req.email),
    )
