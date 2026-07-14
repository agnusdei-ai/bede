"""
Regression tests for core/config.py's cross-field validators around
SANDBOX_PIN — must never collide with another real credential, and must
meet the same strength bar as CHILD_PIN/DEMO_PIN once PRODUCTION=true —
and around LICENSE_KEY, required once PRODUCTION=true for a real family
deployment but exempt for the public demo (see core/licensing.py and
Settings.is_demo_deployment).

Note: conftest.py sets DEMO_PIN=384756 as a process-wide env default, so
every license test below that means to exercise the "real family
production" path passes demo_pin="" explicitly to opt back out of that
default — otherwise is_demo_deployment would be True and the license
check would be silently skipped instead of exercised.
"""
import base64
import json
import uuid
from datetime import date

import pytest
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from core import licensing
from core.config import Settings


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


@pytest.fixture
def valid_license(monkeypatch):
    """A license signed against a throwaway keypair, with
    licensing.PUBLIC_KEY_PEM monkeypatched to match — see
    tests/test_licensing.py for why real-keypair signing isn't used here."""
    key = ECC.generate(curve="ed25519")
    monkeypatch.setattr(licensing, "PUBLIC_KEY_PEM", key.public_key().export_key(format="PEM"))
    payload = {
        "id": str(uuid.uuid4()), "licensee": "Test Family", "tier": "core",
        "seats": 10, "issued": date.today().isoformat(), "expires": None,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = eddsa.new(key, "rfc8032").sign(payload_bytes)
    return f"{_b64url(payload_bytes)}.{_b64url(signature)}"


def test_sandbox_pin_matching_parent_password_rejected():
    with pytest.raises(ValueError, match="SANDBOX_PIN"):
        Settings(sandbox_pin="602656", parent_password="602656")


def test_sandbox_pin_matching_child_pin_rejected():
    with pytest.raises(ValueError, match="SANDBOX_PIN"):
        Settings(sandbox_pin="602656", child_pin="602656")


def test_sandbox_pin_matching_demo_pin_rejected():
    with pytest.raises(ValueError, match="SANDBOX_PIN"):
        Settings(sandbox_pin="602656", demo_pin="602656")


def test_sandbox_pin_distinct_from_everything_is_accepted():
    s = Settings(sandbox_pin="602656", parent_password="x", child_pin="111222", demo_pin="333444")
    assert s.sandbox_pin == "602656"


def test_sandbox_pin_empty_by_default():
    assert Settings().sandbox_pin == ""


def test_weak_sandbox_pin_rejected_in_production(valid_license):
    with pytest.raises(ValueError, match="SANDBOX_PIN"):
        Settings(
            production="true",
            secret_key="a" * 40,
            parent_password="a-strong-password",
            child_pin="602656",
            master_secret="b" * 40,
            sandbox_pin="111111",
            license_key=valid_license,
        )


def test_strong_sandbox_pin_accepted_in_production(valid_license):
    # 749283 deliberately differs from conftest.py's DEMO_PIN env default
    # (384756) — Settings() falls back to the environment for any field not
    # passed explicitly, so reusing that value here would collide with it.
    s = Settings(
        production="true",
        secret_key="a" * 40,
        parent_password="a-strong-password",
        child_pin="602656",
        master_secret="b" * 40,
        sandbox_pin="749283",
        license_key=valid_license,
    )
    assert s.sandbox_pin == "749283"


def test_unset_sandbox_pin_never_blocks_production_startup(valid_license):
    """Empty = disabled, same as DEMO_PIN — must not itself trigger a
    weak-default failure just because it's unset."""
    s = Settings(
        production="true",
        secret_key="a" * 40,
        parent_password="a-strong-password",
        child_pin="602656",
        master_secret="b" * 40,
        license_key=valid_license,
    )
    assert s.sandbox_pin == ""


# ── LICENSE_KEY ──────────────────────────────────────────────────────────

def test_missing_license_key_rejected_in_production():
    with pytest.raises(ValueError, match="LICENSE_KEY is not set"):
        Settings(
            production="true",
            secret_key="a" * 40,
            parent_password="a-strong-password",
            child_pin="602656",
            master_secret="b" * 40,
            demo_pin="",
        )


def test_invalid_license_key_rejected_in_production():
    with pytest.raises(ValueError, match="LICENSE_KEY is invalid"):
        Settings(
            production="true",
            secret_key="a" * 40,
            parent_password="a-strong-password",
            child_pin="602656",
            master_secret="b" * 40,
            license_key="not-a-real-license",
            demo_pin="",
        )


def test_valid_license_key_accepted_in_production(valid_license):
    s = Settings(
        production="true",
        secret_key="a" * 40,
        parent_password="a-strong-password",
        child_pin="602656",
        master_secret="b" * 40,
        license_key=valid_license,
        demo_pin="",
    )
    assert s.license_key == valid_license


def test_license_key_not_required_outside_production():
    s = Settings(license_key="")
    assert s.license_key == ""


def test_expired_license_key_rejected_in_production(monkeypatch):
    import base64 as _b64
    from datetime import timedelta

    key = ECC.generate(curve="ed25519")
    monkeypatch.setattr(licensing, "PUBLIC_KEY_PEM", key.public_key().export_key(format="PEM"))
    payload = {
        "id": str(uuid.uuid4()), "licensee": "Expired Trial", "tier": "trial",
        "seats": 10, "issued": date.today().isoformat(),
        "expires": (date.today() - timedelta(days=1)).isoformat(),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = eddsa.new(key, "rfc8032").sign(payload_bytes)
    expired_license = f"{_b64url(payload_bytes)}.{_b64url(signature)}"

    with pytest.raises(ValueError, match="LICENSE_KEY expired"):
        Settings(
            production="true",
            secret_key="a" * 40,
            parent_password="a-strong-password",
            child_pin="602656",
            master_secret="b" * 40,
            license_key=expired_license,
            demo_pin="",
        )


# ── Public demo exemption ──────────────────────────────────────────────────

def test_demo_deployment_exempt_from_missing_license():
    """DEMO_PIN set + PRODUCTION=true + no LICENSE_KEY at all must boot
    clean — this is exactly bede-demo-api's real render.yaml shape."""
    s = Settings(
        production="true",
        secret_key="a" * 40,
        parent_password="a-strong-password",
        child_pin="602656",
        master_secret="b" * 40,
        demo_pin="749283",
    )
    assert s.license_key == ""


def test_demo_deployment_exempt_from_invalid_license():
    s = Settings(
        production="true",
        secret_key="a" * 40,
        parent_password="a-strong-password",
        child_pin="602656",
        master_secret="b" * 40,
        demo_pin="749283",
        license_key="not-a-real-license",
    )
    assert s.license_key == "not-a-real-license"


def test_is_demo_deployment_reflects_demo_pin():
    assert Settings(demo_pin="").is_demo_deployment is False
    assert Settings(demo_pin="749283").is_demo_deployment is True


def test_real_family_production_without_demo_pin_still_requires_license():
    """The exemption must not accidentally widen to all of production —
    a real family install (demo_pin empty) still needs a valid license."""
    with pytest.raises(ValueError, match="LICENSE_KEY is not set"):
        Settings(
            production="true",
            secret_key="a" * 40,
            parent_password="a-strong-password",
            child_pin="602656",
            master_secret="b" * 40,
            demo_pin="",
        )
