"""
Centralised FastAPI dependencies for authentication and authorisation.

Every protected endpoint uses `Depends(require_auth)` or `Depends(require_parent)`.
These dependencies validate:
  1. JWT signature + expiry
  2. Device fingerprint match (IP + User-Agent bound at token issuance)
  3. Role authorisation (for parent-only routes)

Failures are always logged to the audit log before raising HTTPException.
"""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.audit import AuditEvent, audit_from_request, log_event
from core.demo_session import is_active as demo_session_is_active, touch as demo_session_touch
from core.middleware import compute_fingerprint
from core.security import decode_token, validate_fingerprint

_bearer = HTTPBearer()


async def _validate_token(request: Request, credentials: HTTPAuthorizationCredentials) -> dict:
    """Shared JWT signature/expiry + device fingerprint validation."""
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

    return payload


async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """Validate JWT + fingerprint. Returns payload dict for a *fully*
    authenticated session — rejects the transient "parent_pending" role
    (issued after a correct password but before the parent's enrolled
    security key/TOTP has been verified), which may only be used with
    require_mfa_pending to complete that second factor."""
    ctx = audit_from_request(request)
    payload = await _validate_token(request, credentials)

    if payload.get("role") == "parent_pending":
        await log_event(
            AuditEvent.ACCESS_DENIED,
            role="parent_pending",
            success=False,
            detail="MFA not yet completed",
            **ctx,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Second-factor verification required to finish logging in",
        )

    if payload.get("role") == "demo":
        jti = payload.get("jti", "")
        if not demo_session_is_active(jti):
            await log_event(
                AuditEvent.TOKEN_INVALID,
                role="demo",
                success=False,
                detail="superseded by a newer demo login, or idle for 5+ minutes",
                **ctx,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="This trial session ended — it was replaced by a newer login, or idle for 5+ minutes",
            )
        # Real, server-enforced backstop for the 5-minute inactivity window —
        # the frontend's own timer is UX only and can't be trusted as the
        # actual security boundary (see core/demo_session.py).
        demo_session_touch(jti)

    return payload


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
    ctx = audit_from_request(request)
    payload = await _validate_token(request, credentials)

    if payload.get("role") != "parent_pending":
        await log_event(
            AuditEvent.ACCESS_DENIED,
            role=payload.get("role"),
            success=False,
            detail="Not a pending MFA session",
            **ctx,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No second-factor verification is pending",
        )

    return payload


async def require_real_user(auth: dict = Depends(require_auth)) -> dict:
    """
    Same as require_auth, but rejects the scoped "demo" role — for every
    endpoint beyond the fixed demo chat and TTS (catalog browsing, student
    configs, narration history, transcripts, voice enrollment/verification).
    Parent and child both pass through unchanged.
    """
    if auth.get("role") == "demo":
        await log_event(
            AuditEvent.ACCESS_DENIED,
            role="demo",
            success=False,
            detail="Not available in demo mode",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not available in demo mode",
        )
    return auth


async def require_parent(auth: dict = Depends(require_auth)) -> dict:
    """Require parent role. Children and unauthenticated requests are rejected."""
    if auth.get("role") != "parent":
        await log_event(
            AuditEvent.ACCESS_DENIED,
            role=auth.get("role"),
            success=False,
            detail="Parent-only endpoint",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires parent authorisation",
        )
    return auth
