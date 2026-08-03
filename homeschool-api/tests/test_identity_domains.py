"""
Identity domain separation between the family deployment and the public
demo (docs/ARCHITECTURE_PRINCIPLES.md P10, core/identity.py).

The property under test is not "tokens still work". It is that a token
minted in the demo domain cannot be made to authenticate as a parent, by
anyone holding anything the demo path can produce — and that this holds at
the signature layer, before authorization runs, so it does not depend on
every present and future code path remembering to check a role.
"""
import base64
import hashlib
import hmac
import json
from datetime import timedelta

import pytest

from core import identity
from core.config import settings
from core.security import _b64url_decode, _b64url_encode, create_access_token, decode_token


def _parts(token: str):
    h, b, s = token.split(".")
    return json.loads(_b64url_decode(h)), json.loads(_b64url_decode(b)), s


def _resign(header: dict, payload: dict, key: bytes) -> str:
    h = _b64url_encode(json.dumps(header).encode())
    b = _b64url_encode(json.dumps(payload).encode())
    sig = hmac.new(key, f"{h}.{b}".encode(), hashlib.sha256).digest()
    return f"{h}.{b}.{_b64url_encode(sig)}"


# ── The attack the seam exists to stop ──────────────────────────────────────

def test_a_demo_token_cannot_be_rewritten_into_a_parent_token():
    """The whole point. Someone holding a legitimately-issued demo token
    tries to escalate by editing the role claim and re-signing with the only
    key their side of the system ever touches."""
    demo = create_access_token({"sub": "demo_code", "role": "demo_code", "code": "abc"})
    header, payload, _ = _parts(demo)

    payload["role"] = "parent"
    payload["sub"] = "parent"
    forged = _resign(header, payload, identity.signing_key(identity.DEMO))

    assert decode_token(forged) is None


def test_relabelling_the_domain_header_does_not_help():
    """Editing `dom` to family selects the family key for verification — so
    the forger now needs the family key, which is exactly the point. The
    signature they have is under the demo key."""
    demo = create_access_token({"sub": "demo_code", "role": "demo_code", "code": "abc"})
    header, payload, sig = _parts(demo)

    header["dom"] = identity.FAMILY
    payload["role"] = "parent"
    h = _b64url_encode(json.dumps(header).encode())
    b = _b64url_encode(json.dumps(payload).encode())
    assert decode_token(f"{h}.{b}.{sig}") is None


def test_a_parent_token_signed_in_the_demo_domain_is_rejected():
    """The reverse mistake: an issuing path that signs a privileged role
    under the wrong domain. This must fail loudly rather than work, or the
    boundary silently depends on getting every issue site right."""
    forged = _resign(
        {"alg": "HS256", "typ": "JWT", "dom": identity.DEMO},
        {"sub": "parent", "role": "parent", "exp": 9999999999},
        identity.signing_key(identity.DEMO),
    )
    assert decode_token(forged) is None


def test_an_unknown_domain_is_rejected_rather_than_defaulted():
    forged = _resign(
        {"alg": "HS256", "typ": "JWT", "dom": "family "},   # trailing space
        {"sub": "parent", "role": "parent", "exp": 9999999999},
        identity.signing_key(identity.FAMILY),
    )
    assert decode_token(forged) is None


# ── The keys are actually distinct ──────────────────────────────────────────

def test_the_two_domains_have_different_signing_keys():
    assert identity.signing_key(identity.FAMILY) != identity.signing_key(identity.DEMO)


def test_neither_domain_key_is_the_raw_secret():
    """A derivation bug that returned the secret unchanged would leave both
    domains sharing the legacy key and silently undo the separation."""
    raw = settings.secret_key.encode()
    assert identity.signing_key(identity.FAMILY) != raw
    assert identity.signing_key(identity.DEMO) != raw


def test_an_independent_demo_secret_shares_no_material_with_the_family_key(monkeypatch):
    before = identity.signing_key(identity.DEMO)
    monkeypatch.setattr(settings, "demo_secret_key", "an-entirely-separate-demo-secret-value")
    after = identity.signing_key(identity.DEMO)

    assert after != before
    assert after != identity.signing_key(identity.FAMILY)
    assert identity.demo_key_is_independent() is True


def test_demo_key_is_reported_as_derived_by_default():
    assert identity.demo_key_is_independent() is False


# ── Roles map to the right domain ───────────────────────────────────────────

@pytest.mark.parametrize("role", ["parent", "parent_pending", "child"])
def test_family_roles_sign_in_the_family_domain(role):
    header, _, _ = _parts(create_access_token({"sub": role, "role": role}))
    assert header["dom"] == identity.FAMILY


def test_demo_role_signs_in_the_demo_domain():
    header, _, _ = _parts(create_access_token({"sub": "demo_code", "role": "demo_code"}))
    assert header["dom"] == identity.DEMO


