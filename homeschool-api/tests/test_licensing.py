"""
Regression tests for core/licensing.py's offline license verification —
see the module docstring there and docs/PRODUCTION_SETUP.md#licensing.

Tests generate their own throwaway Ed25519 keypair and monkeypatch
licensing.PUBLIC_KEY_PEM to it, rather than using the real embedded key —
the matching private key for the real key is intentionally kept out of
this repo (see scripts/generate_license_keypair.py), so there is no way
to mint a genuinely-signed license against it in CI, by design.
"""
import base64
import json
import uuid
from datetime import date, timedelta

import pytest
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from core import licensing


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@pytest.fixture
def test_keypair(monkeypatch):
    key = ECC.generate(curve="ed25519")
    monkeypatch.setattr(licensing, "PUBLIC_KEY_PEM", key.public_key().export_key(format="PEM"))
    return key


def _sign(key, tier="core", licensee="Test Family", seats=10, issued=None, expires=None):
    payload = {
        "id": str(uuid.uuid4()),
        "licensee": licensee,
        "tier": tier,
        "seats": seats,
        "issued": (issued or date.today()).isoformat(),
        "expires": expires.isoformat() if expires else None,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = eddsa.new(key, "rfc8032").sign(payload_bytes)
    return f"{_b64url(payload_bytes)}.{_b64url(signature)}"


def test_valid_perpetual_license_verifies(test_keypair):
    lic = _sign(test_keypair, tier="core", licensee="The Smith Family", seats=10)
    info = licensing.verify_license(lic)
    assert info.tier == "core"
    assert info.licensee == "The Smith Family"
    assert info.seats == 10
    assert info.expires is None
    assert info.is_expired is False
    assert info.days_remaining is None


def test_valid_trial_license_not_yet_expired(test_keypair):
    lic = _sign(test_keypair, tier="trial", seats=10, expires=date.today() + timedelta(days=21))
    info = licensing.verify_license(lic)
    assert info.tier == "trial"
    assert info.is_expired is False
    assert info.days_remaining in (20, 21)  # allow for day-boundary flakiness


def test_expired_trial_license_parses_but_reports_expired(test_keypair):
    lic = _sign(test_keypair, tier="trial", seats=10, expires=date.today() - timedelta(days=1))
    info = licensing.verify_license(lic)
    assert info.is_expired is True
    assert info.days_remaining < 0


def test_tampered_payload_is_rejected(test_keypair):
    lic = _sign(test_keypair, tier="core", seats=10)
    payload_part, sig_part = lic.split(".")
    # Flip the seat count without re-signing — must fail cryptographically.
    tampered_payload = json.dumps(
        {**json.loads(licensing._b64url_decode(payload_part)), "seats": 999},
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    tampered = f"{_b64url(tampered_payload)}.{sig_part}"
    with pytest.raises(licensing.InvalidLicenseError, match="signature verification failed"):
        licensing.verify_license(tampered)


def test_signature_from_a_different_keypair_is_rejected(monkeypatch):
    forger_key = ECC.generate(curve="ed25519")
    real_key = ECC.generate(curve="ed25519")
    monkeypatch.setattr(licensing, "PUBLIC_KEY_PEM", real_key.public_key().export_key(format="PEM"))
    forged = _sign(forger_key, tier="coop", seats=999)
    with pytest.raises(licensing.InvalidLicenseError, match="signature verification failed"):
        licensing.verify_license(forged)


def test_malformed_string_rejected(test_keypair):
    with pytest.raises(licensing.InvalidLicenseError, match="malformed license string"):
        licensing.verify_license("not-a-license-at-all")


def test_garbage_base64_rejected(test_keypair):
    # base64's decoder silently discards non-alphabet characters rather than
    # raising, so this actually fails at signature verification rather than
    # decoding — either way it must not be accepted as a genuine license.
    with pytest.raises(licensing.InvalidLicenseError):
        licensing.verify_license("!!!not-valid-base64!!!.also-not-valid")


def test_unknown_tier_rejected(test_keypair):
    payload = {
        "id": str(uuid.uuid4()), "licensee": "X", "tier": "enterprise-deluxe",
        "seats": 10, "issued": date.today().isoformat(), "expires": None,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = eddsa.new(test_keypair, "rfc8032").sign(payload_bytes)
    lic = f"{_b64url(payload_bytes)}.{_b64url(signature)}"
    with pytest.raises(licensing.InvalidLicenseError, match="unknown license tier"):
        licensing.verify_license(lic)


def test_missing_required_field_rejected(test_keypair):
    payload = {"id": str(uuid.uuid4()), "tier": "core", "seats": 10}  # no licensee/issued
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = eddsa.new(test_keypair, "rfc8032").sign(payload_bytes)
    lic = f"{_b64url(payload_bytes)}.{_b64url(signature)}"
    with pytest.raises(licensing.InvalidLicenseError, match="malformed license payload"):
        licensing.verify_license(lic)


def test_get_license_returns_none_for_empty_key():
    assert licensing.get_license("") is None


def test_get_license_raises_for_invalid_key(test_keypair):
    with pytest.raises(licensing.InvalidLicenseError):
        licensing.get_license("garbage.garbage")
