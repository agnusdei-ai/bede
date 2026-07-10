from datetime import timedelta
import hmac
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit import AuditEvent, audit_from_request, log_event
from core.config import settings
from core.database import get_db
from core.demo_code_session import end_session as end_code_session, generate_code, redeem_code
from core.demo_session import end_session, start_new_session
from core.deps import require_auth
from core.middleware import compute_fingerprint
from core.security import create_access_token, decode_token, validate_fingerprint
from models.schemas import DemoCodeResponse, LoginRequest, TokenResponse
from services import mfa_service

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()


@router.post("/demo-code", response_model=DemoCodeResponse)
async def create_demo_code():
    """
    Self-service alternative to the shared DEMO_PIN trial: mints a fresh,
    one-time 6-digit code with no credentials required. Gated on DEMO_PIN
    being set — the same "is the public demo enabled at all" switch the
    shared trial already uses — even though the code itself never touches
    DEMO_PIN's value. Exchange the returned code for a JWT via POST
    /auth/login (role="demo_code"). Lives under /auth/ so it inherits the
    existing per-IP auth rate limit (core/middleware.py) automatically.
    """
    if not settings.demo_pin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The free demo is not enabled on this deployment")
    code = generate_code()
    if code is None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many demo sessions are active right now — please try again shortly",
        )
    return DemoCodeResponse(code=code)


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ctx = audit_from_request(request)
    fp = compute_fingerprint(ctx["ip"], ctx["user_agent"])

    if req.role == "parent":
        if not hmac.compare_digest(req.credential, settings.parent_password):
            await log_event(AuditEvent.AUTH_FAILURE, role="parent", success=False, **ctx)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

        # Password alone isn't enough once a security key or TOTP app is
        # enrolled — issue a short-lived "parent_pending" token that can only
        # be used to complete that second factor (see core/deps.py,
        # routers/mfa.py), not a real parent session.
        methods = await mfa_service.enrolled_methods(db)
        if methods:
            pending_token = create_access_token(
                {"sub": "parent", "role": "parent_pending"},
                fingerprint=fp,
                expires_delta=timedelta(minutes=settings.mfa_pending_token_expire_minutes),
            )
            await log_event(AuditEvent.AUTH_SUCCESS, role="parent", success=True, detail="password ok, mfa pending", **ctx)
            return TokenResponse(access_token=pending_token, role="parent_pending", mfa_required=True, mfa_methods=methods)

        expires = timedelta(minutes=settings.access_token_expire_minutes)
    elif req.role == "child":
        if not hmac.compare_digest(req.credential, settings.child_pin):
            await log_event(AuditEvent.AUTH_FAILURE, role="child", success=False, **ctx)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        expires = timedelta(minutes=settings.child_token_expire_minutes)
    elif req.role == "demo":
        # Disabled entirely unless a deployment has deliberately set DEMO_PIN —
        # an empty setting must never match an empty credential.
        if not settings.demo_pin or not hmac.compare_digest(req.credential, settings.demo_pin):
            await log_event(AuditEvent.AUTH_FAILURE, role="demo", success=False, **ctx)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        expires = timedelta(minutes=settings.demo_token_expire_minutes)
    elif req.role == "demo_code":
        # No static secret to compare against — the credential is a code
        # minted moments earlier by POST /auth/demo-code. redeem_code()
        # rejects an unknown or already-redeemed code, so the same code can
        # never be exchanged for two independent JWTs/quotas.
        if not settings.demo_pin or not redeem_code(req.credential):
            await log_event(AuditEvent.AUTH_FAILURE, role="demo_code", success=False, **ctx)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or already-used code")
        expires = timedelta(minutes=settings.demo_code_token_expire_minutes)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown role")

    token_data = {"sub": req.role, "role": req.role}
    if req.role == "demo":
        # The shared PIN is public by design — this makes each login unique in
        # the sense that matters: only the most recent one stays usable, so at
        # most one demo session can be active at a time regardless of how many
        # people know the PIN. See core/demo_session.py.
        jti = secrets.token_hex(16)
        start_new_session(jti)
        token_data["jti"] = jti
    elif req.role == "demo_code":
        # The code itself is the tracking key for message-quota enforcement
        # (core/demo_code_session.py) — no separate jti needed since each
        # code is already unique to whoever generated it.
        token_data["code"] = req.credential

    token = create_access_token(
        token_data,
        fingerprint=fp,
        expires_delta=expires,
    )
    await log_event(AuditEvent.AUTH_SUCCESS, role=req.role, success=True, **ctx)
    return TokenResponse(access_token=token, role=req.role)


@router.get("/validate")
async def validate_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Used by the frontend AppShell on every mount to confirm the token is still
    valid and the fingerprint still matches. Returns role only — no user data.
    """
    payload = decode_token(credentials.credentials)
    if not payload:
        await log_event(AuditEvent.TOKEN_INVALID, **audit_from_request(request), success=False)
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    ctx = audit_from_request(request)
    fp = compute_fingerprint(ctx["ip"], ctx["user_agent"])
    if not validate_fingerprint(payload, fp):
        await log_event(
            AuditEvent.TOKEN_FINGERPRINT_MISMATCH,
            role=payload.get("role"),
            success=False,
            **ctx,
        )
        raise HTTPException(status_code=401, detail="Session fingerprint mismatch — please log in again")

    return {"role": payload.get("role"), "valid": True}


@router.post("/logout")
async def logout(request: Request, auth: dict = Depends(require_auth)):
    """
    Explicit logout. For the demo role this immediately invalidates the
    session's jti server-side, so the token stops working right away instead
    of riding out its remaining expiry — a real "instant terminate," not just
    the client forgetting the token. Parent/child tokens are stateless JWTs
    with no server-side session to revoke, so this is a no-op for them beyond
    the audit log entry; the client is responsible for discarding the token.
    """
    ctx = audit_from_request(request)
    if auth.get("role") == "demo":
        end_session(auth.get("jti", ""))
    elif auth.get("role") == "demo_code":
        end_code_session(auth.get("code", ""))
    await log_event(AuditEvent.AUTH_SUCCESS, role=auth.get("role"), success=True, detail="logout", **ctx)
    return {"success": True}
