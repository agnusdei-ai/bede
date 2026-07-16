"""
Parent MFA: FIDO2 security keys (YubiKey, etc.) and TOTP authenticator apps.

Two distinct sets of endpoints, gated by two different dependencies:
  - Enrollment (register a key, enable TOTP, remove either) requires a FULL
    "parent" session (require_parent) — you must already be logged in to
    change your own second factors.
  - Completing login (using a key/code to finish a password login that
    returned mfa_required=True) requires the transient "parent_pending" role
    (require_mfa_pending) — see core/deps.py and routers/auth.py.

Production (non-demo) feature only — the demo role never reaches parent
auth at all, so nothing here is reachable from the public demo build.
"""

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit import AuditEvent, audit_from_request, log_event
from core.config import settings
from core.database import get_db
from core.deps import require_mfa_pending, require_parent
from core.middleware import compute_fingerprint
from core.security import create_access_token
from models.schemas import (
    TokenResponse,
    TotpConfirmRequest,
    TotpVerifyRequest,
    WebAuthnAuthVerifyRequest,
    WebAuthnRegisterVerifyRequest,
)
from services import mfa_service

router = APIRouter(prefix="/mfa", tags=["mfa"])


@router.get("/status")
async def status_(db: AsyncSession = Depends(get_db), _: dict = Depends(require_parent)):
    """What's enrolled right now — no secrets, just what a settings screen needs."""
    keys = await mfa_service.list_security_keys(db)
    totp = await mfa_service.get_totp_config(db)
    return {
        "webauthn_available": mfa_service.webauthn_enabled(),
        "security_keys": keys,
        "totp_enabled": bool(totp and totp.confirmed),
    }


# ── Enrollment (requires a full parent session) ──────────────────────────────

@router.post("/webauthn/register/options")
async def webauthn_register_options(db: AsyncSession = Depends(get_db), _: dict = Depends(require_parent)):
    try:
        return json.loads(await mfa_service.build_registration_options(db))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/webauthn/register/verify")
async def webauthn_register_verify(
    req: WebAuthnRegisterVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_parent),
):
    try:
        await mfa_service.verify_and_store_registration(db, json.dumps(req.credential), req.nickname)
    except Exception as e:
        await log_event(AuditEvent.AUTH_FAILURE, role="parent", success=False, detail=f"webauthn register failed: {e}", **audit_from_request(request))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not verify that security key — please try again")
    await log_event(AuditEvent.AUTH_SUCCESS, role="parent", success=True, detail="webauthn key enrolled", **audit_from_request(request))
    return {"success": True}


@router.delete("/webauthn/{key_id}")
async def webauthn_delete(key_id: int, db: AsyncSession = Depends(get_db), _: dict = Depends(require_parent)):
    if not await mfa_service.delete_security_key(db, key_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Security key not found")
    return {"success": True}


@router.post("/totp/enroll")
async def totp_enroll(db: AsyncSession = Depends(get_db), _: dict = Depends(require_parent)):
    """Generates a new secret — the plaintext secret and otpauth:// URI are
    only ever returned from this one call; only the encrypted form is stored."""
    secret, uri = await mfa_service.enroll_totp(db)
    return {"secret": secret, "otpauth_uri": uri}


@router.post("/totp/confirm")
async def totp_confirm(
    req: TotpConfirmRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_parent),
):
    if not await mfa_service.confirm_totp(db, req.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect code — check your authenticator app and try again")
    await log_event(AuditEvent.AUTH_SUCCESS, role="parent", success=True, detail="totp enrolled", **audit_from_request(request))
    return {"success": True}


@router.delete("/totp")
async def totp_disable(db: AsyncSession = Depends(get_db), _: dict = Depends(require_parent)):
    await mfa_service.disable_totp(db)
    return {"success": True}


# ── Completing a pending login (requires "parent_pending", not full parent) ─

def _issue_parent_token(request: Request, locale: str = "en") -> str:
    """locale comes from the pending token's own claim (see routers/auth.py's
    login()) — the parent picked their language at the password step, and
    completing MFA a moment later shouldn't silently reset it to English."""
    ctx = audit_from_request(request)
    fp = compute_fingerprint(ctx["ip"], ctx["user_agent"])
    return create_access_token(
        {"sub": "parent", "role": "parent", "locale": locale},
        fingerprint=fp,
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )


@router.post("/webauthn/authenticate/options")
async def webauthn_authenticate_options(db: AsyncSession = Depends(get_db), _: dict = Depends(require_mfa_pending)):
    options = await mfa_service.build_authentication_options(db)
    if not options:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No security key is enrolled")
    return json.loads(options)


@router.post("/webauthn/authenticate/verify", response_model=TokenResponse)
async def webauthn_authenticate_verify(
    req: WebAuthnAuthVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    pending: dict = Depends(require_mfa_pending),
):
    ctx = audit_from_request(request)
    if not await mfa_service.verify_authentication(db, json.dumps(req.credential)):
        await log_event(AuditEvent.AUTH_FAILURE, role="parent", success=False, detail="webauthn login verify failed", **ctx)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Security key verification failed")
    await log_event(AuditEvent.AUTH_SUCCESS, role="parent", success=True, detail="webauthn login", **ctx)
    return TokenResponse(access_token=_issue_parent_token(request, pending.get("locale", "en")), role="parent")


@router.post("/totp/authenticate/verify", response_model=TokenResponse)
async def totp_authenticate_verify(
    req: TotpVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    pending: dict = Depends(require_mfa_pending),
):
    ctx = audit_from_request(request)
    if not await mfa_service.verify_totp_login(db, req.code):
        await log_event(AuditEvent.AUTH_FAILURE, role="parent", success=False, detail="totp login verify failed", **ctx)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect or reused code")
    await log_event(AuditEvent.AUTH_SUCCESS, role="parent", success=True, detail="totp login", **ctx)
    return TokenResponse(access_token=_issue_parent_token(request, pending.get("locale", "en")), role="parent")
