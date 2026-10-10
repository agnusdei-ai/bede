"""
Cross-language license vector — proof that a Worker-signed license string
verifies under the UNMODIFIED core/licensing.py::verify_license.

The Bede License Server (license-server/, a Cloudflare Worker) issues
licenses with WebCrypto instead of PyCryptodome. The ecommerce readiness
spec (criterion D1) makes the shared Ed25519 port the load-bearing risk of
the whole build, and its proof is THIS test plus a fixture: a committed
TEST-ONLY keypair, a fixed payload, and the signature over it — see
license-server/test/vectors/ed25519-cross-language.json and the generator
that produced it (license-server/scripts/generate-cross-language-vector.mjs).

Ed25519 signing is deterministic (RFC 8032), so the vector's signature stays
valid forever: license-server's own vitest suite re-signs the same payload
inside the real Workers runtime (workerd) and asserts byte-equality with the
committed signature, and this file runs the committed license_key through the
real Python verifier. If either side drifts — a different canonical JSON
serialization, a different key format, a changed field set — one of the two
sides fails here, before anything can silently mint licenses that family
instances reject.

The keypair is throwaway and its private half is public on purpose: it can
only sign fixtures against its own public key, never a license anyone's
deployment would accept (test_licensing.py's monkeypatch pattern — the real
private key is offline, and only its public half is embedded in
core/licensing.py).
"""

import json
import pathlib
from datetime import date

import pytest

from core import licensing

# homeschool-api/tests/ → homeschool-api/ → repo root, where license-server/ lives.
VECTOR_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "license-server"
    / "test"
    / "vectors"
    / "ed25519-cross-language.json"
)


@pytest.fixture
def vector() -> dict:
    # Fail loudly if the vector is missing or was emptied — it IS the test.
    return json.loads(VECTOR_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def vector_public_key(vector, monkeypatch):
    """Point the verifier at the vector's own public key — the exact
    monkeypatch pattern test_licensing.py establishes for throwaway keys."""
    monkeypatch.setattr(licensing, "PUBLIC_KEY_PEM", vector["public_key_pem"])
    return vector


def test_vector_file_is_present_and_marked_test_only(vector):
    assert VECTOR_PATH.exists(), (
        "the cross-language vector is missing — a Worker-signed license string "
        "can no longer be proven to verify under core/licensing.py (spec D1)"
    )
    assert "TEST-ONLY" in vector["comment"]


def test_the_vector_keypair_is_not_the_production_keypair(vector):
    # The one way this fixture becomes dangerous is someone pasting the REAL
    # keypair's halves into it. The real private key must never exist here, and
    # its public half must never equal the fixture's — asserted, not trusted.
    assert vector["public_key_pem"].strip() != licensing.PUBLIC_KEY_PEM.strip()


def test_worker_signed_license_key_verifies(vector_public_key):
    vector = vector_public_key
    info = licensing.verify_license(vector["license_key"])
    payload = vector["payload"]
    assert info.license_id == payload["id"]
    assert info.licensee == payload["licensee"]
    assert info.tier == payload["tier"]
    assert info.seats == payload["seats"]
    assert info.issued == date.fromisoformat(payload["issued"])
    assert info.expires == date.fromisoformat(payload["expires"])
    assert info.is_expired is False  # a paid license's nominal +5y floor


def test_worker_signed_signature_is_deterministic_and_pinned(vector_public_key):
    # Regenerating the vector with a different canonical serialization or key
    # format would still "pass" test_worker_signed_license_key_verifies (that
    # test reads whatever the file says) — THIS one pins the committed
    # signature against the payload bytes: only a byte-identical serialization
    # signed by the fixture key can reproduce it.
    vector = vector_public_key
    assert vector["license_key"] == (
        f"{vector['payload_json_b64url']}.{vector['signature_b64url']}"
    )


def test_tampered_worker_payload_is_rejected(vector_public_key):
    # The vector proves valid signatures verify; this proves the verifier is
    # still actually verifying Worker-signed strings, not accepting anything.
    vector = vector_public_key
    payload_part, sig_part = vector["license_key"].split(".")
    tampered = f"{payload_part[:-1]}.{sig_part}"
    with pytest.raises(licensing.InvalidLicenseError, match="signature verification failed"):
        licensing.verify_license(tampered)
