"""Operator-approved monthly campus location offer & signed entitlement tests.

Ephemeral test-only Ed25519 keys. No OpenAI accounts, cloud requests,
payment captures, customer identifiers or real learner data.
"""
import base64
import json
import sys
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from core import campus_pricing, license_state, licensing
from core.config import settings
from scripts import issue_license


@pytest.fixture
def signing_key(monkeypatch):
    private = ECC.generate(curve="Ed25519")
    monkeypatch.setattr(licensing, "PUBLIC_KEY_PEM", private.public_key().export_key(format="PEM"))
    return private


def sign(key, **changes):
    payload = {
        "id": str(uuid.uuid4()),
        "licensee": "Test Site License",
        "tier": "campus_location",
        "location_id": "school-campus-001",
        "learner_scope": "unlimited_at_location",
        "issued": date.today().isoformat(),
        "expires": (date.today() + timedelta(days=31)).isoformat(),
    }
    payload.update(changes)
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig = eddsa.new(key, "rfc8032").sign(blob)
    b64 = lambda v: base64.urlsafe_b64encode(v).rstrip(b"=").decode("ascii")
    return f"{b64(blob)}.{b64(sig)}"


def test_exact_pricing_and_multi_location_quotes():
    q = campus_pricing.quote_monthly
    assert q(offer=campus_pricing.CAMPUS_LOCATION, learners=1) == Decimal("3500.00")
    assert q(offer=campus_pricing.CAMPUS_LOCATION, learners=100_000) == Decimal("3500.00")
    assert q(offer=campus_pricing.CAMPUS_LOCATION, learners=100_000, locations=3) == Decimal("10500.00")
    assert q(offer=campus_pricing.PER_LEARNER, learners=140) == Decimal("3500.00")
    assert campus_pricing.CAMPUS_LOCATION_ANNUAL_USD == Decimal("42000.00")
    assert campus_pricing.CAMPUS_LOCATION.hardware_included is False
    assert campus_pricing.CAMPUS_LOCATION.ai_capacity_unlimited is False
    for learners in (-1, 0, True, 0.5):
        with pytest.raises(ValueError):
            q(offer=campus_pricing.CAMPUS_LOCATION, learners=learners)


def test_signed_campus_site_unlimited_and_legacy_caps(signing_key):
    license = licensing.verify_license(sign(signing_key))
    assert license.tier == "campus_location"
    assert license.unlimited_learners
    assert license.seats is None
    assert license.location_id == "school-campus-001"
    assert license.expires is not None
    assert licensing.permits_learner_count(license, 100_000)
    assert licensing.location_matches(license, "school-campus-001")
    assert not licensing.location_matches(license, "school-campus-002")
    assert not licensing.location_matches(license, "")

    # Existing tiers still constrain numbers; an "unlimited" extra claim
    # cannot transmute a signed capped family into a campus entitlement.
    legacy = {
        "tier": "core", "seats": 6, "location_id": None,
        "learner_scope": None,
    }
    with pytest.raises(licensing.InvalidLicenseError):
        licensing.verify_license(sign(signing_key, **legacy))


@pytest.mark.parametrize("invalid", [
    {"seats": 999999},
    {"learner_scope": None},
    {"learner_scope": "all_locations"},
    {"location_id": ""},
    {"location_id": "../../other-branch"},
    {"location_id": "x" * 80},
    {"expires": None},
    {"expires": date.today().isoformat()},
    {"tier": "network"},
])
def test_bad_campus_license_never_grants_unlimited(signing_key, invalid):
    with pytest.raises(licensing.InvalidLicenseError):
        licensing.verify_license(sign(signing_key, **invalid))


def test_location_claim_is_in_the_signature(signing_key):
    value = sign(signing_key)
    payload, sig = value.split(".")
    padded = payload + "=" * (-len(payload) % 4)
    fields = json.loads(base64.urlsafe_b64decode(padded))
    fields["location_id"] = "school-campus-002"
    altered = base64.urlsafe_b64encode(
        json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()
    with pytest.raises(licensing.InvalidLicenseError, match="signature verification failed"):
        licensing.verify_license(f"{altered}.{sig}")


def test_license_state_fails_closed_on_wrong_location(signing_key, monkeypatch):
    key = sign(signing_key)
    old = license_state.current()
    try:
        monkeypatch.setattr(settings, "bede_location_id", "")
        assert not license_state.refresh(key, None, required=True).ok
        monkeypatch.setattr(settings, "bede_location_id", "school-campus-002")
        assert not license_state.refresh(key, None, required=True).ok
        monkeypatch.setattr(settings, "bede_location_id", "school-campus-001")
        state = license_state.refresh(key, None, required=True)
        assert state.ok
        assert license_state.effective_info().unlimited_learners
    finally:
        license_state._state = old


def test_manual_issuer_mints_expiring_campus_key(signing_key, tmp_path, monkeypatch, capsys):
    pem = tmp_path / "test-only-ed25519.pem"
    pem.write_text(signing_key.export_key(format="PEM"))
    monkeypatch.setenv("BEDE_LICENSE_LEDGER", str(tmp_path / "ledger.csv"))
    monkeypatch.setattr(sys, "argv", [
        "issue_license.py", "--tier", "campus_location",
        "--licensee", "Test Site License",
        "--location-id", "school-campus-001", "--days", "31",
        "--private-key", str(pem),
    ])
    issue_license.main()
    output = capsys.readouterr().out
    actual_key = output.split("LICENSE_KEY=", 1)[1].strip()
    issued = licensing.verify_license(actual_key)
    assert issued.unlimited_learners
    assert issued.location_id == "school-campus-001"
    assert issued.expires == date.today() + timedelta(days=31)
    assert "unlimited enrolled learners" in output


def test_manual_issuer_fails_without_site_or_attempts_numeric_seats(
    signing_key, tmp_path, monkeypatch,
):
    pem = tmp_path / "throwaway.pem"
    pem.write_text(signing_key.export_key(format="PEM"))
    monkeypatch.setenv("BEDE_LICENSE_LEDGER", str(tmp_path / "ledger.csv"))
    base = ["issue_license.py", "--tier", "campus_location",
            "--licensee", "Test Site License", "--days", "31",
            "--private-key", str(pem)]
    for args in (base, base + ["--location-id", "site-1", "--seats", "999999"]):
        monkeypatch.setattr(sys, "argv", args)
        with pytest.raises(SystemExit) as exc:
            issue_license.main()
        assert exc.value.code != 0
