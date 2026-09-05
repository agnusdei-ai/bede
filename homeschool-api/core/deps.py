"""
Centralised FastAPI dependencies for authentication and authorisation.

This module is the POLICY ENFORCEMENT layer. It authenticates the caller,
builds a Subject, asks core/policy.py for a decision, and either allows the
request or raises. It deliberately contains no authorization *logic* of its
own — the "may they" question lives in core/policy.py, where it's a pure
function over a readable table (P7 in docs/ARCHITECTURE_PRINCIPLES.md).

Every protected endpoint uses one of the guards below. Each validates:
  1. JWT signature + expiry
  2. Device fingerprint match (IP + User-Agent bound at token issuance)
  3. credentials_version, for parent/parent_pending tokens
  4. Device revocation, for parent/child tokens carrying a device_id claim
     (core/device_registry.py, P9)
  5. The policy decision for the action being guarded
  6. Session liveness, where the session is server-tracked (demo codes)
  7. A current privileged-access elevation, for the management-plane
     actions core/policy.py marks as requiring one (P8)

Failures are always logged to the audit log before raising HTTPException.

The original five guards keep the exact signatures, status codes, and
user-visible messages they had before the policy layer existed. That equivalence is
load-bearing and covered by tests/test_deps_policy_equivalence.py: this
refactor claims to change where the decision is made, not what gets decided.
"""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from core import device_registry, elevation
from core.audit import AuditEvent, audit_from_request, log_event
from core.config import settings
from core.database import get_db
from core.demo_code_session import code_exists as demo_code_exists
from core.middleware import compute_fingerprint
from core.parent_credential import current_credentials_version
from core.policy import Subject, decide
from core.security import decode_token, validate_fingerprint

_bearer = HTTPBearer()


async def _validate_token(request: Request, credentials: HTTPAuthorizationCredentials) -> dict:
    """Shared JWT signature/expiry + device fingerprint validation.

    Authentication only — this establishes that the token is genuine and
    was issued to this device. It says nothing about what the bearer may do;
    that's _authorize()'s job."""
    ctx = audit_from_request(request)

    payload = decode_token(credentials.credentials)
    if not payload:
        await log_event(AuditEvent.TOKEN_INVALID, success=False, **ctx)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session — please log in again",
        )

    fp = compute_fingerprint(ctx["ip"], ctx["user_agent"])
    if not validate_fingerprint(payload, fp):
        await log_event(
            AuditEvent.TOKEN_FINGERPRINT_MISMATCH,
            role=payload.get("role"),
            success=False,
            **ctx,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session cannot be used from a different device — please log in again",
        )

    # Only parent/parent_pending tokens carry a 'cv' (credentials_version)
    # claim — see core/parent_credential.py. A mismatch means the password
    # changed (in-app change, or the 2-factor recovery flow) after this
    # token was issued: the whole point of that mechanism is that an old
    # token, including one an attacker may be holding, must stop working
    # the moment a new password is set, not linger until natural expiry.
    if payload.get("role") in ("parent", "parent_pending") and "cv" in payload:
        if payload["cv"] != current_credentials_version():
            await log_event(
                AuditEvent.TOKEN_INVALID,
                role=payload.get("role"),
                success=False,
                detail="credentials_version mismatch — password changed since this token was issued",
                **ctx,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Your password was changed — please log in again",
            )

    # P9 device revocation (core/device_registry.py). Only parent/child
    # tokens ever carry a 'device_id' claim (routers/auth.py's login()) —
    # demo_code sessions are anonymous and were never registered. A revoked
    # device's token stops working on its very next request, not just at
    # its next login; that is the whole point of a revocation mechanism —
    # see docs/DEVICE_IDENTITY_DESIGN.md.
    device_id = payload.get("device_id")
    if device_id and device_registry.is_revoked(device_id):
        await log_event(
            AuditEvent.DEVICE_LOGIN_BLOCKED,
            role=payload.get("role"),
            success=False,
            detail="request rejected — this device was revoked",
            **ctx,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This device's access was revoked — please contact the parent",
        )

    return payload


async def _authorize(request: Request, payload: dict, action: str) -> dict:
    """Ask the policy layer, audit a denial, raise or return.

    The single place an authorization decision is enforced. Any new guard
    goes through here rather than inlining a role comparison — an inline
    check is invisible to anyone auditing what the policy actually is, which
    is how five of them ended up scattered through router bodies before this
    layer existed."""
    subject = Subject.from_token(payload)
    decision = decide(subject, action)
    if not decision.allowed:
        await log_event(
            AuditEvent.ACCESS_DENIED,
            role=subject.role or None,
            success=False,
            detail=f"action={action} — {decision.reason}",
            **audit_from_request(request),
        )
        raise HTTPException(status_code=decision.status_code, detail=decision.reason)
    return payload


async def _require_live_session(request: Request, payload: dict) -> dict:
    """Session liveness for server-tracked sessions.

    Separate from the policy decision on purpose: this needs a database read,
    and core/policy.py is pure. Policy answers "may this subject do this";
    this answers "is this session still real". Only demo codes are tracked
    server-side — parent/child tokens are stateless JWTs with no server-side
    session to check (see routers/auth.py's logout)."""
    if payload.get("role") != "demo_code":
        return payload
    code = payload.get("code", "")
    if not await demo_code_exists(code):
        await log_event(
            AuditEvent.TOKEN_INVALID,
            role="demo_code",
            success=False,
            detail="code was logged out or forgotten (long abandoned)",
            **audit_from_request(request),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This session ended — generate a new code to keep exploring",
        )
    return payload


