"""Device-native biometrics are the primary factor, and the biometric is
actually required rather than merely requested.

TOTP is secondary to a biometric native to the device. A platform
authenticator — Face ID, Touch ID, Windows Hello — never sends the
biometric anywhere, keeps the private key hardware-backed and
non-exportable, binds its signature to the origin (so it cannot be
phished), and gets presentation-attack detection from the platform. A TOTP
code has none of those properties: it is a shared secret typed into a box.
It stays as the fallback for a device with no biometric sensor.

What this file exists to stop coming back:

WebAuthn was configured with user_verification=PREFERRED on both the
registration and authentication options, and neither verification call
passed require_user_verification. py_webauthn defaults that argument to
False, so the UV flag in the authenticator data was never inspected.
PREFERRED lets the authenticator skip the user check entirely, which
reduces the whole credential to possession — a signature from a device that
may or may not have checked who was holding it. The deployment looked like
it had biometrics and had a bearer key in a nice case.

Asking for user verification and CHECKING it are different things, and only
the second one is a control. Both are asserted below.
"""
import inspect

import pytest

from services import mfa_service


def _source(fn) -> str:
    return inspect.getsource(fn)


# ── The registration ceremony ────────────────────────────────────────────

def test_registration_requires_the_on_device_check():
    """PREFERRED would let an authenticator register without ever verifying
    its holder, leaving a possession-only credential wearing the word
    'biometric'."""
    src = _source(mfa_service.build_registration_options)
    assert "UserVerificationRequirement.REQUIRED" in src
    assert "UserVerificationRequirement.PREFERRED" not in src


def test_registration_allows_a_passkey():
    """DISCOURAGED blocks the discoverable credential that makes Face ID and
    Windows Hello work as a passkey rather than as a bare security key."""
    src = _source(mfa_service.build_registration_options)
    assert "ResidentKeyRequirement.PREFERRED" in src
    assert "ResidentKeyRequirement.DISCOURAGED" not in src


def test_registration_verification_enforces_it():
    """The options are a request the client is free to ignore. This is the
    check that the flag actually came back set."""
    src = _source(mfa_service.verify_and_store_registration)
    assert "require_user_verification=True" in src


# ── The authentication ceremony ──────────────────────────────────────────

def test_authentication_requires_the_on_device_check():
    src = _source(mfa_service.build_authentication_options)
    assert "UserVerificationRequirement.REQUIRED" in src
    assert "UserVerificationRequirement.PREFERRED" not in src


def test_authentication_verification_enforces_it():
    """The single most important line in this file. Without it, every login
    through the WebAuthn path proves the device was present and nothing
    about who was holding it."""
    src = _source(mfa_service.verify_authentication)
    assert "require_user_verification=True" in src, (
        "the biometric is requested but never verified — this is a "
        "possession-only credential presented as a biometric one"
    )


def test_no_verification_call_is_left_unchecked():
    """A future third ceremony (a second key type, a re-auth path) must not
    quietly reintroduce the default."""
    import re

    src = inspect.getsource(mfa_service)
    calls = re.findall(r"webauthn\.verify_\w+_response\((.*?)\n    \)", src, re.S)
    assert calls, "no verification calls found — did they move?"
    for call in calls:
        assert "require_user_verification=True" in call, (
            f"a WebAuthn verification call omits require_user_verification: {call[:120]}"
        )


# ── Ordering: which factor a family is offered first ─────────────────────

@pytest.mark.asyncio
@pytest.mark.usefixtures("demo_db")
async def test_the_biometric_is_offered_before_the_code(demo_db):
    """enrolled_methods feeds the login screen. A device-native biometric
    should be what a parent reaches for; the code is the fallback for
    hardware without a sensor."""
    import pyotp

    async with demo_db() as db:
        secret, _ = await mfa_service.enroll_totp(db)
        await mfa_service.confirm_totp(db, pyotp.TOTP(secret).now())
        methods = await mfa_service.enrolled_methods(db)

    assert methods == ["totp"], methods
    # With both enrolled the biometric must come first. Asserted on the
    # function's own ordering rather than by enrolling a real credential,
    # which needs a browser.
    src = _source(mfa_service.enrolled_methods)
    assert src.index('"webauthn"') < src.index('"totp"'), (
        "TOTP is listed before the device biometric"
    )
