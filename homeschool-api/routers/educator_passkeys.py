"""Strongly bound passkey-only institutional educator access.

No password, TOTP, PIN, SMS or email-only login fallback. Existing Bede
administrator must first authenticate with a WebAuthn security key to invite
or recover a school educator; the invitation only enables enrollment.
"""
from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit import AuditEvent, audit_from_request, log_event_nowait
from core.config import settings
from core.database import ClassicalEducator, EducatorPasskeyInvitation, get_db
from core.deps import require_elevated_parent, require_educator
from core.middleware import compute_fingerprint
from core.security import create_access_token
from models.schemas import TokenResponse
from services.educator_access import normalize_username, provision_educator
from services.educator_invites import issue_invitation, validate_invitation, _normalize_email, _digest
from services import educator_passkey_runtime as passkeys
from services.email_service import email_configured

router = APIRouter(prefix="/auth/educator-passkey", tags=["educator-passkey"])


class InviteRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    institutional_email: EmailStr


class RecoveryRequest(BaseModel):
    institutional_email: EmailStr


class CeremonyRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)


class CeremonyVerifyRequest(CeremonyRequest):
    ceremony_id: str = Field(min_length=36, max_length=36)
    credential: dict


class EnrollOptionsRequest(BaseModel):
    ticket_id: str = Field(min_length=36, max_length=36)
    ticket_token: str = Field(min_length=32, max_length=256)


class EnrollVerifyRequest(EnrollOptionsRequest):
    ceremony_id: str = Field(min_length=36, max_length=36)
    credential: dict


def _require_strong_admin(auth: dict) -> None:
    if auth.get("role") != "parent" or auth.get("auth_method") != "webauthn_uv":
        raise HTTPException(status_code=403, detail="A fresh Bede administrator passkey session is required")


def _enabled() -> None:
    if not settings.educator_pilot_enabled or settings.is_demo_deployment:
        raise HTTPException(status_code=403, detail="Institutional educator access is disabled")


@router.post("/invite", status_code=202)
async def invite_educator(
    body: InviteRequest, admin: dict = Depends(require_elevated_parent),
    db: AsyncSession = Depends(get_db),
):
    _enabled()
    _require_strong_admin(admin)
    if not email_configured():
        raise HTTPException(status_code=503, detail="Verified school invitation delivery is not configured")
    try:
        school_email = _normalize_email(str(body.institutional_email))
        username = normalize_username(body.username)
        # Each school mailbox must map to exactly one educator within this
        # Bede instance, including previously used invitations.
        matched = (await db.execute(
            select(EducatorPasskeyInvitation.id)
            .where(EducatorPasskeyInvitation.email_digest == _digest(school_email))
            .limit(1)
        )).scalar_one_or_none()
        if matched:
            raise ValueError("School mailbox already assigned to an educator")
        # Current schema requires legacy columns. Fill with high-entropy
        # UNKNOWN secrets; never return them to any caller. The old password
        # route is disabled independently and cannot sign in.
        # Keep educator identity and invitation in one transaction: a failed
        # delivery must not strand a credential-less account or block retry.
        created = await provision_educator(
            db, username, secrets.token_urlsafe(48), commit=False,
        )
        ok = await issue_invitation(db, created["id"], school_email)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        await db.rollback()
        raise
    if not ok:
        # issue_invitation rolls back a failed send, including the new account.
        await db.rollback()
        raise HTTPException(status_code=503, detail="School invitation delivery failed")
    return {"sent": True, "username": username, "message": "Passkey invite sent to verified school mailbox"}


@router.post("/recovery/{educator_id}", status_code=202)
async def recover_educator(
    educator_id: str, body: RecoveryRequest,
    admin: dict = Depends(require_elevated_parent),
    db: AsyncSession = Depends(get_db),
):
    _enabled()
    _require_strong_admin(admin)
    # A real campus administrator must independently confirm staff identity
    # and continued school affiliation before triggering this route.
    try:
        ok = await issue_invitation(db, educator_id, str(body.institutional_email), recovery=True)
    except ValueError:
        raise HTTPException(status_code=422, detail="School recovery criteria were not satisfied")
    if not ok:
        raise HTTPException(status_code=503, detail="Recovery notice could not be delivered")
    return {"sent": True}


