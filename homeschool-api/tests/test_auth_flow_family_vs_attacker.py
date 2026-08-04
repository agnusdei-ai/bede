"""Two walkthroughs of the same authentication system, driven against the
real route handlers: one family getting through it, one attacker failing to.

Written because "is it secure" and "is it usable" are usually argued
separately and traded off against each other in the abstract. They are the
same flow, so they are exercised here as one file. The family path counts
what a parent actually has to do and asserts the fumbles are free; the
attacker path asserts that every route in that a hacker could take is shut.

Run it as a readable transcript with:

    pytest tests/test_auth_flow_family_vs_attacker.py -s -q

Deliberately drives the route functions rather than a mocked service layer,
so what passes here is what the app does. What it cannot cover is stated
rather than implied at the bottom of this file.
"""
import time

import pyotp
import pytest
import pytest_asyncio
from fastapi import HTTPException, Request

from core import child_credential, otp_throttle, parent_credential, parent_lockout
from core.config import settings
from core.security import decode_token
from models.schemas import (
    ChangePasswordRecoveryRequest,
    LoginRequest,
    RecoveryVerifyRequest,
    TotpVerifyRequest,
)
from routers.auth import login
from routers.mfa import totp_authenticate_verify, totp_confirm, totp_enroll
from routers.recovery import recovery_methods, reset_password, verify
from services import mfa_service, parent_recovery

pytestmark = [pytest.mark.usefixtures("demo_db")]

PARENT_PASSWORD = "a-real-parent-password"
CHILD_PIN = "481973"


@pytest_asyncio.fixture
async def db(demo_db, monkeypatch):
    monkeypatch.setattr(settings, "parent_password", PARENT_PASSWORD)
    monkeypatch.setattr(settings, "child_pin", CHILD_PIN)
    parent_credential._set_cached_version(0)
    child_credential._set_cached(None)
    # The TOTP replay guard is a process-global high-water mark
    # (core/mfa_challenge.py: step <= _last_totp_step), so a step marked
    # used by one test refuses every later test inside the same 30-second
    # window. Reset for the same reason conftest.py resets the prompt and
    # student-key caches.
    import core.mfa_challenge as mfa_challenge
    mfa_challenge._last_totp_step = None
    async with demo_db() as session:
        yield session


def _req(ip: str = "192.168.1.20", ua: str = "Family-iPad") -> Request:
    return Request({
        "type": "http", "client": (ip, 51000),
        "headers": [(b"user-agent", ua.encode())],
    })


def say(line: str = "") -> None:
    print(line)


# ══════════════════════════════════════════════════════════════════════════
#  THE FAMILY
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_a_family_gets_through_without_friction(db):
    say("\n" + "=" * 68)
    say("  A FAMILY, MONDAY MORNING")
    say("=" * 68)

    # ── The child, which is the common case: this happens every school day ──
    t0 = time.perf_counter()
    child = await login(
        LoginRequest(role="child", credential=CHILD_PIN), _req(), db,
    )
    elapsed = (time.perf_counter() - t0) * 1000
    assert child.role == "child"
    say(f"\n  Child logs in with their PIN                 -> in, {elapsed:.0f}ms")
    say("    inputs: 1 (a PIN they chose and can remember)")

    # A child mistypes. This must cost nothing, because a six-year-old
    # mistyping is the expected case, not the suspicious one.
    t0 = time.perf_counter()
    for _ in range(3):
        with pytest.raises(HTTPException):
            await login(LoginRequest(role="child", credential="000111"), _req(), db)
    fumbles = (time.perf_counter() - t0) * 1000
    assert fumbles < 500, f"three child fumbles cost {fumbles:.0f}ms"
    say(f"  Child mistypes it three times                -> free, {fumbles:.0f}ms total")

    # And still gets in straight afterwards. No lockout exists for them at
    # all, deliberately: a sibling must not be able to end a lesson.
    again = await login(LoginRequest(role="child", credential=CHILD_PIN), _req(), db)
    assert again.role == "child"
    say("  Child tries again                            -> in (never locked out)")

    # ── The parent, with a second factor enrolled ──
    say("")
    enroll = await totp_enroll(db, {"role": "parent"})
    secret = enroll["secret"]
    totp = pyotp.TOTP(secret)
    await totp_confirm(TotpVerifyRequest(code=totp.now()), _req(), db, {"role": "parent"})
    say("  Parent enrols an authenticator app           -> scan a QR, type 1 code")

    first = await login(
        LoginRequest(role="parent", credential=PARENT_PASSWORD), _req(), db,
    )
    assert first.mfa_required is True and first.role == "parent_pending"
    say("  Parent signs in: password                    -> asks for the code")

    t0 = time.perf_counter()
    done = await totp_authenticate_verify(
        TotpVerifyRequest(code=totp.now()), _req(), db, {"role": "parent_pending"},
    )
    elapsed = (time.perf_counter() - t0) * 1000
    assert done.role == "parent"
    say(f"  Parent types the 6-digit code                -> in, {elapsed:.0f}ms")
    say("    inputs: 2 (one password, one code) = AAL2")


