import asyncio
from datetime import timedelta
from typing import Optional
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from core import child_throttle, device_registry, elevation, parent_lockout
from core.audit import AuditEvent, audit_from_request, log_event, log_event_nowait
from core.config import settings, SUPPORTED_LOCALES
from core.database import get_db
from core.demo_code_session import end_session as end_code_session, generate_code, redeem_code
from core.deps import require_auth, require_parent
from core.middleware import compute_fingerprint
from core.parent_credential import current_credentials_version, verify_parent_password
from core.security import create_access_token, decode_token, validate_fingerprint
from models.schemas import (
    DemoCodeRequest,
    DemoCodeResponse,
    ElevationRequest,
    ElevationResponse,
    LoginRequest,
    TokenResponse,
    VALID_GRADES,
)
from services import mfa_service
from services.ai_service import _sanitize_parent_field

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()


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

    `req` is optional and all its fields are optional — an older client (or
    one that doesn't want to personalize) can still POST with no body at all,
    same as before. student_name and current_unit are sanitized here (HTML/
    prompt-injection stripping, same as a parent's lesson_focus/
    faith_emphasis notes) since they're free text an anonymous visitor puts
    in front of the model; grade is checked against VALID_GRADES rather than
    sanitized, since anything outside that small allowlist is silently
    ignored (falls back to the operator's configured DEMO_GRADE) rather than
    trusted as text.

    current_unit is the "what are we already covering at home" note behind
    the demo's Continuing Mastery card (see core/database.py's
    DemoCodeUnitNote and CLAUDE.md's "Continuing Mastery (demo)" section) —
    threaded into the demo's SessionConfig.current_unit exactly like a real
    parent's own field, so Bede can anchor on material the family brought in
    from outside the built-in curriculum.

    faith_tradition is the visiting family's own optional church-tradition
    label (e.g. "Baptist", "Catholic") — threaded into
    SessionConfig.faith_tradition the same way, so Bede can frame Scripture
    & Bible Study / Saints & Catechism content consistently with that
    tradition even though the demo shows both modules to every visitor
    (see core/database.py's DemoCodeFaithNote).
    """
    if not settings.demo_pin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The free demo is not enabled on this deployment")

    student_name = _sanitize_parent_field(req.student_name if req else None, max_len=50)
    grade = req.grade.strip() if req and req.grade and req.grade.strip() in VALID_GRADES else None
    current_unit = _sanitize_parent_field(req.current_unit if req else None, max_len=200)
    faith_tradition = _sanitize_parent_field(req.faith_tradition if req else None, max_len=60)

    code = await generate_code(
        student_name=student_name, grade=grade, current_unit=current_unit, faith_tradition=faith_tradition,
    )
    if code is None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many demo sessions are active right now — please try again shortly",
        )
    return DemoCodeResponse(code=code)


@router.get("/locales")
async def available_locales():
    """
    Public, unauthenticated — Login.tsx calls this before a token exists to
    decide whether to render the English/Español toggle at all. Returns only
    whether this deployment has opted into offering a non-English login
    choice (settings.locale — see core/config.py's updated docstring), never
    anything sensitive. An English-only deployment (the default) gets an
    empty list and never sees a toggle.
    """
    if settings.locale == "en":
        return {"locales": []}
    return {"locales": [{"code": settings.locale, "name": SUPPORTED_LOCALES[settings.locale]}]}


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    ctx = audit_from_request(request)
    fp = compute_fingerprint(ctx["ip"], ctx["user_agent"])

    # Chosen at the login screen itself — validated against whichever single
    # locale this deployment has opted into (settings.locale), same list
    # GET /auth/locales already advertised to render the toggle. Silently
    # falls back to "en" for anything else (an unknown code, or a deployment
    # that hasn't enabled a toggle at all) rather than rejecting the login
    # outright — a stale/tampered client value should never be able to block
    # someone from getting into their own session.
    locale = req.locale if req.locale == settings.locale else "en"

    # P9 device revocation (core/device_registry.py) — checked BEFORE any
    # credential verification, so a revoked device is refused outright
    # rather than burning a parent_lockout/child_throttle attempt on a
    # login that was never going to succeed regardless of the password/PIN.
    # demo_code never sends device_id (models/schemas.py's LoginRequest),
    # so this is a no-op for that role.
    if req.role in ("parent", "child") and req.device_id and device_registry.is_revoked(req.device_id):
        log_event_nowait(
            AuditEvent.DEVICE_LOGIN_BLOCKED, role=req.role, success=False,
            detail="login refused — this device was revoked", **ctx,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This device's access was revoked — please contact the parent",
        )

    if req.role == "parent":
        locked_until = await parent_lockout.check_locked(db)
        if locked_until is not None:
            log_event_nowait(AuditEvent.AUTH_FAILURE, role="parent", success=False, detail="locked out", **ctx)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "Too many incorrect attempts — locked until "
                    f"{locked_until.strftime('%H:%M UTC')}. Use account recovery if you've lost your password."
                ),
            )

        if not await verify_parent_password(db, req.credential):
            triggered = await parent_lockout.record_failure(db)
            log_event_nowait(AuditEvent.AUTH_FAILURE, role="parent", success=False, **ctx)
            if triggered is not None:
                await log_event(
                    AuditEvent.ACCESS_DENIED, role="parent", success=False,
                    detail=f"account locked until {triggered.isoformat()}", **ctx,
                )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        await parent_lockout.record_success(db)
        cv = current_credentials_version()

        # Password alone isn't enough once a security key or TOTP app is
        # enrolled — issue a short-lived "parent_pending" token that can only
        # be used to complete that second factor (see core/deps.py,
        # routers/mfa.py), not a real parent session.
        methods = await mfa_service.enrolled_methods(db)
        if methods:
            # locale (and, likewise, device_id) carries through the pending
            # token so the FINAL token (issued by routers/mfa.py once the
            # second factor completes) can re-embed it — the parent picked
            # their language once, and this device was already identified,
            # at this password step; MFA completing a moment later
            # shouldn't silently reset either.
            pending_payload = {"sub": "parent", "role": "parent_pending", "locale": locale, "cv": cv}
            if req.device_id:
                pending_payload["device_id"] = req.device_id
            pending_token = create_access_token(
                pending_payload,
                fingerprint=fp,
                expires_delta=timedelta(minutes=settings.mfa_pending_token_expire_minutes),
            )
            log_event_nowait(AuditEvent.AUTH_SUCCESS, role="parent", success=True, detail="password ok, mfa pending", **ctx)
            return TokenResponse(access_token=pending_token, role="parent_pending", mfa_required=True, mfa_methods=methods)

        expires = timedelta(minutes=settings.access_token_expire_minutes)
    elif req.role == "child":
        if not hmac.compare_digest(req.credential, settings.child_pin):
            # Escalating delay, not a lockout — see core/child_throttle.py
            # for why copying parent_lockout's fixed-threshold refusal here
            # would have closed a brute-force gap by opening an easier
            # availability one (any sibling who knows the threshold could
            # end a lesson before it starts). The first few failures cost
            # nothing, so a child mistyping their own PIN notices no
            # difference; sustained guessing gets expensive regardless of
            # how many source addresses it comes from, which is the gap the
            # per-IP rate limiter alone can't close on a LAN.
            delay = child_throttle.record_failure()
            if delay:
                await asyncio.sleep(delay)
            log_event_nowait(AuditEvent.AUTH_FAILURE, role="child", success=False, **ctx)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        child_throttle.record_success()
        expires = timedelta(minutes=settings.child_token_expire_minutes)
    elif req.role == "demo_code":
        # No static secret to compare against — the credential is a code
        # minted moments earlier by POST /auth/demo-code. redeem_code()
        # rejects an unknown or already-redeemed code, so the same code can
        # never be exchanged for two independent JWTs/quotas.
        if not settings.demo_pin or not await redeem_code(req.credential):
            log_event_nowait(AuditEvent.AUTH_FAILURE, role="demo_code", success=False, **ctx)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or already-used code")
        expires = timedelta(minutes=settings.demo_code_token_expire_minutes)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown role")

    token_data = {"sub": req.role, "role": req.role, "locale": locale}
    if req.role == "demo_code":
        # The code itself is the tracking key for message-quota enforcement
        # (core/demo_code_session.py) — no separate jti needed since each
        # code is already unique to whoever generated it.
        token_data["code"] = req.credential
    if req.role == "parent":
        # See core/deps.py's cv check — reached only for a parent with no
        # MFA enrolled (the MFA branch above already embedded cv on its own
        # pending token and returned early).
        token_data["cv"] = cv
    if req.role in ("parent", "child") and req.device_id:
        # touch() only runs at the point a REAL, usable token is issued —
        # never for the transient parent_pending token above, which isn't
        # a completed login yet. The MFA-required parent path instead
        # touches in routers/mfa.py's _issue_parent_token, the equivalent
        # point once the second factor completes.
        token_data["device_id"] = req.device_id
        await device_registry.touch(db, req.device_id, req.role, ctx["user_agent"])

    # demo_code tokens skip IP+UA fingerprint binding (parent/child keep it
    # unchanged). Real bug this fixes: a demo visitor's IP legitimately
    # changes mid-session on mobile (WiFi<->cellular handoff, carrier CGNAT
    # rotation) far more often than a real family's home network does —
    # the very next authenticated request (often the one a subject switch
    # fires) then failed validate_fingerprint's exact-hash comparison and
    # 401'd, which the frontend treats as "trial session ended," booting a
    # visitor who never actually left their device. The token's real
    # replay defense here is the one-time code redemption itself
    # (core/demo_code_session.py's redeem_code — a code can only ever be
    # exchanged for one JWT), plus the 2-hour token expiry and per-IP
    # quota (core/diagnostic_preview_quota.py) already in place; there's
    # no real family data behind this role for device-binding to protect,
    # unlike parent/child. validate_fingerprint's own "no fp claim ->
    # allow" branch (core/security.py) makes this a true no-op for every
    # other role.
    demo_fp = None if req.role == "demo_code" else fp
    token = create_access_token(
        token_data,
        fingerprint=demo_fp,
        expires_delta=expires,
    )
    log_event_nowait(AuditEvent.AUTH_SUCCESS, role=req.role, success=True, **ctx)
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
        log_event_nowait(AuditEvent.TOKEN_INVALID, **audit_from_request(request), success=False)
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    ctx = audit_from_request(request)
    fp = compute_fingerprint(ctx["ip"], ctx["user_agent"])
    if not validate_fingerprint(payload, fp):
        log_event_nowait(
            AuditEvent.TOKEN_FINGERPRINT_MISMATCH,
            role=payload.get("role"),
            success=False,
            **ctx,
        )
        raise HTTPException(status_code=401, detail="Session fingerprint mismatch — please log in again")

    return {"role": payload.get("role"), "valid": True}


@router.post("/elevate", response_model=ElevationResponse)
async def elevate(
    req: ElevationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_parent),
):
    """Step up to management-plane privilege for a short window (P8).

    Being logged in as the parent is the ordinary account identity. Reading
    the audit log, repointing the AI provider, changing an authentication
    factor, or permanently destroying a student's data additionally requires
    this — a recent, explicit, time-boxed re-authentication. See
    core/elevation.py for the reasoning and core/policy.py's
    _REQUIRES_ELEVATION for exactly which actions are covered.

    What it defends against is a *stolen session* rather than a stolen
    password: a token lifted from a tab left open on a shared device, or
    replayed by an XSS payload. None of those carry the password, and all of
    them are the realistic ones for a LAN appliance.

    SECOND FACTOR. A TOTP code is required when TOTP is enrolled. WebAuthn
    is deliberately NOT required here even when it is enrolled, and that is
    a real gap rather than a decision: verifying a security key needs a
    challenge/response round trip, so it needs its own endpoint pair the way
    login has. A WebAuthn-only deployment therefore elevates on the password
    alone — still strictly stronger than the nothing that came before, and
    tracked as the next step on P8.
    """
    ctx = audit_from_request(request)
    jti = auth.get("jti")

    if not jti:
        # A parent token issued before P8 existed. It has no session id to
        # key a grant to, so it cannot be elevated at all — and inventing
        # one here would key the grant to something the token doesn't
        # actually carry. Re-login mints a token that does.
        log_event_nowait(
            AuditEvent.ELEVATION_DENIED, role="parent", success=False,
            detail="token predates privileged access — no session id", **ctx,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please log in again before performing this action",
        )

    if not await verify_parent_password(db, req.password):
        # Shares parent_lockout with the login path deliberately: an
        # attacker holding a live session must not get an unthrottled
        # password oracle just because they are already authenticated.
        await parent_lockout.record_failure(db)
        log_event_nowait(
            AuditEvent.ELEVATION_DENIED, role="parent", success=False,
            detail="wrong password", **ctx,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Password is incorrect",
        )

    methods = await mfa_service.enrolled_methods(db)
    if "totp" in methods:
        if not req.totp_code or not await mfa_service.verify_totp_login(db, req.totp_code):
            log_event_nowait(
                AuditEvent.ELEVATION_DENIED, role="parent", success=False,
                detail="missing or invalid second factor", **ctx,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Enter the current code from your authenticator app",
            )

    await parent_lockout.record_success(db)
    expires = await elevation.grant(db, jti)
    log_event_nowait(
        AuditEvent.ELEVATION_GRANTED, role="parent", success=True,
        detail=f"privileged access for {settings.elevation_ttl_minutes} min", **ctx,
    )
    return ElevationResponse(
        elevated=True,
        expires_at=expires.isoformat(),
        ttl_seconds=settings.elevation_ttl_minutes * 60,
    )


@router.delete("/elevate")
async def drop_elevation(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_parent),
):
    """End privileged access early — "I'm done administering".

    Not required (the grant expires on its own) but the right thing to offer
    a parent stepping away from a shared machine, and cheap."""
    dropped = await elevation.drop(db, auth.get("jti"))
    if dropped:
        log_event_nowait(
            AuditEvent.ELEVATION_DROPPED, role="parent", success=True,
            **audit_from_request(request),
        )
    return {"elevated": False, "was_elevated": dropped}


@router.get("/elevate")
async def elevation_status(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(require_parent),
):
    """Whether this session currently holds privileged access, so the
    frontend can show the state rather than probing with a real action."""
    return {"elevated": await elevation.is_elevated(db, auth.get("jti"))}


@router.post("/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db), auth: dict = Depends(require_auth)):
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
        await end_code_session(auth.get("code", ""))
    # A parent token is a stateless JWT that stays valid until it expires,
    # so "logged out" is a client-side claim. The elevation is the one piece
    # of this session that IS server-side state, and leaving it behind would
    # mean a token recovered after logout came back still holding
    # management-plane privilege.
    if auth.get("role") == "parent":
        await elevation.drop(db, auth.get("jti"))
    log_event_nowait(AuditEvent.AUTH_SUCCESS, role=auth.get("role"), success=True, detail="logout", **ctx)
    return {"success": True}
