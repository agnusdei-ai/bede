"""Persisted real-WebAuthn ceremony controls using synthetic educators.

Cryptographic signature parsing is provided by pinned py_webauthn; hardware
Safari/Windows/Linux journeys remain an owner-run release acceptance gate.
"""
import re
from datetime import timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, EducatorWebAuthnChallenge, EducatorWebAuthnCredential
from core.encryption import initialize_encryption
from services import educator_passkey_runtime as runtime
from services import educator_invites as invites
from services.educator_access import provision_educator

PASSWORD = "temporary-synthetic-only-long-educator-secret"


@pytest_asyncio.fixture
async def db(monkeypatch):
    monkeypatch.setattr(settings, "webauthn_rp_id", "bede.example.org")
    monkeypatch.setattr(settings, "webauthn_origin", "https://bede.example.org")
    monkeypatch.setattr(settings, "educator_institution_email_domain", "example.edu")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:",
                                 poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await initialize_encryption(settings.master_secret, session)
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_uv_discoverable_passkey_registration_challenge_one_use(db):
    educator = await provision_educator(db, "mentor.alpha", PASSWORD)
    opts = await runtime.registration_options(db, educator["id"])
    assert opts["options"]["authenticatorSelection"]["userVerification"] == "required"
    assert opts["options"]["authenticatorSelection"]["residentKey"] == "required"
    challenge = await runtime._consume(db, educator["id"], "register", opts["ceremony_id"])
    assert len(challenge) >= 16
    with pytest.raises(ValueError, match="already-used"):
        await runtime._consume(db, educator["id"], "register", opts["ceremony_id"])


@pytest.mark.asyncio
async def test_cross_educator_challenge_cannot_be_consumed(db):
    a = await provision_educator(db, "mentor.alpha", PASSWORD)
    b = await provision_educator(db, "mentor.bravo", PASSWORD)
    opts = await runtime.registration_options(db, a["id"])
    with pytest.raises(ValueError):
        await runtime._consume(db, b["id"], "register", opts["ceremony_id"])
    assert await runtime._consume(db, a["id"], "register", opts["ceremony_id"])


@pytest.mark.asyncio
async def test_expired_challenge_and_wrong_ceremony_fail_closed(db):
    a = await provision_educator(db, "mentor.alpha", PASSWORD)
    opts = await runtime.registration_options(db, a["id"])
    with pytest.raises(ValueError):
        await runtime._consume(db, a["id"], "authenticate", opts["ceremony_id"])
    row = await db.get(EducatorWebAuthnChallenge, opts["ceremony_id"])
    row.expires_at = runtime._now() - timedelta(minutes=1)
    await db.commit()
    with pytest.raises(ValueError):
        await runtime._consume(db, a["id"], "register", opts["ceremony_id"])


@pytest.mark.asyncio
async def test_unapproved_mailbox_and_unconfigured_mail_denied(db, monkeypatch):
    a = await provision_educator(db, "mentor.alpha", PASSWORD)
    with pytest.raises(ValueError):
        await invites.issue_invitation(db, a["id"], "outside@example.net")
    monkeypatch.setattr(invites, "email_configured", lambda: False)
    with pytest.raises(ValueError):
        await invites.issue_invitation(db, a["id"], "mentor@example.edu")


@pytest.mark.asyncio
async def test_delivered_one_time_school_mailbox_invitation(db, monkeypatch):
    a = await provision_educator(db, "mentor.alpha", PASSWORD)
    delivered = []
    async def fake_send(address, subject, body):
        delivered.append((address, subject, body))
        return True
    monkeypatch.setattr(invites, "email_configured", lambda: True)
    monkeypatch.setattr(invites, "send_email", fake_send)
    assert await invites.issue_invitation(db, a["id"], "mentor@example.edu")
    assert delivered[0][0] == "mentor@example.edu"
    assert "#ticket=" in delivered[0][2]   # token never travels in HTTP URL request
    m = re.search(r"ticket=([a-f0-9-]{36})&amp;token=([A-Za-z0-9_-]+)", delivered[0][2])
    assert m
    ticket, token = m.groups()
    invitation = await invites.validate_invitation(db, ticket, token)
    assert invitation.educator_id == a["id"]
    with pytest.raises(ValueError):
        await invites.validate_invitation(db, ticket, "invalid" * 12)
    await invites.consume_invitation(db, ticket, token, a["id"])
    await db.commit()
    with pytest.raises(ValueError):
        await invites.validate_invitation(db, ticket, token)


@pytest.mark.asyncio
async def test_school_mailbox_cannot_migrate_on_recovery(db, monkeypatch):
    a = await provision_educator(db, "mentor.alpha", PASSWORD)
    async def fake_send(*args):
        return True
    monkeypatch.setattr(invites, "email_configured", lambda: True)
    monkeypatch.setattr(invites, "send_email", fake_send)
    assert await invites.issue_invitation(db, a["id"], "mentor@example.edu")
    with pytest.raises(ValueError, match="previously verified"):
        await invites.issue_invitation(db, a["id"], "other@example.edu", recovery=True)


@pytest.mark.asyncio
async def test_key_revocation_invalidates_current_session_version(db):
    a = await provision_educator(db, "mentor.alpha", PASSWORD)
    row = EducatorWebAuthnCredential(
        credential_id="synthetic-credential", educator_id=a["id"],
        credential_enc=b"synthetic-non-secret", enabled=True,
    )
    db.add(row)
    await db.commit()
    assert await runtime.revoke_credential(db, a["id"], row.credential_id)
    assert not row.enabled
    assert not await runtime.revoke_credential(db, a["id"], row.credential_id)