# ── Guards ───────────────────────────────────────────────────────────────────

async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """Validate JWT + fingerprint for a *fully* authenticated session.

    Rejects the transient roles — "parent_pending" (password verified,
    second factor outstanding) and "parent_recovery" (2 recovery factors
    verified, may only set a new password). Each is usable solely with its
    own guard below.

    Note "parent_recovery" specifically: before the policy layer, this guard
    rejected parent_pending by name and said nothing about parent_recovery,
    so a recovery token could reach any of the 17 endpoints behind this
    guard. Enumerating transient roles in core/policy.py rather than
    rejecting known-bad ones case by case is what closes that."""
    payload = await _validate_token(request, credentials)
    await _authorize(request, payload, "session.self")
    return await _require_live_session(request, payload)


async def require_mfa_pending(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """
    Validate JWT + fingerprint for the transient "parent_pending" role only —
    used exclusively by the MFA completion endpoints in routers/mfa.py. A
    fully authenticated "parent" token is deliberately NOT accepted here,
    since there'd be nothing left to complete.
    """
    payload = await _validate_token(request, credentials)
    return await _authorize(request, payload, "mfa.complete")


async def require_parent_recovery(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """Validate JWT + fingerprint for the transient "parent_recovery" role
    only — issued by routers/recovery.py's verify() once the parent has
    proven >=2 of {recovery_code, totp, webauthn}, and usable for exactly
    one thing: POST /auth/recovery/reset-password. Deliberately a separate
    role from "parent_pending" (which means "password already verified,
    second factor still needed") — recovery is a different trust path
    entirely, reached WITHOUT the password."""
    payload = await _validate_token(request, credentials)
    return await _authorize(request, payload, "recovery.reset_password")


async def require_real_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """
    Same as require_auth, but rejects the scoped "demo_code" role — for
    every endpoint beyond the fixed demo chat/TTS and the diagnostic
    preview itself (catalog browsing, student configs, narration history,
    transcripts, voice enrollment/verification). Parent and child both
    pass through unchanged.
    """
    payload = await _validate_token(request, credentials)
    await _authorize(request, payload, "family.data.read")
    return await _require_live_session(request, payload)


async def require_parent(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """Require parent role. Children, the demo role, transient roles, and
    unauthenticated requests are all rejected."""
    payload = await _validate_token(request, credentials)
    return await _authorize(request, payload, "admin.manage")


async def require_elevated_parent(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Require parent role AND a current privileged-access elevation (P8).

    For the management-plane actions a parent cannot undo by trying again:
    reading the audit log, repointing the AI provider, changing an
    authentication factor, permanently destroying a student's data. See
    core/policy.py's _REQUIRES_ELEVATION for where the line is drawn and
    core/elevation.py for what an elevation is.

    The 403 is deliberately distinguishable from an ordinary authorization
    denial by its `elevation_required` marker, so the frontend can prompt
    for the password rather than showing "not authorized" to the one person
    who is."""
    payload = await _validate_token(request, credentials)
    await _authorize(request, payload, "admin.privileged")

    # See settings.elevation_enforced for why this can be off, and why that
    # is temporary. The policy decision above still runs either way — only
    # the step-up requirement is gated, so turning it on changes one thing
    # rather than switching on an untested path.
    if not settings.elevation_enforced:
        return payload

    if not await elevation.is_elevated(db, payload.get("jti")):
        await log_event(
            AuditEvent.ACCESS_DENIED,
            role=payload.get("role"),
            success=False,
            detail="action=admin.privileged — no current elevation",
            **audit_from_request(request),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Confirm your password to continue — this action needs to be re-authorised",
                "elevation_required": True,
            },
        )
    return payload


# ── Action-specific guards (previously inline role checks in routers) ────────
# Each of these replaces a hand-written `role == "..."` comparison in a router
# body. Those were real authorization decisions living outside the dependency
# layer, invisible to anyone auditing authorization by reading deps.py or
# grepping for Depends(...).

async def require_email_summary(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """Parent or demo visitor may email a session summary; a child may not
    (they should not be able to send mail to an arbitrary address).
    Replaces routers/tutor.py's inline `role not in ("parent", "demo_code")`."""
    payload = await _validate_token(request, credentials)
    await _authorize(request, payload, "tutor.email_summary")
    return await _require_live_session(request, payload)


async def require_demo_parent_config(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """The demo's own Parent Setup (POST /auth/demo-code/config) — the
    visitor configuring their own demo session. Its own policy action
    rather than a third use of require_demo_preview: this one WRITES, and
    an action that changes what the model is told should not ride on a
    guard whose name and docstring say "preview"."""
    payload = await _validate_token(request, credentials)
    await _authorize(request, payload, "demo.parent_config")
    return await _require_live_session(request, payload)


async def require_demo_preview(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """Public-demo previews (the sandbox preview, the diagnostic preview) —
    reachable only from the demo identity domain, deliberately not by a real
    family session. Replaces the inline `role != "demo_code"` checks in
    routers/sandbox.py and routers/diagnostic.py."""
    payload = await _validate_token(request, credentials)
    await _authorize(request, payload, "sandbox.demo_preview")
    return await _require_live_session(request, payload)