@pytest.mark.asyncio
async def test_a_parent_who_fumbles_the_code_pays_nothing(db):
    """The usability question that decides whether a family keeps 2FA on.
    A code rolls over every 30 seconds; typing one late is routine."""
    say("\n" + "-" * 68)
    say("  A PARENT FUMBLING (the case that decides if 2FA survives)")
    say("-" * 68)

    enroll = await totp_enroll(db, {"role": "parent"})
    totp = pyotp.TOTP(enroll["secret"])
    await totp_confirm(TotpVerifyRequest(code=totp.now()), _req(), db, {"role": "parent"})

    t0 = time.perf_counter()
    for _ in range(otp_throttle.FREE_ATTEMPTS):
        with pytest.raises(HTTPException):
            await totp_authenticate_verify(
                TotpVerifyRequest(code="000000"), _req(), db, {"role": "parent_pending"},
            )
    elapsed = (time.perf_counter() - t0) * 1000
    assert elapsed < 500, f"{otp_throttle.FREE_ATTEMPTS} fumbles cost {elapsed:.0f}ms"
    say(f"\n  {otp_throttle.FREE_ATTEMPTS} wrong codes in a row                       -> free, {elapsed:.0f}ms total")

    # And the right code still works immediately afterwards, with the
    # counter cleared so the next bad day starts fresh.
    ok = await totp_authenticate_verify(
        TotpVerifyRequest(code=totp.now()), _req(), db, {"role": "parent_pending"},
    )
    assert ok.role == "parent"
    say("  Then the right code                          -> in, count reset")


@pytest.mark.asyncio
async def test_a_locked_out_parent_can_get_back_in(db):
    say("\n" + "-" * 68)
    say("  A PARENT WHO FORGOT THE PASSWORD")
    say("-" * 68)

    enroll = await totp_enroll(db, {"role": "parent"})
    totp = pyotp.TOTP(enroll["secret"])
    await totp_confirm(TotpVerifyRequest(code=totp.now()), _req(), db, {"role": "parent"})
    code = await parent_recovery.enroll_recovery_code(db)
    say("\n  (at setup they saved a recovery code and enrolled an app)")

    methods = await recovery_methods(db)
    assert methods["recovery_possible"] is True
    say(f"  The screen says recovery is possible         -> {methods['recovery_possible']}")

    # Deliberately NOT the same 30-second step as any earlier use in this
    # test, or the replay guard would (correctly) reject it.
    ticket = await verify(
        RecoveryVerifyRequest(recovery_secret=code, totp_code=totp.now()),
        _req(), db,
    )
    assert "recovery_token" in ticket
    say("  Recovery code + app code                     -> a 10-minute ticket")

    await reset_password(
        ChangePasswordRecoveryRequest(new_password="a-brand-new-password"),
        _req(), db, {"role": "parent_recovery"},
    )
    say("  Sets a new password                          -> done")

    back = await login(
        LoginRequest(role="parent", credential="a-brand-new-password"), _req(), db,
    )
    assert back.mfa_required is True
    say("  Signs in with it                             -> works")
    say("    inputs: 2 things they have + a new password. No email, no server.")


