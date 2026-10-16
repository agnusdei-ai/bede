"""RESEND_API_BASE_URL can only ever point mail at THIS machine, and never in
production.

It exists so the synthetic qualification run (docs/SYNTHETIC_QUALIFICATION.md)
can capture the email the real /auth/educator-passkey/invite route sends, on a
loopback mail sink, and so enroll a synthetic teacher through the real
passkey ceremony instead of a minted token. The risk it carries is the
obvious one: a setting that redirects outbound mail could redirect a
family's distress alert or a teacher's enrollment link to someone else. So:

  * empty (the default) is Resend, exactly as before;
  * any non-loopback host, a non-http(s) scheme, or embedded credentials is
    refused when Settings is constructed;
  * any value at all is refused when PRODUCTION=true;
  * and send_email() really posts to the configured sink (the invocation,
    not just the helper).
"""
import httpx
import pytest

from core.config import Settings
from tests.test_config_production_hardening import _base_production_kwargs


def test_production_baseline_is_otherwise_valid():
    # So the production refusal below fails for THIS setting, not another.
    Settings(**_base_production_kwargs())


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8767", "http://localhost:8767/", "http://[::1]:8767",
])
def test_loopback_sink_is_accepted_outside_production(url):
    assert Settings(resend_api_base_url=url).resend_api_base_url == url


@pytest.mark.parametrize("url", [
    "https://api.example.com", "http://10.0.0.5:8767", "http://192.168.1.2",
    "http://127.0.0.1.example.com", "http://user:pw@127.0.0.1:8767",
    "ftp://127.0.0.1", "127.0.0.1:8767",
])
def test_non_loopback_mail_endpoint_is_refused(url):
    with pytest.raises(ValueError, match="RESEND_API_BASE_URL must be a loopback URL"):
        Settings(resend_api_base_url=url)


def test_any_mail_endpoint_is_refused_in_production():
    with pytest.raises(ValueError, match="must be empty when PRODUCTION=true"):
        Settings(**_base_production_kwargs(resend_api_base_url="http://127.0.0.1:8767"))


def test_default_is_resend(monkeypatch):
    from services import email_service
    monkeypatch.setattr(email_service.settings, "resend_api_base_url", "")
    assert email_service._resend_url() == "https://api.resend.com/emails"


def test_send_email_posts_to_the_configured_sink(monkeypatch):
    """Invocation half: the real send path reaches the configured URL."""
    from services import email_service
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"id": "synthetic"})

    monkeypatch.setattr(email_service.settings, "resend_api_base_url", "http://127.0.0.1:8767")
    monkeypatch.setattr(email_service.settings, "resend_api_key", "synthetic-sink-key")
    monkeypatch.setattr(email_service.settings, "resend_from_address", "bede@qualification.agnusdei.ai")
    monkeypatch.setattr(email_service, "_get_http_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    import asyncio
    assert asyncio.run(email_service.send_email("t@qualification.agnusdei.ai", "s", "<p>b</p>")) is True
    assert seen == ["http://127.0.0.1:8767/emails"]
