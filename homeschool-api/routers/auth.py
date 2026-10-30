import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError, BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core import child_throttle, device_registry, elevation, parent_lockout
from core.audit import AuditEvent, audit_from_request, log_event, log_event_nowait
from core.config import settings, SUPPORTED_LOCALES
from core.database import ChildDevicePairing, get_db
from core.demo_code_session import (
    end_session as end_code_session,
    generate_code,
    get_personalization as get_demo_personalization,
    redeem_code,
    set_parent_config,
)
from core.deps import require_auth, require_demo_parent_config, require_parent
from core.middleware import compute_fingerprint
from core.parent_credential import current_credentials_version, verify_parent_password
from core.security import create_access_token, decode_token, validate_fingerprint
from models.schemas import (
    DemoCodeRequest,
    DemoCodeResponse,
    DemoParentConfigRequest,
    ElevationRequest,
    ElevationResponse,
    LoginRequest,
    TokenResponse,
    SessionConfig,
    VALID_GRADES,
    grade_to_stage,
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


@router.post("/demo-code/config", status_code=status.HTTP_204_NO_CONTENT)
async def set_demo_parent_config(
    req: DemoParentConfigRequest,
    auth: dict = Depends(require_demo_parent_config),
):
    """
    The demo's own Parent Setup — a visitor configuring their own demo
    session the way a parent configures a real one (subjects, companion
    mode, what the family is already reading, what helps this child).
    Stored per demo code and read back by routers/tutor.py's
    _demo_session_config, so it shapes the prompt exactly as a real
    parent's own config does.

    **Validated by building a real SessionConfig, not by a second set of
    rules written here.** Every one of these fields belongs to
    SessionConfig, and its validators are what decide whether a
    configuration is acceptable: the subject list, the clean-never-reject
    caps on curriculum_resources/character_virtues/learning_support, the
    K-2 Logic gate. A demo that accepted something the product refuses
    would be demonstrating a product that does not exist, and a looser
    copy of those rules in this file is the exact "a fake looser than the
    real thing" failure this repository has shipped before. The
    SessionConfig that comes back is also what gets stored, so the values
    persisted are the CLEANED ones rather than what was sent.

    Free text is sanitized here as well as at prompt-build time. A real
    parent's fields meet _sanitize_parent_field once, inside
    _build_subject_prompt; this input arrives from an anonymous public
    visitor, so it meets it on the way in too — the same belt-and-braces
    already applied to current_unit and faith_tradition at
    POST /auth/demo-code.
    """
    if not settings.demo_pin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The free demo is not enabled on this deployment",
        )

    code = auth.get("code")
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This demo session has no code to configure",
        )

    text = {
        "lesson_focus": _sanitize_parent_field(req.lesson_focus, max_len=500),
        "faith_emphasis": _sanitize_parent_field(req.faith_emphasis, max_len=500),
        "current_unit": _sanitize_parent_field(req.current_unit, max_len=200),
        "faith_tradition": _sanitize_parent_field(req.faith_tradition, max_len=60),
    }
    lists = {
        field: [
            cleaned
            for item in (getattr(req, field) or [])
            if (cleaned := _sanitize_parent_field(item, max_len=80))
        ]
        for field in ("curriculum_resources", "character_virtues", "learning_support")
    }

    # The real thing, with the demo's own fixed identity fields filled in so
    # every validator that depends on them (the K-2 Logic gate reads
    # grade_stage) actually runs.
    student_name, grade = await get_demo_personalization(code)
    grade = grade or settings.demo_grade
    try:
        validated = SessionConfig(
            student_name=student_name or settings.demo_student_name,
            grade=grade,
            grade_stage=grade_to_stage(grade),
            **({"subjects": req.subjects} if req.subjects else {}),
            **({"companion_mode": req.companion_mode} if req.companion_mode else {}),
            **({"bible_translation": req.bible_translation} if req.bible_translation else {}),
            **text,
            **lists,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"That setup isn't valid: {exc.error_count()} problem(s)",
        ) from exc

    await set_parent_config(code, {
        "subjects": [s.value for s in validated.subjects],
        "companion_mode": validated.companion_mode.value,
        "lesson_focus": validated.lesson_focus,
        "faith_emphasis": validated.faith_emphasis,
        "current_unit": validated.current_unit,
        "faith_tradition": validated.faith_tradition,
        "bible_translation": validated.bible_translation,
        "curriculum_resources": validated.curriculum_resources,
        "character_virtues": validated.character_virtues,
        "learning_support": validated.learning_support,
    })


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


