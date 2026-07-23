"""
Parent account recovery — regaining access when PARENT_PASSWORD (and
possibly a lost/forgotten second factor) are both unavailable, without
editing .env or restarting the server. Requires proving AT LEAST 2 of the
enrolled recovery factors: a recovery PIN or recovery code (mutually
exclusive — services/parent_recovery.py), TOTP, and/or WebAuthn
(services/mfa_service.py, reused unchanged — a recovery-flow WebAuthn
ceremony is identical to a login one).

Deliberately >=2, not "any one" — a family enrolling only one recovery
method can't use this flow at all (the methods/ endpoint below tells the
frontend which, so it can say so honestly) rather than silently accepting
a single weak factor. See docs/SECURITY.md's "Closed gaps" for the
design rationale, including why voice biometrics are NOT a recovery
factor here (no liveness/anti-spoof check — see the persona-security
discussion this closes).

Entirely public/unauthenticated (that's the point — a locked-out parent
has no valid session to authenticate with) but scoped to exactly two
things a successful recovery can do: issue a narrow "parent_recovery"
token (core/deps.py's require_parent_recovery), and use that token to set
a new password. It cannot read or change anything else.
"""
import json
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit import AuditEvent, audit_from_request, log_event
from core.config import MIN_PASSWORD_LENGTH
from core.database import get_db
from core.deps import require_parent_recovery
from core.middleware import compute_fingerprint
from core.parent_credential import set_parent_password_override
from core.security import create_access_token
from models.schemas import ChangePasswordRecoveryRequest, RecoveryVerifyRequest
from services import mfa_service, parent_recovery

router = APIRouter(prefix="/auth/recovery", tags=["recovery"])

# How many of the attempted factors must verify. Not a magic number scattered
# across the module — see the file docstring for why this is >=2, not 1.
_REQUIRED_FACTORS = 2

_RECOVERY_TOKEN_EXPIRE_MINUTES = 10


@router.get("/methods")
async def recovery_methods(db: AsyncSession = Depends(get_db)):
    """Public — which recovery factors are enrolled (booleans/kind only, no
    other detail), so the frontend can render an honest "you have N of the
    2 you need" state rather than a guessing game. Same public-boolean-only
    pattern as GET /auth/locales."""
    methods = await mfa_service.enrolled_methods(db)
    secret_kind = await parent_recovery.recovery_secret_kind(db)
    available = int(secret_kind is not None) + ("totp" in methods) + ("webauthn" in methods)
    return {
        # "pin" | "code" | null — which shape of the "something you know"
        # factor is enrolled, if either (they're mutually exclusive).
        "recovery_secret": secret_kind,
        "totp": "totp" in methods,
        "webauthn": "webauthn" in methods,
        "recovery_possible": available >= _REQUIRED_FACTORS,
    }


@router.post("/webauthn/options")
async def recovery_webauthn_options(db: AsyncSession = Depends(get_db)):
    """Public — a locked-out parent has no session to gate this behind.
    Reuses mfa_service's own challenge/options plumbing unchanged; a
    recovery-flow WebAuthn ceremony is identical to a login one."""
    options = await mfa_service.build_authentication_options(db)
    if not options:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No security key is enrolled")
    return json.loads(options)


@router.post("/verify")
async def verify(req: RecoveryVerifyRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ctx = audit_from_request(request)

    verified_count = 0
    factors_used = []

    if req.recovery_secret:
        # Mutually exclusive by enrollment (services/parent_recovery.py),
        # so at most one of these two calls can ever actually match —
        # trying both means the client never needs to know which shape is
        # enrolled to submit the right field.
        if await parent_recovery.verify_recovery_pin(db, req.recovery_secret) or \
           await parent_recovery.verify_recovery_code(db, req.recovery_secret):
            verified_count += 1
            factors_used.append("recovery_secret")

    if req.totp_code:
        if await mfa_service.verify_totp_login(db, req.totp_code):
            verified_count += 1
            factors_used.append("totp")

    if req.webauthn_credential:
        if await mfa_service.verify_authentication(db, json.dumps(req.webauthn_credential)):
            verified_count += 1
            factors_used.append("webauthn")

    if verified_count < _REQUIRED_FACTORS:
        await log_event(
            AuditEvent.AUTH_FAILURE, role="parent", success=False,
            detail=f"recovery attempt: {verified_count}/{_REQUIRED_FACTORS} factors verified ({','.join(factors_used) or 'none'})",
            **ctx,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not verify at least {_REQUIRED_FACTORS} recovery factors — please try again",
        )

    await log_event(
        AuditEvent.AUTH_SUCCESS, role="parent", success=True,
        detail=f"account recovery succeeded via {','.join(factors_used)}",
        **ctx,
    )
    fp = compute_fingerprint(ctx["ip"], ctx["user_agent"])
    token = create_access_token(
        {"sub": "parent", "role": "parent_recovery"},
        fingerprint=fp,
        expires_delta=timedelta(minutes=_RECOVERY_TOKEN_EXPIRE_MINUTES),
    )
    return {"recovery_token": token}


@router.post("/reset-password")
async def reset_password(
    req: ChangePasswordRecoveryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_parent_recovery),
):
    if len(req.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"New password must be at least {MIN_PASSWORD_LENGTH} characters",
        )
    await set_parent_password_override(db, req.new_password)
    await log_event(
        AuditEvent.AUTH_SUCCESS, role="parent", success=True,
        detail="password reset via account recovery", **audit_from_request(request),
    )
    return {"success": True}
