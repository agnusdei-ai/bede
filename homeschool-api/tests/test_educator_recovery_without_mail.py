"""Lost-passkey recovery with no outbound mail configured (owner decision 2026-11-08).

The same decision as tests/test_educator_invite_without_mail.py, applied to
``POST /auth/educator-passkey/recovery/{educator_id}``: with no mail
configured the one-time recovery link is returned once, in the 202, to the
elevated administrator who issued it; with mail configured the response stays
``{"sent": true}`` and the link is only emailed.

Real HTTP against a real uvicorn server (tests/g1_harness.py); the teacher
first enrolls through the invite link with one real WebAuthn credential, then
recovers onto a second, so the recovery ticket's real side effects (old
passkeys disabled, sessions ended) are observed. Synthetic identities only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer

import httpx
import pytest
from sqlalchemy import select

from core.config import settings
from core.database import ClassicalEducator, EducatorPasskeyInvitation, EducatorWebAuthnCredential
from g1_harness import world  # noqa: F401 (fixture)
from test_educator_invite_without_mail import (
    BODY, INVITE, LINK, _Sink, _count, _enroll, _link_parts, _unconfigured,
)

EMAIL = {"institutional_email": BODY["institutional_email"]}


def _recovery(educator_id: str) -> str:
    return f"/auth/educator-passkey/recovery/{educator_id}"


def _enrolled_teacher(w) -> str:
    """Invite (no mail), enroll one real passkey, return the educator id."""
    r = w.client.post(INVITE, json=BODY, headers=w.admin())
    assert r.status_code == 202, r.text
    _, ticket, token = _link_parts(r)
    assert _enroll(w, ticket, token).status_code == 200

    async def find():
        async with w.factory() as s:
            return (await s.execute(select(ClassicalEducator.id).where(
                ClassicalEducator.username == BODY["username"]))).scalar_one()
    return w.run(find)


def _enabled_credentials(w, educator_id: str) -> int:
    return _count(w, EducatorWebAuthnCredential,
                  EducatorWebAuthnCredential.educator_id == educator_id,
                  EducatorWebAuthnCredential.enabled.is_(True))


def test_unconfigured_mail_returns_the_recovery_link_once_and_it_works_once(world, monkeypatch):
    w = world
    _unconfigured(monkeypatch)
    teacher = _enrolled_teacher(w)
    version = w.credential_version(teacher)
    r = w.client.post(_recovery(teacher), json=EMAIL, headers=w.admin())
    assert r.status_code == 202, r.text
    payload = r.json()
    assert payload["delivery"] == "shown_to_admin" and payload["sent"] is False
    assert payload["expires_in_minutes"] == 10
    assert "expires in 10 minutes" in payload["message"]
    assert "no-store" in r.headers.get("cache-control", "")
    _, ticket, token = _link_parts(r)

    first = _enroll(w, ticket, token)
    assert first.status_code == 200, first.text
    # The recovery ticket's own semantics: old passkey off, sessions ended.
    assert _enabled_credentials(w, teacher) == 1
    assert _count(w, EducatorWebAuthnCredential) == 2
    assert w.credential_version(teacher) == version + 1
    assert _enroll(w, ticket, token).status_code == 401
    assert _enabled_credentials(w, teacher) == 1


def test_an_expired_recovery_link_is_refused(world, monkeypatch):
    w = world
    _unconfigured(monkeypatch)
    teacher = _enrolled_teacher(w)
    r = w.client.post(_recovery(teacher), json=EMAIL, headers=w.admin())
    assert r.status_code == 202, r.text
    _, ticket, token = _link_parts(r)

    async def expire():
        async with w.factory() as s:
            t = await s.get(EducatorPasskeyInvitation, ticket)
            t.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await s.commit()
    w.run(expire)
    assert _enroll(w, ticket, token).status_code == 401
    assert _count(w, EducatorWebAuthnCredential) == 1


def test_the_recovery_link_never_reaches_logs_or_the_audit_trail(world, monkeypatch, caplog, capfd):
    w = world
    _unconfigured(monkeypatch)
    teacher = _enrolled_teacher(w)
    caplog.set_level(logging.DEBUG)
    capfd.readouterr()
    r = w.client.post(_recovery(teacher), json=EMAIL, headers=w.admin())
    assert r.status_code == 202, r.text
    url, ticket, token = _link_parts(r)
    _enroll(w, ticket, token)
    events = w.audit_events()
    issued = [e for e in events if e["event"] == "educator.passkey_recovery_issued"]
    assert len(issued) == 1
    assert issued[0]["detail"] == f"educator={teacher} delivery=shown_to_admin"
    captured = capfd.readouterr()
    for text in (caplog.text, captured.out, captured.err, json.dumps(events, default=str)):
        assert token not in text
        assert url not in text
        assert BODY["institutional_email"] not in text


def test_the_wrong_mailbox_gets_422_and_no_link(world, monkeypatch):
    w = world
    _unconfigured(monkeypatch)
    teacher = _enrolled_teacher(w)
    before = _count(w, EducatorPasskeyInvitation)
    r = w.client.post(_recovery(teacher),
                      json={"institutional_email": "synthetic.someone.else@qualification.agnusdei.ai"},
                      headers=w.admin())
    assert r.status_code == 422
    assert "educator-enroll" not in r.text
    assert _count(w, EducatorPasskeyInvitation) == before


@pytest.mark.parametrize("claims", [
    {"role": "parent", "auth_method": "password"},
    {"role": "educator", "auth_method": "webauthn_uv"},
    {"role": "child"},
])
def test_non_admin_callers_are_refused_and_get_no_recovery_link(world, monkeypatch, claims):
    from core.security import create_access_token
    w = world
    _unconfigured(monkeypatch)
    teacher = _enrolled_teacher(w)
    before = _count(w, EducatorPasskeyInvitation)
    token = create_access_token(dict(claims))
    r = w.client.post(_recovery(teacher), json=EMAIL, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code in (401, 403), r.text
    assert "educator-enroll" not in r.text
    assert _count(w, EducatorPasskeyInvitation) == before


def test_an_unelevated_admin_is_refused_and_gets_no_recovery_link(world, monkeypatch):
    w = world
    _unconfigured(monkeypatch)
    teacher = _enrolled_teacher(w)
    before = _count(w, EducatorPasskeyInvitation)
    monkeypatch.setattr(settings, "elevation_enforced", True)
    r = w.client.post(_recovery(teacher), json=EMAIL, headers=w.admin())
    assert r.status_code == 403, r.text
    assert r.json()["detail"].get("elevation_required") is True
    assert "educator-enroll" not in r.text
    assert _count(w, EducatorPasskeyInvitation) == before


def test_concurrent_recoveries_return_a_link_only_for_a_committed_ticket(world, monkeypatch):
    """Recovery has no unique index to lose on, so concurrent requests each
    get their own ticket, exactly as each would get its own email today.
    What must hold is that no response carries a link whose ticket was not
    committed first."""
    import services.educator_invites as invites
    w = world
    _unconfigured(monkeypatch)
    teacher = _enrolled_teacher(w)
    before = _count(w, EducatorPasskeyInvitation)
    real_add = invites._add_ticket

    async def slow_add(*args, **kwargs):
        staged = await real_add(*args, **kwargs)
        await asyncio.sleep(0.3)
        return staged
    monkeypatch.setattr(invites, "_add_ticket", slow_add)
    n = 3
    barrier = threading.Barrier(n)
    results: list = [None] * n
    base, headers = str(w.client.base_url), w.admin()

    def one(i: int) -> None:
        with httpx.Client(base_url=base, timeout=60) as c:
            barrier.wait()
            results[i] = c.post(_recovery(teacher), json=EMAIL, headers=headers)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=90)
    linked = [r for r in results if r.status_code == 202]
    for r in results:
        if r.status_code != 202:
            assert "educator-enroll" not in r.text
    assert _count(w, EducatorPasskeyInvitation) == before + len(linked)

    async def exists(ticket_id):
        async with w.factory() as s:
            return await s.get(EducatorPasskeyInvitation, ticket_id) is not None
    for r in linked:
        _, ticket, _ = _link_parts(r)
        assert w.run(exists, ticket)


def test_configured_mail_emails_the_recovery_link_and_never_returns_it(world, monkeypatch):
    import services.email_service as email_service
    w = world
    _unconfigured(monkeypatch)
    teacher = _enrolled_teacher(w)
    _Sink.messages = []
    sink = ThreadingHTTPServer(("127.0.0.1", 0), _Sink)
    threading.Thread(target=sink.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(settings, "resend_api_key", "synthetic-sink-key")
        monkeypatch.setattr(settings, "resend_from_address", "bede@qualification.agnusdei.ai")
        monkeypatch.setattr(settings, "resend_api_base_url", f"http://127.0.0.1:{sink.server_port}")
        monkeypatch.setattr(email_service, "_http_client", None)
        r = w.client.post(_recovery(teacher), json=EMAIL, headers=w.admin())
    finally:
        sink.shutdown()
    assert r.status_code == 202, r.text
    assert r.json() == {"sent": True}
    assert len(_Sink.messages) == 1
    assert _Sink.messages[0]["to"] == [BODY["institutional_email"]]
    assert LINK.search(_Sink.messages[0]["html"].replace("&amp;", "&"))
    issued = [e for e in w.audit_events() if e["event"] == "educator.passkey_recovery_issued"]
    assert len(issued) == 1 and issued[0]["detail"] == f"educator={teacher} delivery=email"


def test_a_recovery_whose_commit_fails_never_returns_a_link(monkeypatch):
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from core.database import Base
    from core.encryption import initialize_encryption
    from routers import educator_passkeys as routes
    from services.educator_access import provision_educator
    from services.educator_invites import issue_invitation_for_admin

    _unconfigured(monkeypatch)
    monkeypatch.setattr(settings, "educator_pilot_enabled", True)
    monkeypatch.setattr(settings, "demo_pin", "")

    async def go():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                     connect_args={"check_same_thread": False})
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            await initialize_encryption(settings.master_secret, db)
            teacher = await provision_educator(db, BODY["username"], "synthetic-passphrase-strong-one")
            await issue_invitation_for_admin(db, teacher["id"], BODY["institutional_email"])

            async def failing_commit():
                raise OperationalError("COMMIT", {}, Exception("lost"))
            monkeypatch.setattr(db, "commit", failing_commit)
            try:
                result = await routes.recover_educator(
                    teacher["id"], routes.RecoveryRequest(**EMAIL),
                    admin={"role": "parent", "auth_method": "webauthn_uv"}, db=db)
            except Exception as exc:  # anything but a link
                result = exc
        await engine.dispose()
        return result

    outcome = asyncio.run(go())
    assert not isinstance(outcome, dict), outcome