@router.get("/educator-mode")
async def educator_mode() -> dict:
    return {"enabled": bool(settings.educator_pilot_enabled and not settings.is_demo_deployment),
            "shared_child_pin_disabled": bool(settings.educator_pilot_enabled)}


class EducatorLoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=1, max_length=256)
    totp: str = Field(min_length=6, max_length=6)
    locale: str = "en"


@router.post("/educator-login", response_model=TokenResponse)
async def educator_login(
    req: EducatorLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Retired. Institution users can authenticate only with WebAuthn UV."""
    raise HTTPException(status_code=410, detail="Educator sign-in requires a verified passkey")


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

    def _reject_if_device_revoked(role: str) -> None:
        """P9 device revocation (core/device_registry.py). Called ONLY after
        this role's credential has already verified successfully — never
        before. An earlier version checked this first, reasoning that it
        would avoid burning a parent_lockout/child_throttle attempt on a
        login that was never going to succeed anyway. That reasoning was
        wrong: it made this endpoint a pre-authentication oracle, since a
        caller submitting the right device_id with ANY (or no valid)
        credential would learn whether that device is revoked without ever
        proving they hold it. Checking only after a genuinely correct
        password/PIN closes that — a wrong credential now always gets the
        same "Invalid credentials" response regardless of whether the
        device happens to be revoked, indistinguishable either way."""
        if not req.device_id or not device_registry.is_revoked(req.device_id):
            return
        log_event_nowait(
            AuditEvent.DEVICE_LOGIN_BLOCKED, role=role, success=False,
            detail="login refused — this device was revoked", **ctx,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This device's access was revoked — please contact the parent",
        )

    # Set only by the hosted child-device gate below; None everywhere else.
    child_device_token: Optional[str] = None

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
        _reject_if_device_revoked("parent")
        cv = current_credentials_version()

        # Password alone isn't enough once a security key or TOTP app is
        # enrolled — issue a short-lived "parent_pending" token that can only
        # be used to complete that second factor (see core/deps.py,
        # routers/mfa.py), not a real parent session.
        methods = await mfa_service.enrolled_methods(db)
        if not methods and settings.hosted_profile:
            # COPPA readiness C-22. A hosted deployment does not open a
            # parent session on a password alone. The refusal carries a
            # short-lived enrollment-only token ("parent_pending" with
            # enroll=True): core/deps.py grants it nothing but the MFA
            # enrollment routes (routers/mfa.py's require_enrollment_or_
            # elevated_parent), so a parent can comply with the refusal
            # without ever holding a session that reads family data.
            enrollment_token = create_access_token(
                {"sub": "parent", "role": "parent_pending", "locale": locale, "cv": cv, "enroll": True},
                fingerprint=fp,
                expires_delta=timedelta(minutes=settings.mfa_pending_token_expire_minutes),
            )
            log_event_nowait(
                AuditEvent.AUTH_FAILURE, role="parent", success=False,
                detail="password ok, refused: no second factor enrolled (hosted profile)", **ctx,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "mfa_enrollment_required",
                    "message": (
                        "This deployment requires a second sign-in factor. Set up a "
                        "security key or an authenticator app, then sign in again."
                    ),
                    "enrollment_token": enrollment_token,
                },
            )
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
        if settings.educator_pilot_enabled:
            raise HTTPException(status_code=403, detail="Classroom pilot requires an authorized educator")
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
        _reject_if_device_revoked("child")
        if settings.hosted_profile:
            # COPPA readiness C-23. Runs only after the PIN has verified, so
            # a caller without the PIN cannot use it to probe or to fill the
            # pending list (see _gate_child_device).
            child_device_token = await _gate_child_device(db, req, ctx)
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
    return TokenResponse(access_token=token, role=req.role, device_token=child_device_token)


def _device_token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _gate_child_device(db: AsyncSession, req: LoginRequest, ctx: dict) -> Optional[str]:
    """COPPA readiness C-23: child sign-in on a hosted deployment is accepted
    only from a device a parent has approved.

    Called after the PIN has verified (and after the throttle has recorded
    success), so an unauthenticated caller learns nothing and creates
    nothing. States, stored in ChildDevicePairing:

      (no row)   -> create `pending`, refuse (the tablet now appears in the
                    parent's list for approval)
      pending    -> refuse until a parent approves
      approved   -> issue a fresh per-device token ONCE, store only its
                    digest, move to `paired`, return the token for the
                    device to keep
      paired     -> require the token; refuse without it or with a mismatch
      revoked    -> refuse, token or not

    Returns the newly issued token on the single `approved` -> `paired`
    transition, otherwise None.
    """
    refusal = "This device is waiting for parent approval. Ask a parent to approve this tablet."
    if not req.device_id:
        log_event_nowait(AuditEvent.AUTH_FAILURE, role="child", success=False,
                         detail="device pairing: no device id", **ctx)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sign-in on this deployment requires a registered device. Ask a parent to approve this tablet.",
        )

    row = await db.get(ChildDevicePairing, req.device_id)
    if row is None:
        db.add(ChildDevicePairing(
            device_id=req.device_id,
            state="pending",
            user_agent=(ctx.get("user_agent") or "")[:256],
        ))
        try:
            await db.commit()
        except IntegrityError:
            # A concurrent first attempt from the same tablet created the row
            # already; that is still "pending", which is what we report.
            await db.rollback()
        log_event_nowait(AuditEvent.AUTH_FAILURE, role="child", success=False,
                         detail="device pairing: new device awaiting approval", **ctx)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=refusal)

    if row.state == "pending":
        log_event_nowait(AuditEvent.AUTH_FAILURE, role="child", success=False,
                         detail="device pairing: still awaiting approval", **ctx)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=refusal)

    if row.state == "revoked":
        log_event_nowait(AuditEvent.AUTH_FAILURE, role="child", success=False,
                         detail="device pairing: device revoked", **ctx)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This device was removed by a parent — please contact the parent.",
        )

    if row.state == "approved":
        token = secrets.token_urlsafe(32)
        # Conditional on state == approved, so two concurrent first sign-ins
        # cannot both receive a token: exactly one UPDATE matches.
        result = await db.execute(
            update(ChildDevicePairing)
            .where(ChildDevicePairing.device_id == req.device_id, ChildDevicePairing.state == "approved")
            .values(state="paired", token_hash=_device_token_digest(token),
                    decided_at=datetime.now(timezone.utc))
        )
        await db.commit()
        if result.rowcount != 1:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Please try signing in again.")
        log_event_nowait(AuditEvent.AUTH_SUCCESS, role="child", success=True,
                         detail="device paired: token issued once", **ctx)
        return token

    # state == "paired"
    if not req.device_token or not hmac.compare_digest(
        _device_token_digest(req.device_token), row.token_hash or "",
    ):
        log_event_nowait(AuditEvent.AUTH_FAILURE, role="child", success=False,
                         detail="device pairing: token missing or mismatched", **ctx)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This device is not paired. Ask a parent to approve it again.",
        )
    return None


@router.get("/child-devices")
async def list_child_devices(db: AsyncSession = Depends(get_db), _: dict = Depends(require_parent)):
    """Parent view of tablets that have tried to sign a child in on a hosted
    deployment. Never returns a token or a token digest."""
    rows = (await db.execute(select(ChildDevicePairing).order_by(ChildDevicePairing.requested_at))).scalars().all()
    return {
        "devices": [
            {
                "device_id": r.device_id,
                "state": r.state,
                "user_agent": r.user_agent,
                "requested_at": r.requested_at.isoformat() if r.requested_at else None,
                "decided_at": r.decided_at.isoformat() if r.decided_at else None,
            }
            for r in rows
        ]
    }


@router.post("/child-devices/{device_id}/approve")
async def approve_child_device(
    device_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_parent),
):
    row = await db.get(ChildDevicePairing, device_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")
    if row.state != "pending":
        raise HTTPException(status_code=409, detail="This device is not waiting for approval")
    row.state = "approved"
    row.decided_at = datetime.now(timezone.utc)
    await db.commit()
    log_event_nowait(AuditEvent.AUTH_SUCCESS, role="parent", success=True,
                     detail="child device approved", **audit_from_request(request))
    return {"approved": device_id}


@router.post("/child-devices/{device_id}/revoke")
async def revoke_child_device(
    device_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_parent),
):
    row = await db.get(ChildDevicePairing, device_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")
    row.state = "revoked"
    row.token_hash = None
    row.decided_at = datetime.now(timezone.utc)
    await db.commit()
    log_event_nowait(AuditEvent.DEVICE_REVOKED, role="parent", success=True,
                     detail="child device pairing revoked", **audit_from_request(request))
    return {"revoked": device_id}


@router.get("/validate")
async def validate_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
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

    if payload.get("role") == "child" and settings.educator_pilot_enabled:
        raise HTTPException(status_code=403, detail="Classroom pilot requires an authorized educator")
    if payload.get("role") == "educator":
        if not settings.educator_pilot_enabled:
            raise HTTPException(status_code=403, detail="Educator pilot not enabled")
        from services.educator_access import live_educator
        await live_educator(db, payload)
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
