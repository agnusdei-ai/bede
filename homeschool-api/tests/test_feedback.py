"""
Regression tests for routers/feedback.py — beta CX/UX/content-quality
feedback routed to the operator's own inbox (FEEDBACK_EMAIL), open to any
authenticated role including the scoped public demo visitor.
"""
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from core.config import settings
from models.schemas import FeedbackRequest
from routers.feedback import feedback_enabled, submit_feedback


def _fake_request() -> Request:
    scope = {
        "type": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [(b"user-agent", b"pytest")],
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_submit_feedback_404s_when_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "feedback_email", "")
    with pytest.raises(HTTPException) as exc_info:
        await submit_feedback(
            FeedbackRequest(category="ux", message="hard to find the button"),
            _fake_request(),
            auth={"role": "parent"},
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_submit_feedback_sends_and_returns_success(monkeypatch):
    monkeypatch.setattr(settings, "feedback_email", "operator@example.com")

    sent_calls = []

    async def fake_send_feedback(**kwargs):
        sent_calls.append(kwargs)
        return True

    monkeypatch.setattr("routers.feedback.send_feedback", fake_send_feedback)

    result = await submit_feedback(
        FeedbackRequest(category="content_quality", message="Bede explained fractions well", rating=5),
        _fake_request(),
        auth={"role": "demo_code", "code": "123456"},
    )
    assert result == {"sent": True}
    assert sent_calls[0]["category"] == "content_quality"
    assert sent_calls[0]["role"] == "demo_code"
    assert sent_calls[0]["rating"] == 5


@pytest.mark.asyncio
async def test_submit_feedback_502s_when_send_fails(monkeypatch):
    monkeypatch.setattr(settings, "feedback_email", "operator@example.com")

    async def fake_send_feedback(**kwargs):
        return False

    monkeypatch.setattr("routers.feedback.send_feedback", fake_send_feedback)

    with pytest.raises(HTTPException) as exc_info:
        await submit_feedback(
            FeedbackRequest(category="other", message="test"),
            _fake_request(),
            auth={"role": "child"},
        )
    assert exc_info.value.status_code == 502


@pytest.mark.asyncio
async def test_plans_category_reuses_the_exact_same_pipeline(monkeypatch):
    """The demo's "interested in plans" contact form (surfaced from the
    diagnostic preview's quota-exceeded state) is just this category value
    — no separate endpoint, no separate config, same FEEDBACK_EMAIL."""
    monkeypatch.setattr(settings, "feedback_email", "operator@example.com")

    sent_calls = []

    async def fake_send_feedback(**kwargs):
        sent_calls.append(kwargs)
        return True

    monkeypatch.setattr("routers.feedback.send_feedback", fake_send_feedback)

    result = await submit_feedback(
        FeedbackRequest(category="plans", message="Would love to hear about pricing", contact_email="parent@example.com"),
        _fake_request(),
        auth={"role": "demo_code", "code": "123456"},
    )
    assert result == {"sent": True}
    assert sent_calls[0]["category"] == "plans"
    assert sent_calls[0]["contact_email"] == "parent@example.com"


@pytest.mark.asyncio
async def test_beta_close_category_reuses_the_exact_same_pipeline(monkeypatch):
    """The demo's end-of-session "help us improve" prompt (DemoSummaryScreen)
    is also just this category value — same pipeline, contact_email still
    fully optional since the field itself is only shown after a client-side
    parent/guardian affirmation, not enforced here."""
    monkeypatch.setattr(settings, "feedback_email", "operator@example.com")

    sent_calls = []

    async def fake_send_feedback(**kwargs):
        sent_calls.append(kwargs)
        return True

    monkeypatch.setattr("routers.feedback.send_feedback", fake_send_feedback)

    result = await submit_feedback(
        FeedbackRequest(category="beta_close", message="More subjects would be great!", contact_email="parent@example.com"),
        _fake_request(),
        auth={"role": "demo_code", "code": "123456"},
    )
    assert result == {"sent": True}
    assert sent_calls[0]["category"] == "beta_close"
    assert sent_calls[0]["contact_email"] == "parent@example.com"


def test_beta_close_category_works_without_contact_email():
    """contact_email is optional — a visitor can leave improvement feedback
    without opting into follow-up contact at all."""
    req = FeedbackRequest(category="beta_close", message="Love the Socratic style!")
    assert req.contact_email is None


@pytest.mark.asyncio
async def test_onboarding_category_reuses_the_exact_same_pipeline(monkeypatch):
    """A real beta family's one-time "what are you hoping Bede helps with"
    intake prompt (BetaIntakeModal, shown once right after first pod setup)
    is also just this category value — same pipeline, no contact_email
    needed since the parent is already authenticated."""
    monkeypatch.setattr(settings, "feedback_email", "operator@example.com")

    sent_calls = []

    async def fake_send_feedback(**kwargs):
        sent_calls.append(kwargs)
        return True

    monkeypatch.setattr("routers.feedback.send_feedback", fake_send_feedback)

    result = await submit_feedback(
        FeedbackRequest(category="onboarding", message="Hoping for more confident narration"),
        _fake_request(),
        auth={"role": "parent"},
    )
    assert result == {"sent": True}
    assert sent_calls[0]["category"] == "onboarding"


@pytest.mark.asyncio
async def test_feedback_enabled_reflects_configuration(monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "")
    monkeypatch.setattr(settings, "feedback_email", "")
    assert await feedback_enabled() == {"enabled": False}

    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "resend_from_address", "Bede <bede@realdomain.org>")
    monkeypatch.setattr(settings, "feedback_email", "operator@example.com")
    assert await feedback_enabled() == {"enabled": True}