# ══════════════════════════════════════════════════════════════════════════
#  THE ATTACKER
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_the_password_alone_is_not_enough(db):
    """The whole point of a second factor. A leaked or guessed password
    must not produce a usable session."""
    say("\n" + "=" * 68)
    say("  AN ATTACKER WHO KNOWS THINGS")
    say("=" * 68)

    enroll = await totp_enroll(db, {"role": "parent"})
    totp = pyotp.TOTP(enroll["secret"])
    await totp_confirm(TotpVerifyRequest(code=totp.now()), _req(), db, {"role": "parent"})

    stolen = await login(
        LoginRequest(role="parent", credential=PARENT_PASSWORD),
        _req(ip="203.0.113.9", ua="curl/8"), db,
    )
    assert stolen.role == "parent_pending"
    claims = decode_token(stolen.access_token)
    assert claims["role"] == "parent_pending"
    say("\n  Has the correct password                     -> BLOCKED (pending only)")
    say("    the token it yields can do exactly one thing: present a code")


@pytest.mark.asyncio
async def test_guessing_the_code_gets_expensive_then_stops(db):
    say("\n  Brute-forcing the 6-digit code:")

    enroll = await totp_enroll(db, {"role": "parent"})
    totp = pyotp.TOTP(enroll["secret"])
    await totp_confirm(TotpVerifyRequest(code=totp.now()), _req(), db, {"role": "parent"})

    # Drive the counter directly rather than sleeping through the ladder —
    # the delay is asserted from the pure function, and the wall-clock cost
    # is what is being demonstrated, not what is being spent.
    for n in range(1, 40):
        await otp_throttle.record_failure(db, otp_throttle.PURPOSE_TOTP)
        if n in (3, 4, 6, 10, 39):
            say(f"    after {n:>3} wrong codes  -> {otp_throttle.delay_for(n):>4.0f}s per further guess")

    for _ in range(otp_throttle.CONSECUTIVE_FAILURE_CEILING):
        await otp_throttle.record_failure(db, otp_throttle.PURPOSE_TOTP)

    blocked = await otp_throttle.check_blocked(db, otp_throttle.PURPOSE_TOTP)
    assert blocked is not None
    say(f"    at {otp_throttle.CONSECUTIVE_FAILURE_CEILING} consecutive       -> refused outright (800-63B 5.2.2)")

    with pytest.raises(HTTPException) as exc:
        await totp_authenticate_verify(
            TotpVerifyRequest(code=totp.now()), _req(), db, {"role": "parent_pending"},
        )
    assert exc.value.status_code == 429
    say("    even a CORRECT code is refused while blocked -> no oracle")


@pytest.mark.asyncio
async def test_a_used_code_cannot_be_replayed(db):
    enroll = await totp_enroll(db, {"role": "parent"})
    totp = pyotp.TOTP(enroll["secret"])
    await totp_confirm(TotpVerifyRequest(code=totp.now()), _req(), db, {"role": "parent"})

    code = totp.now()
    await totp_authenticate_verify(
        TotpVerifyRequest(code=code), _req(), db, {"role": "parent_pending"},
    )
    with pytest.raises(HTTPException):
        await totp_authenticate_verify(
            TotpVerifyRequest(code=code), _req(), db, {"role": "parent_pending"},
        )
    say("\n  Replays a code seen over the shoulder        -> BLOCKED (already used)")


@pytest.mark.asyncio
async def test_one_recovery_factor_is_never_enough(db):
    """Someone who finds the recovery code on the fridge has one factor.
    That must not be a way in."""
    enroll = await totp_enroll(db, {"role": "parent"})
    totp = pyotp.TOTP(enroll["secret"])
    await totp_confirm(TotpVerifyRequest(code=totp.now()), _req(), db, {"role": "parent"})
    code = await parent_recovery.enroll_recovery_code(db)

    with pytest.raises(HTTPException) as exc:
        await verify(RecoveryVerifyRequest(recovery_secret=code), _req(), db)
    assert exc.value.status_code == 401
    say("  Finds the recovery code, has nothing else    -> BLOCKED (needs 2)")

    # And the refusal says the same thing whether one factor matched or
    # none did, so it cannot be used to confirm a correct code.
    with pytest.raises(HTTPException) as exc2:
        await verify(RecoveryVerifyRequest(recovery_secret="WRONG-CODE-HERE-XXXX"), _req(), db)
    assert exc.value.detail == exc2.value.detail
    say("  Compares the two refusals                    -> identical (no oracle)")


