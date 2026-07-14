"""
Regression tests for services/email_service.py — the post-session
diagnostic email. The two things that must never regress: the disclaimer
copy (this is explicitly NOT framed as an official evaluation) and that a
malicious summary (however unlikely from the model itself) can't smuggle
real HTML into the outgoing email.
"""
import asyncio

from services.email_service import (
    _feedback_prefix,
    build_distress_alert_html,
    build_feedback_email_html,
    build_summary_email_html,
    distress_alert_configured,
    email_configured,
    feedback_configured,
    send_distress_alert,
    send_email,
    send_feedback,
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


def test_email_configured_false_when_from_address_still_the_example_com_placeholder(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "resend_from_address", "Bede <bede@example.com>")
    assert email_configured() is False


def test_email_configured_true_with_a_real_from_address(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "resend_from_address", "Bede <bede@realdomain.org>")
    assert email_configured() is True


def test_send_email_returns_false_when_from_address_still_the_placeholder(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "resend_from_address", "Bede <bede@example.com>")
    result = asyncio.run(send_email("parent@example.com", "subject", "<p>body</p>"))
    assert result is False


def test_send_email_returns_false_when_unconfigured(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "resend_api_key", "")
    result = asyncio.run(send_email("parent@example.com", "subject", "<p>body</p>"))
    assert result is False


def test_distress_alert_html_includes_student_and_excerpt():
    html = build_distress_alert_html("Emma", "2026-07-10T12:00:00+00:00", "I want to hurt myself")
    assert "Emma" in html
    assert "I want to hurt myself" in html
    assert "2026-07-10T12:00:00+00:00" in html
    assert "not a professional assessment" in html


def test_distress_alert_html_escapes_malicious_excerpt():
    """The excerpt is child-authored text — must never be trusted as HTML."""
    html = build_distress_alert_html("Emma", "2026-07-10T12:00:00+00:00", "<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_distress_alert_configured_requires_both_resend_and_parent_email(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "resend_from_address", "Bede <bede@realdomain.org>")
    monkeypatch.setattr(settings, "parent_email", "")
    assert distress_alert_configured() is False

    monkeypatch.setattr(settings, "parent_email", "parent@example.com")
    assert distress_alert_configured() is True


def test_send_distress_alert_returns_false_when_parent_email_unset(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "parent_email", "")
    result = asyncio.run(send_distress_alert("Emma", "2026-07-10T12:00:00+00:00", "trigger text"))
    assert result is False


def test_feedback_html_includes_category_role_and_rating():
    html = build_feedback_email_html("ux", "The subject sidebar is hard to reach", "demo_code", rating=4)
    assert "The subject sidebar is hard to reach" in html
    assert "demo_code" in html
    assert "★★★★☆" in html


def test_feedback_html_omits_reply_to_when_no_contact_email():
    html = build_feedback_email_html("cx", "Loved it", "parent")
    assert "Reply-to" not in html


def test_feedback_html_includes_reply_to_when_contact_email_given():
    html = build_feedback_email_html("cx", "Loved it", "parent", contact_email="mom@example.com")
    assert "mom@example.com" in html


def test_feedback_html_escapes_malicious_message():
    html = build_feedback_email_html("other", "<script>alert(1)</script>", "child")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_plans_category_gets_a_lead_heading_not_a_feedback_heading():
    """The demo's "interested in plans" contact form reuses this exact
    pipeline (see models.schemas.FeedbackRequest's docstring) but reads
    oddly under "Bede beta feedback" — it should read as a lead, not
    product feedback."""
    html = build_feedback_email_html("plans", "Tell me about pricing", "demo_code", contact_email="mom@example.com")
    assert "Bede demo lead" in html
    assert "Bede beta feedback" not in html


def test_other_categories_still_get_the_beta_feedback_heading():
    html = build_feedback_email_html("ux", "hard to find the button", "parent")
    assert "Bede beta feedback" in html
    assert "Bede demo lead" not in html


def test_feedback_prefix_only_treats_plans_specially():
    assert _feedback_prefix("plans") == "Bede demo lead"
    for category in ("cx", "ux", "content_quality", "other", "anything-unrecognized"):
        assert _feedback_prefix(category) == "Bede beta feedback"


def test_feedback_configured_requires_both_resend_and_feedback_email(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "resend_from_address", "Bede <bede@realdomain.org>")
    monkeypatch.setattr(settings, "feedback_email", "")
    assert feedback_configured() is False

    monkeypatch.setattr(settings, "feedback_email", "operator@example.com")
    assert feedback_configured() is True


def test_send_feedback_returns_false_when_feedback_email_unset(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "feedback_email", "")
    result = asyncio.run(send_feedback("cx", "message", "parent"))
    assert result is False
