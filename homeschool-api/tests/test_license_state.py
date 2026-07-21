"""
core/license_state.py — the effective-license resolution that replaced the
old refuse-to-boot Settings validator, plus the LicenseGateMiddleware's
allowlist behavior. Signed against a throwaway keypair, same technique as
test_config.py's license fixtures.
"""
import base64
import json
import uuid
from datetime import date, timedelta

import pytest
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from core import license_state, licensing
from core.middleware import LicenseGateMiddleware


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign(key, *, licensee="Fam", tier="core", seats=10, expires=None):
    payload = {
        "id": str(uuid.uuid4()), "licensee": licensee, "tier": tier,
        "seats": seats, "issued": date.today().isoformat(),
        "expires": expires.isoformat() if expires else None,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = eddsa.new(key, "rfc8032").sign(payload_bytes)
    return f"{_b64url(payload_bytes)}.{_b64url(signature)}"


@pytest.fixture()
def keypair(monkeypatch):
    key = ECC.generate(curve="ed25519")
    monkeypatch.setattr(licensing, "PUBLIC_KEY_PEM", key.public_key().export_key(format="PEM"))
    licensing._cached_verify.cache_clear()
    yield key
    licensing._cached_verify.cache_clear()


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    # Leave the module ungated for whatever test runs next.
    license_state.refresh("", None, required=False)


def test_dev_mode_never_gated():
    state = license_state.refresh("", None, required=False)
    assert state.ok and not license_state.is_gated()
    assert license_state.effective_info() is None


def test_env_license_used_when_no_db_license(keypair):
    env_key = _sign(keypair, licensee="Env Family")
    state = license_state.refresh(env_key, None, required=True)
    assert state.ok and state.source == "env"
    assert license_state.effective_info().licensee == "Env Family"


def test_db_license_wins_over_env(keypair):
    env_key = _sign(keypair, licensee="Env Family", seats=5)
    db_key = _sign(keypair, licensee="Renewed Family", seats=15)
    state = license_state.refresh(env_key, db_key, required=True)
    assert state.ok and state.source == "db"
    assert license_state.effective_info().seats == 15


def test_expired_db_license_falls_back_to_valid_env(keypair):
    env_key = _sign(keypair, licensee="Env Family")
    stale_db = _sign(keypair, licensee="Old Renewal", expires=date.today() - timedelta(days=1))
    state = license_state.refresh(env_key, stale_db, required=True)
    assert state.ok and state.source == "env"


def test_all_expired_gates_with_expiry_message(keypair):
    expired = _sign(keypair, tier="trial", expires=date.today() - timedelta(days=3))
    state = license_state.refresh(expired, None, required=True)
    assert not state.ok and license_state.is_gated()
    assert "expired" in state.problem
    # An expired license grants nothing — no seats, no enforcement identity.
    assert license_state.effective_info() is None


def test_renewal_lifts_gate_live(keypair):
    expired = _sign(keypair, expires=date.today() - timedelta(days=1))
    license_state.refresh(expired, None, required=True)
    assert license_state.is_gated()
    renewed = _sign(keypair, licensee="Renewed", expires=date.today() + timedelta(days=365))
    state = license_state.refresh(expired, renewed, required=True)
    assert state.ok and not license_state.is_gated()
    assert state.source == "db"


def test_gate_allowlist_paths():
    """The middleware's allowlist must cover exactly the fix-it-in-app
    surface: health, login (+MFA second factor), and the license endpoints."""
    allowed = ("/health", "/auth/login", "/auth/validate", "/mfa/verify", "/admin/license")
    blocked = ("/tutor/chat", "/pod/configs", "/admin/status", "/voice/transcribe", "/narration/emma/profile")
    prefixes = LicenseGateMiddleware._ALLOWED_PREFIXES
    for path in allowed:
        assert path == "/health" or any(path.startswith(p) for p in prefixes), path
    for path in blocked:
        assert not any(path.startswith(p) for p in prefixes), path


# ── Integration: the gate middleware + the in-app apply endpoint ────────────

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _gated_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(LicenseGateMiddleware)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/auth/login")
    def login():
        return {"ok": True}

    @app.get("/admin/license")
    def license_route():
        return {"ok": True}

    @app.get("/tutor/chat")
    def tutoring():
        return {"ok": True}

    return app


def test_gate_blocks_tutoring_but_not_the_fix_it_surface(keypair):
    expired = _sign(keypair, expires=date.today() - timedelta(days=1))
    license_state.refresh(expired, None, required=True)
    client = TestClient(_gated_app())
    assert client.get("/health").status_code == 200
    assert client.post("/auth/login").status_code == 200
    assert client.get("/admin/license").status_code == 200
    blocked = client.get("/tutor/chat")
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "license_required"
    assert "expired" in blocked.json()["detail"]
    # A renewal (as POST /admin/license would apply it) lifts the gate LIVE.
    renewed = _sign(keypair, expires=date.today() + timedelta(days=365))
    license_state.refresh(expired, renewed, required=True)
    assert client.get("/tutor/chat").status_code == 200


@pytest.mark.asyncio
async def test_apply_license_endpoint_persists_and_lifts_gate(keypair, demo_db, monkeypatch):
    """Drives the REAL apply_license handler against a real (SQLite) DB:
    invalid key rejected, expired key rejected, valid key stored + gate
    lifted, and a re-apply overwrites the stored row."""
    from fastapi import HTTPException
    from core.config import settings
    from routers.admin import ApplyLicenseRequest, apply_license
    from unittest.mock import MagicMock

    monkeypatch.setattr(settings, "production", "true")
    monkeypatch.setattr(settings, "license_key", "")
    license_state.refresh("", None, required=True)
    assert license_state.is_gated()

    request = MagicMock()
    request.client.host = "127.0.0.1"
    request.headers = {}

    async with demo_db() as db:
        with pytest.raises(HTTPException) as exc_info:
            await apply_license(ApplyLicenseRequest(license_key="garbage"), request, db=db, _={})
        assert exc_info.value.status_code == 422

        expired = _sign(keypair, expires=date.today() - timedelta(days=1))
        with pytest.raises(HTTPException) as exc_info:
            await apply_license(ApplyLicenseRequest(license_key=expired), request, db=db, _={})
        assert "expired" in exc_info.value.detail
        assert license_state.is_gated()  # nothing bad was stored

        good = _sign(keypair, licensee="Renewed Family", seats=12)
        result = await apply_license(ApplyLicenseRequest(license_key=good), request, db=db, _={})
        assert result["gated"] is False
        assert result["license"]["licensee"] == "Renewed Family"
        assert not license_state.is_gated()
        assert license_state.effective_info().seats == 12

        # Upgrade re-apply overwrites the single stored row.
        bigger = _sign(keypair, licensee="Renewed Family", seats=30)
        await apply_license(ApplyLicenseRequest(license_key=bigger), request, db=db, _={})
        assert license_state.effective_info().seats == 30

        from core.database import LicenseConfig
        row = await db.get(LicenseConfig, "license")
        assert row is not None and row.license_text == bigger
