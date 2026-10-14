"""Durable educator WebAuthn cryptographic ceremonies.

No password, TOTP, email token or campus SSO constitutes an authentication
assertion here. The calling HTTP route MUST separately authorize onboarding,
verify school affiliation and issue its JWT only after a true assertion.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import webauthn
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
    ResidentKeyRequirement, UserVerificationRequirement,
)

from core.config import settings
from core.database import ClassicalEducator, EducatorWebAuthnChallenge, EducatorWebAuthnCredential
from core.encryption import aad_for, decrypt_json, encrypt_json

CHALLENGE_LIFETIME = timedelta(minutes=5)


def _now():
    return datetime.now(timezone.utc)


def _origin_ready() -> bool:
    return bool(settings.webauthn_rp_id and settings.webauthn_origin
                and (settings.webauthn_origin.startswith("https://")
                     or settings.webauthn_origin.startswith("http://localhost")))


def _aad(credential_id: str) -> bytes:
    return aad_for("educator_webauthn_credentials", "credential_enc", credential_id)


async def _start(db: AsyncSession, educator_id: str, ceremony: str, challenge: bytes) -> str:
    if not _origin_ready():
        raise ValueError("Bede HTTPS WebAuthn origin and RP ID are required")
    identifier = str(uuid.uuid4())
    db.add(EducatorWebAuthnChallenge(
        id=identifier, educator_id=educator_id, ceremony=ceremony, challenge=challenge,
        expires_at=_now() + CHALLENGE_LIFETIME, consumed=False,
    ))
    await db.commit()
    return identifier


async def _consume(db: AsyncSession, educator_id: str, ceremony: str, identifier: str) -> bytes:
    # UPDATE compare-and-set provides single-use semantics even across concurrent
    # workers. Prevent a replay by consuming BEFORE expensive crypto validation.
    now = _now()
    result = await db.execute(
        update(EducatorWebAuthnChallenge)
        .where(EducatorWebAuthnChallenge.id == identifier)
        .where(EducatorWebAuthnChallenge.educator_id == educator_id)
        .where(EducatorWebAuthnChallenge.ceremony == ceremony)
        .where(EducatorWebAuthnChallenge.consumed.is_(False))
        .where(EducatorWebAuthnChallenge.expires_at > now)
        .values(consumed=True)
        .returning(EducatorWebAuthnChallenge.challenge)
    )
    challenge = result.scalar_one_or_none()
    await db.commit()
    if challenge is None:
        raise ValueError("Invalid, expired or already-used passkey challenge")
    return challenge


async def registration_options(db: AsyncSession, educator_id: str):
    account = await db.get(ClassicalEducator, educator_id)
    if account is None or not account.enabled:
        raise ValueError("Educator enrollment was not approved")
    rows = (await db.execute(
        select(EducatorWebAuthnCredential)
        .where(EducatorWebAuthnCredential.educator_id == educator_id)
        .where(EducatorWebAuthnCredential.enabled.is_(True))
    )).scalars().all()
    exclude = [PublicKeyCredentialDescriptor(id=webauthn.base64url_to_bytes(item.credential_id))
               for item in rows]
    options = webauthn.generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.webauthn_rp_name,
        user_name=account.username,
        user_id=uuid.UUID(educator_id).bytes,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=exclude,
    )
    ceremony_id = await _start(db, educator_id, "register", options.challenge)
    return {"ceremony_id": ceremony_id, "options": json.loads(webauthn.options_to_json(options))}


async def verify_registration(db: AsyncSession, educator_id: str,
                              ceremony_id: str, credential: dict) -> str:
    challenge = await _consume(db, educator_id, "register", ceremony_id)
    verified = webauthn.verify_registration_response(
        credential=credential,
        expected_challenge=challenge,
        expected_rp_id=settings.webauthn_rp_id,
        expected_origin=settings.webauthn_origin,
        require_user_verification=True,
    )
    credential_id = bytes_to_base64url(verified.credential_id)
    if await db.get(EducatorWebAuthnCredential, credential_id):
        raise ValueError("This passkey credential is already registered")
    record = {
        "public_key": bytes_to_base64url(verified.credential_public_key),
        "sign_count": verified.sign_count,
    }
    db.add(EducatorWebAuthnCredential(
        credential_id=credential_id,
        educator_id=educator_id,
        credential_enc=encrypt_json(record, _aad(credential_id)),
        enabled=True,
    ))
    await db.commit()
    return credential_id


async def authentication_options(db: AsyncSession, educator_id: str):
    account = await db.get(ClassicalEducator, educator_id)
    if account is None or not account.enabled or not _origin_ready():
        raise ValueError("Educator passkey sign-in is unavailable")
    rows = (await db.execute(
        select(EducatorWebAuthnCredential)
        .where(EducatorWebAuthnCredential.educator_id == educator_id)
        .where(EducatorWebAuthnCredential.enabled.is_(True))
    )).scalars().all()
    if not rows:
        raise ValueError("No active passkey for this educator")
    opts = webauthn.generate_authentication_options(
        rp_id=settings.webauthn_rp_id,
        allow_credentials=[PublicKeyCredentialDescriptor(
            id=webauthn.base64url_to_bytes(row.credential_id),
        ) for row in rows],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    ceremony_id = await _start(db, educator_id, "authenticate", opts.challenge)
    return {"ceremony_id": ceremony_id, "options": json.loads(webauthn.options_to_json(opts))}


async def verify_authentication(db: AsyncSession, educator_id: str,
                                ceremony_id: str, credential: dict) -> dict:
    challenge = await _consume(db, educator_id, "authenticate", ceremony_id)
    if not isinstance(credential, dict) or not isinstance(credential.get("rawId"), str):
        raise ValueError("Invalid passkey credential")
    credential_id = credential["rawId"]
    row = await db.get(EducatorWebAuthnCredential, credential_id, with_for_update=True)
    account = await db.get(ClassicalEducator, educator_id)
    if (row is None or not row.enabled or row.educator_id != educator_id
            or account is None or not account.enabled):
        raise ValueError("Passkey credential is revoked or unknown")
    material = decrypt_json(row.credential_enc, _aad(credential_id))
    verified = webauthn.verify_authentication_response(
        credential=credential,
        expected_challenge=challenge,
        expected_rp_id=settings.webauthn_rp_id,
        expected_origin=settings.webauthn_origin,
        credential_public_key=webauthn.base64url_to_bytes(material["public_key"]),
        credential_current_sign_count=material["sign_count"],
        require_user_verification=True,
    )
    if verified.credential_id != webauthn.base64url_to_bytes(credential_id):
        raise ValueError("Passkey identity mismatch")
    material["sign_count"] = verified.new_sign_count
    row.credential_enc = encrypt_json(material, _aad(credential_id))
    await db.commit()
    return {"role": "educator", "sub": account.id,
            "ev": account.credential_version, "auth_method": "webauthn_uv"}


async def revoke_credential(db: AsyncSession, educator_id: str, credential_id: str) -> bool:
    row = await db.get(EducatorWebAuthnCredential, credential_id)
    if row is None or row.educator_id != educator_id or not row.enabled:
        return False
    row.enabled = False
    account = await db.get(ClassicalEducator, educator_id)
    if account:
        account.credential_version += 1  # revoke currently issued sessions
    await db.commit()
    return True
