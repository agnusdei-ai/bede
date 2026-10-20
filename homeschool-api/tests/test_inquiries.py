"""Business inquiry delivery is independent of demo auth and never an open relay."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.inquiries import InquiryRequest
from routers import inquiries
from services import email_service, inquiry_service


def payload(audience="homeschool"):
    value = {
        "audience": audience, "name": "Test Owner", "email": "owner@example.org",
        "role": "Parent / guardian", "learners": 3, "grades": ["K–2", "3–5"],
        "interests": ["Plan and pricing", "Implementation"],
        "timing": "Next school term", "deployment": "Need guidance", "consent": True,
    }
    if audience != "homeschool":
        value.update(organization="Synthetic Learning Community", educators=4, sites=1)
    if audience == "coop":
        value["families"] = 12
    return value


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(inquiries.router)
    monkeypatch.setattr(inquiries, "inquiry_configured", lambda audience: True)
    return TestClient(app)


@pytest.mark.parametrize("audience", ["homeschool", "coop", "charter_school"])
def test_each_audience_can_send_without_demo_auth(client, monkeypatch, audience):
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(inquiries, "send_inquiry", send)
    response = client.post("/inquiries", json=payload(audience))
    assert response.status_code == 200
    assert response.json() == {"sent": True}
    assert send.await_args.args[0].audience == audience


@pytest.mark.parametrize("changes", [
    {"audience": "unknown"}, {"consent": False}, {"email": "not an email"},
    {"learners": 0}, {"learners": 2.5}, {"notes": "x" * 1201},
    {"grades": []}, {"interests": []}, {"grades": ["K–2", "K–2"]},
    {"to": "third-party@example.org"}, {"audience": "charter_school"},
    {"email": "owner@example.org\r\nBcc: third-party@example.org"},
])
def test_invalid_scope_or_recipient_injection_never_sends(client, monkeypatch, changes):
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(inquiries, "send_inquiry", send)
    response = client.post("/inquiries", json={**payload(), **changes})
    assert response.status_code == 422
    send.assert_not_awaited()


def test_coop_requires_participating_families(client):
    data = payload("coop")
    del data["families"]
    assert client.post("/inquiries", json=data).status_code == 422


def test_honeypot_and_delivery_failures_never_claim_success(client, monkeypatch):
    send = AsyncMock(return_value=False)
    monkeypatch.setattr(inquiries, "send_inquiry", send)
    assert client.post("/inquiries", json={**payload(), "website": "bot"}).status_code == 400
    send.assert_not_awaited()
    assert client.post("/inquiries", json=payload()).status_code == 502
    monkeypatch.setattr(inquiries, "inquiry_configured", lambda audience: False)
    assert client.post("/inquiries", json=payload()).status_code == 503
    assert send.await_count == 1


@pytest.mark.parametrize("audience,recipient", [
    ("homeschool", "bede@agnusdei.ai"),
    ("coop", "info@agnusdei.ai"),
    ("charter_school", "info@agnusdei.ai"),
])
@pytest.mark.asyncio
async def test_fixed_owner_routing_and_reply_address(monkeypatch, audience, recipient):
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(inquiry_service, "send_email", send)
    monkeypatch.setattr(inquiry_service, "email_configured", lambda: True)
    req = InquiryRequest(**payload(audience))
    assert await inquiry_service.send_inquiry(req) is True
    assert send.await_args.args[0] == recipient
    assert send.await_args.kwargs["reply_to"] == "owner@example.org"
    assert req.timing in send.await_args.kwargs["html_body"]
    assert "3" in send.await_args.kwargs["html_body"]


def test_email_escapes_every_user_supplied_value():
    req = InquiryRequest(**{**payload(), "name": "<script>unsafe()</script>", "notes": "<b>not markup</b>"})
    body = inquiry_service.build_inquiry_email(req)
    assert "<script>" not in body
    assert "&lt;script&gt;unsafe()&lt;/script&gt;" in body
    assert "&lt;b&gt;not markup&lt;/b&gt;" in body


@pytest.mark.asyncio
async def test_unconfigured_mail_provider_does_not_attempt_send(monkeypatch):
    send = AsyncMock()
    monkeypatch.setattr(inquiry_service, "send_email", send)
    monkeypatch.setattr(inquiry_service, "email_configured", lambda: False)
    assert await inquiry_service.send_inquiry(InquiryRequest(**payload())) is False
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_shared_provider_passes_validated_reply_to(monkeypatch):
    response = MagicMock()
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    monkeypatch.setattr(email_service, "email_configured", lambda: True)
    monkeypatch.setattr(email_service, "_get_http_client", lambda: client)
    assert await email_service.send_email(
        "info@agnusdei.ai", "Synthetic test", "<p>Test</p>", reply_to="owner@example.org"
    )
    data = client.post.await_args.kwargs["json"]
    assert data["to"] == ["info@agnusdei.ai"]
    assert data["reply_to"] == "owner@example.org"