@router.post("/register/options")
async def register_options(
    body: EnrollOptionsRequest, response: Response,
    db: AsyncSession = Depends(get_db),
):
    _enabled()
    response.headers["Cache-Control"] = "no-store"
    try:
        ticket = await validate_invitation(db, body.ticket_id, body.ticket_token)
        return await passkeys.registration_options(db, ticket.educator_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invitation is invalid or expired")


@router.post("/register/verify")
async def register_verify(
    body: EnrollVerifyRequest, response: Response,
    db: AsyncSession = Depends(get_db),
):
    _enabled()
    response.headers["Cache-Control"] = "no-store"
    try:
        ticket = await validate_invitation(db, body.ticket_id, body.ticket_token)
        await passkeys.verify_registration(
            db, ticket.educator_id, body.ceremony_id, body.credential,
            ticket_id=body.ticket_id, ticket_token=body.ticket_token,
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Passkey enrollment could not be verified")
    return {"registered": True, "sign_in_required": True}


@router.post("/login/options")
async def login_options(
    body: CeremonyRequest, response: Response,
    db: AsyncSession = Depends(get_db),
):
    _enabled()
    response.headers["Cache-Control"] = "no-store"
    try:
        username = normalize_username(body.username)
        account = (await db.execute(
            select(ClassicalEducator).where(ClassicalEducator.username == username)
        )).scalar_one_or_none()
        if account is None:
            raise ValueError("Unknown educator")
        return await passkeys.authentication_options(db, account.id)
    except ValueError:
        raise HTTPException(status_code=401, detail="No available passkey authentication")


@router.post("/login/verify", response_model=TokenResponse)
async def login_verify(
    body: CeremonyVerifyRequest, request: Request,
    response: Response, db: AsyncSession = Depends(get_db),
):
    _enabled()
    response.headers["Cache-Control"] = "no-store"
    try:
        username = normalize_username(body.username)
        account = (await db.execute(
            select(ClassicalEducator).where(ClassicalEducator.username == username)
        )).scalar_one_or_none()
        if not account:
            raise ValueError("Unknown educator")
        payload = await passkeys.verify_authentication(db, account.id, body.ceremony_id, body.credential)
    except Exception:
        log_event_nowait(AuditEvent.AUTH_FAILURE, role="educator", success=False,
                         **audit_from_request(request))
        raise HTTPException(status_code=401, detail="Passkey authentication failed")
    ctx = audit_from_request(request)
    token = create_access_token(
        payload, fingerprint=compute_fingerprint(ctx["ip"], ctx["user_agent"]),
        expires_delta=timedelta(minutes=60),
    )
    log_event_nowait(AuditEvent.AUTH_SUCCESS, role="educator", success=True, **ctx)
    return TokenResponse(access_token=token, role="educator")


@router.get("/credentials")
async def my_passkeys(auth: dict = Depends(require_educator),
                      db: AsyncSession = Depends(get_db)):
    """Own account only; no public keys, secrets or unrelated educators."""
    from core.database import EducatorWebAuthnCredential
    rows = (await db.execute(
        select(EducatorWebAuthnCredential)
        .where(EducatorWebAuthnCredential.educator_id == auth["sub"])
        .where(EducatorWebAuthnCredential.enabled.is_(True))
        .order_by(EducatorWebAuthnCredential.created_at)
    )).scalars().all()
    return [{"id": row.credential_id, "created_at": row.created_at.isoformat()}
            for row in rows]


@router.post("/credentials/{credential_id}/revoke")
async def revoke_my_passkey(
    credential_id: str, auth: dict = Depends(require_educator),
    db: AsyncSession = Depends(get_db),
):
    """Only a UV-verified current session can revoke its own key."""
    _enabled()
    if auth.get("auth_method") != "webauthn_uv":
        raise HTTPException(status_code=403, detail="Verified passkey required")
    from core.database import EducatorWebAuthnCredential
    rows = (await db.execute(
        select(EducatorWebAuthnCredential.credential_id)
        .where(EducatorWebAuthnCredential.educator_id == auth["sub"])
        .where(EducatorWebAuthnCredential.enabled.is_(True))
    )).scalars().all()
    if credential_id not in rows:
        raise HTTPException(status_code=404, detail="Credential is not active")
    if len(rows) <= 1:
        raise HTTPException(status_code=409, detail="Cannot revoke your last passkey. Contact your school administrator for supervised recovery.")
    await passkeys.revoke_credential(db, auth["sub"], credential_id)
    return {"revoked": True, "all_previous_sessions_invalidated": True}
