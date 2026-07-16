"""
Regression tests for the per-login locale toggle: GET /auth/locales (the
public, pre-auth endpoint Login.tsx calls to decide whether to render the
English/Español toggle at all) and POST /auth/login embedding the chosen
locale as a JWT claim — see routers/auth.py's login() and core/config.py's
updated comment on `locale` (which single non-English locale a deployment
OFFERS as a login-time choice, not which language every session runs in).
"""
import pytest
import pytest_asyncio
from starlette.requests import Request

from core.config import settings
from core.security import decode_token
from models.schemas import LoginRequest
from routers.auth import available_locales, login

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


@pytest_asyncio.fixture
async def db_session(demo_db):
    async with demo_db() as session:
        yield session


def _fake_request() -> Request:
    scope = {
        "type": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [(b"user-agent", b"pytest")],
    }
    return Request(scope)


# ── GET /auth/locales ────────────────────────────────────────────────────────

async def test_available_locales_is_empty_when_deployment_is_english_only(monkeypatch):
    monkeypatch.setattr(settings, "locale", "en")
    assert await available_locales() == {"locales": []}


async def test_available_locales_lists_the_offered_locale(monkeypatch):
    monkeypatch.setattr(settings, "locale", "es")
    result = await available_locales()
    assert result == {"locales": [{"code": "es", "name": "Spanish (Español)"}]}


# ── POST /auth/login embeds the chosen locale ───────────────────────────────

async def test_login_embeds_the_chosen_locale_in_the_token(db_session, monkeypatch):
    monkeypatch.setattr(settings, "locale", "es")
    monkeypatch.setattr(settings, "child_pin", "602656")

    resp = await login(
        LoginRequest(role="child", credential="602656", locale="es"),
        _fake_request(),
        db=db_session,
    )
    payload = decode_token(resp.access_token)
    assert payload["locale"] == "es"


async def test_login_defaults_to_english_when_no_locale_is_offered(db_session, monkeypatch):
    monkeypatch.setattr(settings, "locale", "en")
    monkeypatch.setattr(settings, "child_pin", "602656")

    resp = await login(
        LoginRequest(role="child", credential="602656"),
        _fake_request(),
        db=db_session,
    )
    payload = decode_token(resp.access_token)
    assert payload["locale"] == "en"


async def test_login_ignores_a_locale_the_deployment_never_offered(db_session, monkeypatch):
    """A stale or tampered client value must not smuggle in a locale this
    deployment never enabled — silently falls back to "en" rather than
    rejecting the login outright (a bad locale value should never be able to
    block someone from getting into their own session)."""
    monkeypatch.setattr(settings, "locale", "en")
    monkeypatch.setattr(settings, "child_pin", "602656")

    resp = await login(
        LoginRequest(role="child", credential="602656", locale="es"),
        _fake_request(),
        db=db_session,
    )
    payload = decode_token(resp.access_token)
    assert payload["locale"] == "en"


async def test_login_ignores_an_unrecognized_locale_code(db_session, monkeypatch):
    monkeypatch.setattr(settings, "locale", "es")
    monkeypatch.setattr(settings, "child_pin", "602656")

    resp = await login(
        LoginRequest(role="child", credential="602656", locale="fr"),
        _fake_request(),
        db=db_session,
    )
    payload = decode_token(resp.access_token)
    assert payload["locale"] == "en"


async def test_parent_login_without_mfa_embeds_locale(db_session, monkeypatch):
    monkeypatch.setattr(settings, "locale", "es")
    monkeypatch.setattr(settings, "parent_password", "correct horse battery staple")

    resp = await login(
        LoginRequest(role="parent", credential="correct horse battery staple", locale="es"),
        _fake_request(),
        db=db_session,
    )
    payload = decode_token(resp.access_token)
    assert payload["role"] == "parent"
    assert payload["locale"] == "es"
