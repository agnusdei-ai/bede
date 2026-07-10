"""
Regression tests for services/email_service.py — the post-session
diagnostic email. The two things that must never regress: the disclaimer
copy (this is explicitly NOT framed as an official evaluation) and that a
malicious summary (however unlikely from the model itself) can't smuggle
real HTML into the outgoing email.
"""
import asyncio

from services.email_service import (
    build_summary_email_html,
    email_configured,
    send_email,
)


def test_html_includes_disclaimer_and_bold_conversion():
    html = build_summary_email_html(
        "Emma",
        "**Session Highlights**\n\nEmma worked through fractions with real curiosity.",
    )
    assert "<strong>Session Highlights</strong>" in html
    assert "not a benchmark-validated" in html
    assert "Emma" in html


def test_html_escapes_malicious_summary_content():
    """A summary text containing a script tag must never execute — this
    would only ever come from the model's own output, but the email
    template must not trust it either way."""
    html = build_summary_email_html("Emma", "<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_email_configured_false_when_no_api_key(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "resend_api_key", "")
    assert email_configured() is False


def test_send_email_returns_false_when_unconfigured(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "resend_api_key", "")
    result = asyncio.run(send_email("parent@example.com", "subject", "<p>body</p>"))
    assert result is False
