"""Bede-operator approved, school-mailbox-bound educator passkey invitations.

Reuses the already configured Bede email provider. If no institution domain,
verified sending provider, or strong admin session exists, fail closed.
No invitation bearer can ever issue a session or grant roster access.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from core.config import settings
from core.database import ClassicalEducator, EducatorPasskeyInvitation, EducatorWebAuthnCredential
from services.email_service import email_configured, send_email

INVITATION_TTL = timedelta(minutes=10)


def _normalize_email(email: str) -> str:
    address = email.strip().lower()
    domain = settings.educator_institution_email_domain.strip().lower().lstrip("@")
    approved_exact = {
        item.strip().lower()
        for item in settings.educator_bootstrap_emails.split(",")
        if item.strip()
    }
    valid_address = (
        address.count("@") == 1
        and len(address) <= 254
        and not any(ch.isspace() for ch in address)
    )
    school_domain = bool(domain) and address.endswith("@" + domain)
    if not valid_address or not (school_domain or address in approved_exact):
        raise ValueError("An explicitly approved organizational email address is required")
    return address

def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


async def issue_invitation(db, educator_id: str, email: str, *, recovery: bool = False) -> bool:
    """Send a one-time link only to the verified-school-domain mailbox.

    Calling routes must verify a recent Bede administrator passkey assertion,
    independent school affiliation and authorization to manage this educator.
    A delivered email never authenticates or signs in its recipient.
    """
    address = _normalize_email(email)
    if not email_configured() or not settings.webauthn_origin.startswith("https://"):
        raise ValueError("HTTPS WebAuthn and authenticated Bede email are required")
    account = await db.get(ClassicalEducator, educator_id)
    if not account or not account.enabled:
        raise ValueError("No approved active educator account")
    recipient_hash = _digest(address)
    if recovery:
        prior = (await db.execute(
            select(EducatorPasskeyInvitation.email_digest)
            .where(EducatorPasskeyInvitation.educator_id == educator_id)
            .order_by(EducatorPasskeyInvitation.expires_at.desc()).limit(1)
        )).scalar_one_or_none()
        if prior is None or not hmac.compare_digest(prior, recipient_hash):
            raise ValueError("Recovery requires the educator's previously verified school mailbox")
    token = secrets.token_urlsafe(32)
    ticket = EducatorPasskeyInvitation(
        id=str(uuid.uuid4()), educator_id=educator_id,
        email_digest=recipient_hash, token_digest=_digest(token),
        expires_at=datetime.now(timezone.utc) + INVITATION_TTL,
        used=False, recovery=recovery,
    )
    db.add(ticket)
    # We never hand the token to an administrator; it is delivered only to
    # the mailbox. A failure to send discards the invitation transaction.
    url = settings.webauthn_origin.rstrip("/") + "/educator-enroll#ticket=" + ticket.id + "&token=" + token
    body = ("<p>An authorized Bede school administrator requested a passkey "
            "enrollment or recovery.</p><p><a href='" + html.escape(url, quote=True) +
            "'>Enroll your passkey</a></p><p>This link expires after ten minutes. "
            "It cannot sign you in or grant access without a verified passkey.</p>")
    if not await send_email(address, "Bede educator passkey invitation", body):
        await db.rollback()
        return False
    await db.commit()
    return True


async def validate_invitation(db, ticket_id: str, token: str) -> EducatorPasskeyInvitation:
    if len(token) < 32:
        raise ValueError("Invalid invitation")
    ticket = await db.get(EducatorPasskeyInvitation, ticket_id)
    now = datetime.now(timezone.utc)
    if not ticket or ticket.used or not hmac.compare_digest(ticket.token_digest, _digest(token)):
        raise ValueError("Invalid invitation")
    expires = ticket.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= now:
        raise ValueError("Expired invitation")
    account = await db.get(ClassicalEducator, ticket.educator_id)
    if not account or not account.enabled:
        raise ValueError("Educator account revoked")
    return ticket


async def consume_invitation(db, ticket_id: str, token: str, educator_id: str) -> None:
    ticket = await validate_invitation(db, ticket_id, token)
    if ticket.educator_id != educator_id:
        raise ValueError("Wrong educator invitation")
    updated = await db.execute(
        update(EducatorPasskeyInvitation)
        .where(EducatorPasskeyInvitation.id == ticket_id)
        .where(EducatorPasskeyInvitation.used.is_(False))
        .values(used=True)
    )
    if updated.rowcount != 1:
        raise ValueError("Invitation was already used")
    if ticket.recovery:
        # Revoke every older authenticator AND all sessions when a lost
        # passkey is replaced; recovery never creates an admin session.
        credentials = (await db.execute(
            select(EducatorWebAuthnCredential)
            .where(EducatorWebAuthnCredential.educator_id == educator_id)
            .where(EducatorWebAuthnCredential.enabled.is_(True))
        )).scalars().all()
        for credential in credentials:
            credential.enabled = False
        account = await db.get(ClassicalEducator, educator_id)
        account.credential_version += 1
    await db.flush()
