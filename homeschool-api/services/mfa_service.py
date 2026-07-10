"""
Parent MFA — FIDO2/WebAuthn security keys (YubiKey, etc.) and TOTP.

Single-family app: there is exactly one parent identity, so credentials and
the TOTP secret all belong to "the parent" with no user id needed, same as
parent_password itself. This module owns the WebAuthn ceremony plumbing, TOTP
enrollment/verification, and DB access; routers/mfa.py and routers/auth.py
stay focused on HTTP concerns.
"""

import json

import pyotp
import webauthn
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import ParentSecurityKey, ParentTotpConfig
from core.encryption import decrypt_json, encrypt_json
from core.mfa_challenge import (
    mark_totp_step_used,
    pop_authenticate_challenge,
    pop_register_challenge,
    totp_step_already_used,
)

base64url_to_bytes = webauthn.base64url_to_bytes


def webauthn_enabled() -> bool:
    return bool(settings.webauthn_rp_id and settings.webauthn_origin)


# ── Enrollment status ────────────────────────────────────────────────────────

async def list_security_keys(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(ParentSecurityKey).order_by(ParentSecurityKey.created_at))
    return [
        {"id": row.id, "nickname": row.nickname, "created_at": row.created_at.isoformat()}
        for row in result.scalars().all()
    ]


async def get_totp_config(db: AsyncSession) -> ParentTotpConfig | None:
    result = await db.execute(select(ParentTotpConfig).where(ParentTotpConfig.key == "totp"))
    return result.scalar_one_or_none()


async def enrolled_methods(db: AsyncSession) -> list[str]:
    """Which second factors are actually usable right now — an unconfirmed
    TOTP enrollment-in-progress doesn't count."""
    methods = []
    result = await db.execute(select(ParentSecurityKey.id).limit(1))
    if result.first() is not None:
        methods.append("webauthn")
    totp = await get_totp_config(db)
    if totp is not None and totp.confirmed:
        methods.append("totp")
    return methods


# ── WebAuthn: registration (enrolling a new key) ─────────────────────────────

async def build_registration_options(db: AsyncSession) -> str:
    if not webauthn_enabled():
        raise ValueError("WEBAUTHN_RP_ID / WEBAUTHN_ORIGIN are not configured on this deployment")

    existing = await db.execute(select(ParentSecurityKey.credential_enc))
    exclude = []
    for (blob,) in existing.all():
        cred = decrypt_json(blob)
        exclude.append(PublicKeyCredentialDescriptor(id=base64url_to_bytes(cred["credential_id"])))

    options = webauthn.generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.webauthn_rp_name,
        user_name="parent",
        user_display_name="Parent",
        exclude_credentials=exclude,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.DISCOURAGED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    from core.mfa_challenge import set_register_challenge
    set_register_challenge(options.challenge)
    return webauthn.options_to_json(options)


async def verify_and_store_registration(db: AsyncSession, credential_json: str, nickname: str) -> None:
    challenge = pop_register_challenge()
    if not challenge:
        raise ValueError("Registration expired — please try adding the key again")

    verification = webauthn.verify_registration_response(
        credential=credential_json,
        expected_challenge=challenge,
        expected_rp_id=settings.webauthn_rp_id,
        expected_origin=settings.webauthn_origin,
    )
    record = {
        "credential_id": bytes_to_base64url(verification.credential_id),
        "public_key": bytes_to_base64url(verification.credential_public_key),
        "sign_count": verification.sign_count,
    }
    db.add(ParentSecurityKey(
        nickname=nickname.strip() or "Security key",
        credential_enc=encrypt_json(record),
    ))
    await db.commit()


async def delete_security_key(db: AsyncSession, key_id: int) -> bool:
    result = await db.execute(delete(ParentSecurityKey).where(ParentSecurityKey.id == key_id))
    await db.commit()
    return result.rowcount > 0


# ── WebAuthn: authentication (using a key to finish login) ──────────────────

async def build_authentication_options(db: AsyncSession) -> str | None:
    if not webauthn_enabled():
        return None
    result = await db.execute(select(ParentSecurityKey.credential_enc))
    rows = result.all()
    if not rows:
        return None

    allow = [
        PublicKeyCredentialDescriptor(id=base64url_to_bytes(decrypt_json(blob)["credential_id"]))
        for (blob,) in rows
    ]
    options = webauthn.generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        allow_credentials=allow,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    from core.mfa_challenge import set_authenticate_challenge
    set_authenticate_challenge(options.challenge)
    return webauthn.options_to_json(options)


async def verify_authentication(db: AsyncSession, credential_json: str) -> bool:
    challenge = pop_authenticate_challenge()
    if not challenge:
        return False

    try:
        parsed = json.loads(credential_json) if isinstance(credential_json, str) else credential_json
        raw_id = parsed["rawId"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return False

    result = await db.execute(select(ParentSecurityKey))
    target_row = None
    target_cred = None
    for row in result.scalars().all():
        cred = decrypt_json(row.credential_enc)
        if cred["credential_id"] == raw_id:
            target_row, target_cred = row, cred
            break
    if target_row is None:
        return False

    try:
        verification = webauthn.verify_authentication_response(
            credential=credential_json,
            expected_challenge=challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.webauthn_origin,
            credential_public_key=base64url_to_bytes(target_cred["public_key"]),
            credential_current_sign_count=target_cred["sign_count"],
        )
    except Exception:
        return False

    target_cred["sign_count"] = verification.new_sign_count
    target_row.credential_enc = encrypt_json(target_cred)
    await db.commit()
    return True


# ── TOTP ─────────────────────────────────────────────────────────────────────

async def enroll_totp(db: AsyncSession) -> tuple[str, str]:
    """Generates and stores a new (unconfirmed) secret. Returns
    (secret_base32, otpauth_uri) for the parent to add to their authenticator
    app — the secret is shown exactly once, at this call."""
    secret = pyotp.random_base32()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name="parent", issuer_name=settings.totp_issuer)

    existing = await get_totp_config(db)
    if existing:
        existing.secret_enc = encrypt_json({"secret": secret})
        existing.confirmed = False
    else:
        db.add(ParentTotpConfig(key="totp", secret_enc=encrypt_json({"secret": secret}), confirmed=False))
    await db.commit()
    return secret, uri


async def confirm_totp(db: AsyncSession, code: str) -> bool:
    """Verifies the parent's first code against the pending secret, then
    marks it confirmed — TOTP isn't usable as a login factor until this
    succeeds, so an abandoned enrollment can't weaken login."""
    config = await get_totp_config(db)
    if not config:
        return False
    secret = decrypt_json(config.secret_enc)["secret"]
    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        return False
    config.confirmed = True
    await db.commit()
    return True


async def verify_totp_login(db: AsyncSession, code: str) -> bool:
    config = await get_totp_config(db)
    if not config or not config.confirmed:
        return False
    secret = decrypt_json(config.secret_enc)["secret"]
    totp = pyotp.TOTP(secret)
    step = int(totp.timecode(__import__("datetime").datetime.now()))
    if totp_step_already_used(step):
        return False
    if not totp.verify(code, valid_window=1):
        return False
    mark_totp_step_used(step)
    return True


async def disable_totp(db: AsyncSession) -> bool:
    result = await db.execute(delete(ParentTotpConfig).where(ParentTotpConfig.key == "totp"))
    await db.commit()
    return result.rowcount > 0