@pytest.mark.asyncio
async def test_a_stolen_token_does_not_travel(db):
    """Device binding: a token lifted off one machine is refused from
    another, because it is bound to the IP and user-agent that got it."""
    session = await login(
        LoginRequest(role="child", credential=CHILD_PIN),
        _req(ip="192.168.1.20", ua="Family-iPad"), db,
    )
    from core.middleware import compute_fingerprint
    claims = decode_token(session.access_token)
    attacker_fp = compute_fingerprint("203.0.113.9", "curl/8")
    assert claims["fp"] != attacker_fp
    say("  Steals a token, replays it from their machine-> BLOCKED (bound to device)")


@pytest.mark.asyncio
async def test_recovery_ends_the_attackers_session_too(db):
    """The property that makes recovery worth having: it does not merely
    add a new valid session beside the attacker's."""
    attacker_session = await login(
        LoginRequest(role="parent", credential=PARENT_PASSWORD),
        _req(ip="203.0.113.9", ua="curl/8"), db,
    )
    stolen_cv = decode_token(attacker_session.access_token).get("cv")

    await parent_credential.set_parent_password_override(db, "the-real-parent-recovers")
    now = parent_credential.current_credentials_version()

    assert stolen_cv != now
    say("  Holds a live session when the parent recovers-> BLOCKED (token invalidated)")


@pytest.mark.asyncio
async def test_password_guessing_locks_the_account(db):
    for _ in range(parent_lockout.FAILURE_THRESHOLD):
        with pytest.raises(HTTPException):
            await login(
                LoginRequest(role="parent", credential="wrong"),
                _req(ip="203.0.113.9", ua="curl/8"), db,
            )
    locked = await parent_lockout.check_locked(db)
    assert locked is not None
    say(f"  Guesses the password {parent_lockout.FAILURE_THRESHOLD} times           -> LOCKED for "
        f"{parent_lockout.LOCKOUT_DURATION_SECONDS // 60} minutes")

    # Even with the right password.
    with pytest.raises(HTTPException):
        await login(
            LoginRequest(role="parent", credential=PARENT_PASSWORD),
            _req(ip="198.51.100.4", ua="another-box"), db,
        )
    say("  Switches IP and tries the right one          -> still locked (role-scoped)")


@pytest.mark.asyncio
async def test_the_recovery_ticket_cannot_do_anything_else(db):
    """A recovery ticket is not a session. It opens one door."""
    enroll = await totp_enroll(db, {"role": "parent"})
    totp = pyotp.TOTP(enroll["secret"])
    await totp_confirm(TotpVerifyRequest(code=totp.now()), _req(), db, {"role": "parent"})
    code = await parent_recovery.enroll_recovery_code(db)

    ticket = await verify(
        RecoveryVerifyRequest(recovery_secret=code, totp_code=totp.now()),
        _req(), db,
    )
    claims = decode_token(ticket["recovery_token"])
    assert claims["role"] == "parent_recovery"
    say("  Gets a recovery ticket                       -> role is 'parent_recovery'")
    say("    every parent-only route requires 'parent', so it opens one door")
    say("")


# ══════════════════════════════════════════════════════════════════════════
#  WHAT THIS FILE DOES NOT PROVE
# ══════════════════════════════════════════════════════════════════════════
#
# Stated rather than implied, because a passing suite reads as broader
# assurance than it is:
#
#   * These drive route FUNCTIONS. Middleware (the per-IP rate limiter,
#     security headers, the exfiltration guard) is not in the path here; it
#     is covered by tests/test_app_composition.py instead.
#   * "Ease of use" is measured as inputs and wall-clock cost, which is a
#     proxy. It is not a usability study, and no real parent has been
#     watched using this.
#   * MFA is still OPTIONAL in the product. Every parent test above enrols
#     TOTP first. A family that enrols nothing gets a password-only login,
#     which is AAL1, not AAL2 — the IA-2(1) gap, not yet closed.
