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
from core.middleware import compute_fingerprint
from core.security import decode_token, validate_fingerprint

_bearer = HTTPBearer()


async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """Validate JWT + fingerprint. Returns payload dict."""
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


async def require_real_user(auth: dict = Depends(require_auth)) -> dict:
    """
    Same as require_auth, but rejects the scoped "demo" role — for every
    endpoint beyond the fixed demo chat itself (catalog browsing, student
    configs, narration history, transcripts, voice, TTS). Parent and child
    both pass through unchanged.
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
