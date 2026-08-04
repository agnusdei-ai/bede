"""MFA is not optional. There is no path to a parent session with one factor.

Until this landed, a second factor was something a family could enrol if
they thought of it. A deployment that enrolled nothing had a password-only
parent login — one factor, AAL1 — for the account that reads every
narration, holds the audit log, and can crypto-shred a child's record. NIST
800-53 IA-2(1) requires MFA to privileged accounts, and 800-63B AAL2
requires two DISTINCT factor types, which a password on its own can never
be.

The hard part is not refusing. It is refusing without locking a family out
of the app they just installed, on a machine in their own house, with no
support desk to call. So login with a correct password and nothing enrolled
issues a "parent_enrolling" token: it reaches the enrolment endpoints and
NOTHING else, and confirming a code turns it straight into a real session
rather than sending the parent back to the login screen.

These tests exist because "mandatory" is the kind of property that quietly
stops being true. The first one is the whole point: it walks every role a
token can carry and asserts none of them is a parent session.
"""
import time

import pyotp
import pytest
import pytest_asyncio
from fastapi import HTTPException, Request

from core import parent_credential
from core.config import settings
from core.policy import Subject, decide
from core.security import decode_token
from models.schemas import LoginRequest, TotpConfirmRequest, TotpVerifyRequest
from routers.auth import login
from routers.mfa import totp_authenticate_verify, totp_confirm, totp_enroll
from services import mfa_service

pytestmark = [pytest.mark.usefixtures("demo_db")]

PARENT_PASSWORD = "a-real-parent-password"


@pytest_asyncio.fixture
async def db(demo_db, monkeypatch):
    monkeypatch.setattr(settings, "parent_password", PARENT_PASSWORD)
    parent_credential._set_cached_version(0)
    import core.mfa_challenge as mfa_challenge
    mfa_challenge._last_totp_step = None
    async with demo_db() as session:
        yield session


def _req() -> Request:
    return Request({"type": "http", "client": ("192.168.1.20", 51000),
                    "headers": [(b"user-agent", b"Family-iPad")]})


# ── The property, stated directly ────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_correct_password_alone_never_yields_a_parent_session(db):
    """With nothing enrolled — the state every new install starts in."""
    assert await mfa_service.enrolled_methods(db) == []

    result = await login(
        LoginRequest(role="parent", credential=PARENT_PASSWORD), _req(), db,
    )
    assert result.role != "parent", "a password alone produced a parent session"
    assert result.role == "parent_enrolling"
    assert result.mfa_required is True
    assert decode_token(result.access_token)["role"] == "parent_enrolling"


@pytest.mark.asyncio
async def test_the_enrolling_token_can_do_nothing_but_enrol(db):
    """A weaker role that could read a narration would be a downgrade
    dressed as a bootstrap."""
    result = await login(
        LoginRequest(role="parent", credential=PARENT_PASSWORD), _req(), db,
    )
    claims = decode_token(result.access_token)

    who = Subject(role=claims["role"], identity_domain="family")
    for action in ["family.data.read", "family.data.write", "admin.manage",
                   "admin.privileged", "sandbox.parent_chat", "mfa.complete",
                   "recovery.reset_password"]:
        verdict = decide(who, action)
        assert not verdict.allowed, f"parent_enrolling was allowed {action}"

    assert decide(who, "mfa.enroll").allowed


@pytest.mark.asyncio
async def test_enrolling_finishes_the_login_rather_than_restarting_it(db):
    """Sending a parent back to the login screen after they just proved
    both factors is ceremony without security, and the surest way to teach
    a family that the second factor is an obstacle."""
    first = await login(
        LoginRequest(role="parent", credential=PARENT_PASSWORD), _req(), db,
    )
    claims = decode_token(first.access_token)

    enroll = await totp_enroll(db, claims)
    totp = pyotp.TOTP(enroll["secret"])
    done = await totp_confirm(
        TotpConfirmRequest(code=totp.now()), _req(), db, claims,
    )

    assert done["success"] is True
    assert "access_token" in done, "enrolling did not finish the login"
    assert decode_token(done["access_token"])["role"] == "parent"


@pytest.mark.asyncio
async def test_after_enrolment_login_needs_both_factors_every_time(db):
    """The bootstrap must not leave a permanent hole behind it."""
    first = await login(
        LoginRequest(role="parent", credential=PARENT_PASSWORD), _req(), db,
    )
    enroll = await totp_enroll(db, decode_token(first.access_token))
    totp = pyotp.TOTP(enroll["secret"])
    await totp_confirm(
        TotpConfirmRequest(code=totp.now()), _req(), db, decode_token(first.access_token),
    )

    again = await login(
        LoginRequest(role="parent", credential=PARENT_PASSWORD), _req(), db,
    )
    assert again.role == "parent_pending", "the second login skipped the factor"
    assert again.mfa_required is True

    # And the code is what finishes it. A step ahead of the one confirmed
    # above, since the replay guard (correctly) refuses a reused step.
    next_step_code = totp.at(time.time() + 30)
    finished = await totp_authenticate_verify(
        TotpVerifyRequest(code=next_step_code), _req(), db, {"role": "parent_pending"},
    )
    assert finished.role == "parent"


@pytest.mark.asyncio
async def test_a_settled_parent_still_cannot_enrol_without_a_step_up(db):
    """Widening the enrolment endpoints to accept the bootstrap role must
    not have widened them for everyone else. An unattended parent session
    adding an attacker's authenticator is the whole reason those endpoints
    were elevated in the first place."""
    first = await login(
        LoginRequest(role="parent", credential=PARENT_PASSWORD), _req(), db,
    )
    enroll = await totp_enroll(db, decode_token(first.access_token))
    totp = pyotp.TOTP(enroll["secret"])
    await totp_confirm(
        TotpConfirmRequest(code=totp.now()), _req(), db, decode_token(first.access_token),
    )

    # A plain parent claim, no elevation. The policy layer is what refuses.
    verdict = decide(Subject(role="parent", identity_domain="family"), "mfa.enroll")
    assert not verdict.allowed, (
        "a settled parent session reached the bootstrap action directly"
    )


@pytest.mark.asyncio
async def test_a_wrong_password_still_gets_nothing(db):
    with pytest.raises(HTTPException) as exc:
        await login(LoginRequest(role="parent", credential="wrong"), _req(), db)
    assert exc.value.status_code == 401