def test_an_unclassified_role_fails_closed_into_the_family_domain():
    """A role added later without being classified must land in the domain
    with the stricter checks, not the internet-facing one."""
    assert identity.domain_for_role("some_future_role") == identity.FAMILY
    assert identity.domain_for_role(None) == identity.FAMILY


# ── Ordinary tokens keep working ────────────────────────────────────────────

@pytest.mark.parametrize("role", ["parent", "child", "demo_code"])
def test_a_freshly_issued_token_round_trips(role):
    payload = decode_token(create_access_token({"sub": role, "role": role}))
    assert payload is not None and payload["role"] == role


def test_expected_domain_narrows_what_a_caller_accepts():
    demo = create_access_token({"sub": "demo_code", "role": "demo_code"})
    assert decode_token(demo, expected_domain=identity.DEMO) is not None
    assert decode_token(demo, expected_domain=identity.FAMILY) is None


def test_expiry_is_still_enforced():
    stale = create_access_token({"sub": "parent", "role": "parent"}, expires_delta=timedelta(seconds=-1))
    assert decode_token(stale) is None


def test_fingerprint_claim_survives_the_domain_change():
    payload = decode_token(create_access_token({"sub": "parent", "role": "parent"}, fingerprint="fp-abc"))
    assert payload["fp"] == "fp-abc"


# ── Migration: tokens issued before domains existed ─────────────────────────

def _legacy_token(role: str) -> str:
    """Exactly what create_access_token produced before this change: no
    `dom` header, signed with the raw secret."""
    return _resign(
        {"alg": "HS256", "typ": "JWT"},
        {"sub": role, "role": role, "exp": 9999999999},
        settings.secret_key.encode(),
    )


def test_a_pre_existing_session_is_not_signed_out_by_the_deploy():
    payload = decode_token(_legacy_token("parent"))
    assert payload is not None and payload["role"] == "parent"


def test_legacy_grace_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "legacy_token_grace", False)
    assert decode_token(_legacy_token("parent")) is None
    # New-style tokens are unaffected by the switch.
    assert decode_token(create_access_token({"sub": "parent", "role": "parent"})) is not None


def test_legacy_grace_does_not_accept_a_token_signed_with_a_domain_key():
    """The grace path must only cover genuinely old tokens. A domain-signed
    token with its header stripped would otherwise be a way to bypass the
    role/domain check."""
    demo = create_access_token({"sub": "demo_code", "role": "demo_code"})
    _, payload, _ = _parts(demo)
    payload["role"] = "parent"
    forged = _resign({"alg": "HS256", "typ": "JWT"}, payload, identity.signing_key(identity.DEMO))
    assert decode_token(forged) is None


# ── Malformed input ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("token", [
    "", "a.b", "a.b.c.d", "...", "not-a-token",
    "!!!.!!!.!!!",
])
def test_malformed_tokens_return_none_rather_than_raising(token):
    assert decode_token(token) is None


def test_a_non_object_header_is_rejected():
    h = _b64url_encode(json.dumps(["not", "an", "object"]).encode())
    b = _b64url_encode(json.dumps({"role": "parent", "exp": 9999999999}).encode())
    sig = hmac.new(settings.secret_key.encode(), f"{h}.{b}".encode(), hashlib.sha256).digest()
    assert decode_token(f"{h}.{b}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}") is None


# ── Deployment wiring ───────────────────────────────────────────────────────

def test_every_security_setting_reaches_the_container():
    """docker-compose.yml enumerates environment variables explicitly rather
    than using env_file, so a variable set in .env and not named there is
    silently dropped. That makes a documented-but-unwired setting worse than
    no setting: an operator sets ELEVATION_ENFORCED=true, sees no error, and
    believes the step-up is on. Caught exactly that way once already."""
    import pathlib
    import yaml

    root = pathlib.Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    declared = {
        e.split("=")[0]
        for svc in compose["services"].values()
        for e in (svc.get("environment") or [])
    }
    required = {"SECRET_KEY", "MASTER_SECRET", "DEMO_SECRET_KEY",
                "ELEVATION_ENFORCED", "ELEVATION_TTL_MINUTES", "LEGACY_TOKEN_GRACE"}

    assert required <= declared, f"not passed through to the container: {sorted(required - declared)}"


def test_the_public_demo_blueprint_gives_the_demo_domain_its_own_key():
    """render.yaml is the internet-facing, multi-tenant deployment — the one
    case where domain separation is not enough and the demo's signing key
    should share no material with the family's."""
    import pathlib
    import yaml

    root = pathlib.Path(__file__).resolve().parents[2]
    blueprint = yaml.safe_load((root / "render.yaml").read_text())
    env = {e["key"]: e for svc in blueprint["services"] for e in svc["envVars"]}

    assert "DEMO_SECRET_KEY" in env, "the public demo has no independent demo signing key"
    assert env["DEMO_SECRET_KEY"].get("generateValue") is True, (
        "should be generated, not hand-set — a key nobody handles is a key nobody leaks"
    )
