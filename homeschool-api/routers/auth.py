from datetime import timedelta
from typing import Optional
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit import AuditEvent, audit_from_request, log_event
from core.config import settings
from core.database import get_db
from core.demo_code_session import end_session as end_code_session, generate_code, redeem_code
from core.deps import require_auth
from core.middleware import compute_fingerprint
from core.security import create_access_token, decode_token, validate_fingerprint
from models.schemas import DemoCodeRequest, DemoCodeResponse, LoginRequest, TokenResponse, VALID_GRADES
from services import mfa_service
from services.ai_service import _sanitize_parent_field

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()


def _looks_like_anthropic_key(value: str) -> bool:
    """Loose format check only — catches an obvious paste error (wrong
    field, truncated copy, a placeholder like "your-key-here") with an
    immediate, actionable error rather than silently dropping it (unlike
    grade, an invalid BYOK key isn't safe to just fall back from: the
    visitor explicitly asked for an unlimited session and deserves to know
    it didn't take). Real validity (revoked, wrong permissions, no credit)
    can only be confirmed by an actual API call, which stream_tutor_response
    already handles gracefully — see its anthropic.APIError handling."""
    v = value.strip()
    return v.startswith("sk-ant-") and 20 <= len(v) <= 200 and " " not in v


def _looks_like_openai_key(value: str) -> bool:
    """Same loose-format-only intent as _looks_like_anthropic_key, for a
    visitor's own OpenAI key instead — real OpenAI keys start "sk-" (legacy
    project keys are "sk-proj-", both match this prefix). Real validity is
    confirmed the same way: an actual API call, handled gracefully by
    _stream_tutor_events_openai's httpx.HTTPError handling."""
    v = value.strip()
    return v.startswith("sk-") and 20 <= len(v) <= 200 and " " not in v


@router.post("/demo-code", response_model=DemoCodeResponse)
async def create_demo_code(req: Optional[DemoCodeRequest] = None):
    """
    Mints a fresh, one-time 6-digit code with no credentials required — the
    sole way into the public demo. Gated on DEMO_PIN being set (the "is the
    public demo enabled at all" switch — see core/config.py), even though the
    code itself never touches DEMO_PIN's value. Exchange the returned code
    for a JWT via POST /auth/login (role="demo_code"). Lives under /auth/ so
    it inherits the existing per-IP auth rate limit (core/middleware.py)
    automatically. Each code is independent, so unlike the shared-PIN trial
    this once had, concurrent visitors never collide with each other.

    `req` is optional and every one of its fields is optional — an older
    client (or one that doesn't want to personalize) can still POST with no
    body at all, same as before. student_name is sanitized here (HTML/
    prompt-injection stripping, same as a parent's lesson_focus/
    faith_emphasis notes) since it's the one new piece of free text an
    anonymous visitor puts in front of the model; grade is checked against
    VALID_GRADES rather than sanitized, since anything outside that small
    allowlist is silently ignored (falls back to the operator's configured
    DEMO_GRADE) rather than trusted as text.

    byok_anthropic_key / byok_openai_key, if supplied, unlocks an uncapped
    session using the visitor's OWN Anthropic or OpenAI key instead of the
    operator's (see core/demo_code_session.py's generate_code docstring for
    the full ephemeral-handling contract) — format-checked here and rejected
    outright if it doesn't look like a real key, since silently falling back
    to a capped session would leave the visitor thinking they got what they
    asked for when they didn't. A visitor sets at most one of the two —
    the frontend only shows one BYOK field at a time.
    """
    if not settings.demo_pin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The free demo is not enabled on this deployment")

    student_name = _sanitize_parent_field(req.student_name if req else None, max_len=50)
    grade = req.grade.strip() if req and req.grade and req.grade.strip() in VALID_GRADES else None

    byok_anthropic_key = req.byok_anthropic_key.strip() if req and req.byok_anthropic_key else None
    if byok_anthropic_key and not _looks_like_anthropic_key(byok_anthropic_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That doesn't look like a valid Anthropic API key (should start with sk-ant-)",
        )

    byok_openai_key = req.byok_openai_key.strip() if req and req.byok_openai_key else None
    if byok_openai_key and not _looks_like_openai_key(byok_openai_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That doesn't look like a valid OpenAI API key (should start with sk-)",
        )

    code = generate_code(
        student_name=student_name,
        grade=grade,
        byok_anthropic_key=byok_anthropic_key,
        byok_openai_key=byok_openai_key,
    )
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
    if req.role == "demo_code":
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
    Explicit logout. For the demo_code role this immediately deletes the
    code server-side, so the token stops working right away instead of
    riding out its remaining expiry — a real "instant terminate," not just
    the client forgetting the token. Parent/child tokens are stateless JWTs
    with no server-side session to revoke, so this is a no-op for them beyond
    the audit log entry; the client is responsible for discarding the token.
    """
    ctx = audit_from_request(request)
    if auth.get("role") == "demo_code":
        end_code_session(auth.get("code", ""))
    await log_event(AuditEvent.AUTH_SUCCESS, role=auth.get("role"), success=True, detail="logout", **ctx)
    return {"success": True}
