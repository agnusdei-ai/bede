"""Teacher enrollment with no outbound mail configured (owner decision 2026-11-08).

A campus install with no RESEND_API_KEY used to answer the admin's invite with
503, so a teacher could not be enrolled without a third-party mail secret. Now
the one-time link is returned once, in the 202, to the elevated administrator
who issued it, to hand over in person. With mail configured nothing changes:
the link is emailed and never returned.

Driven over real HTTP against a real uvicorn server (tests/g1_harness.py). The
enrollment itself is a real WebAuthn registration: a synthetic software
authenticator below builds a genuine "none" attestation that py_webauthn
verifies, so the ticket is consumed by the real ceremony and not by a stub.
The "configured" case drives the real email_configured() condition and the
real send_email() against a loopback mail sink. Synthetic identities only.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import struct
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import cbor2
import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import func, select

from core.config import settings
from core.database import ClassicalEducator, EducatorPasskeyInvitation, EducatorWebAuthnCredential
from g1_harness import world  # noqa: F401 (fixture)

ORIGIN = "https://qualification.agnusdei.ai"
RP_ID = "qualification.agnusdei.ai"
BODY = {"username": "synthetic.teacher.handover",
        "institutional_email": "synthetic.teacher.handover@qualification.agnusdei.ai"}
INVITE = "/auth/educator-passkey/invite"
LINK = re.compile(r"/educator-enroll#ticket=([0-9a-f-]{36})&token=([A-Za-z0-9_-]{32,})")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _attestation(options: dict) -> dict:
    """A real, verifiable 'none' attestation from a throwaway P-256 key."""
    key = ec.generate_private_key(ec.SECP256R1())
    numbers = key.public_key().public_numbers()
    cose = cbor2.dumps({1: 2, 3: -7, -1: 1,
                        -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})
    cred_id = hashlib.sha256(cose).digest()
    auth_data = (hashlib.sha256(RP_ID.encode()).digest() + bytes([0x01 | 0x04 | 0x40])
                 + struct.pack(">I", 0) + bytes(16) + struct.pack(">H", len(cred_id))
                 + cred_id + cose)
    client_data = json.dumps({"type": "webauthn.create", "challenge": options["challenge"],
                              "origin": ORIGIN, "crossOrigin": False}).encode()
    return {"id": _b64(cred_id), "rawId": _b64(cred_id), "type": "public-key",
            "response": {"clientDataJSON": _b64(client_data),
                         "attestationObject": _b64(cbor2.dumps(
                             {"fmt": "none", "attStmt": {}, "authData": auth_data}))}}


def _enroll(w, ticket: str, token: str) -> httpx.Response:
    """The real register/options + register/verify ceremony for one link."""
    req = {"ticket_id": ticket, "ticket_token": token}
    opts = w.client.post("/auth/educator-passkey/register/options", json=req)
    if opts.status_code != 200:
        return opts
    body = opts.json()
    return w.client.post("/auth/educator-passkey/register/verify", json={
        **req, "ceremony_id": body["ceremony_id"], "credential": _attestation(body["options"]),
    })


def _unconfigured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "webauthn_origin", ORIGIN)
    monkeypatch.setattr(settings, "webauthn_rp_id", RP_ID)
    monkeypatch.setattr(settings, "educator_institution_email_domain", RP_ID)
    # The real condition, not a stubbed email_configured(): no Resend key.
    monkeypatch.setattr(settings, "resend_api_key", "")
    monkeypatch.setattr(settings, "resend_api_base_url", "")


def _count(w, model, *where) -> int:
    async def go():
        async with w.factory() as s:
            q = select(func.count()).select_from(model)
            for clause in where:
                q = q.where(clause)
            return (await s.execute(q)).scalar_one()
    return w.run(go)


def _link_parts(response: httpx.Response) -> tuple[str, str, str]:
    url = response.json()["enrollment_url"]
    m = LINK.search(url)
    assert m and url.startswith(ORIGIN + "/educator-enroll#"), url
    return url, m.group(1), m.group(2)


# ── mail not configured: the link is shown once to the admin ──────────────

def test_unconfigured_mail_returns_the_link_once_and_it_enrolls_exactly_once(world, monkeypatch):
    w = world
    _unconfigured(monkeypatch)
    r = w.client.post(INVITE, json=BODY, headers=w.admin())
    assert r.status_code == 202, r.text
    payload = r.json()
    assert payload["delivery"] == "shown_to_admin" and payload["sent"] is False
    assert payload["expires_in_minutes"] == 10
    assert "expires in 10 minutes" in payload["message"]
    assert "no-store" in r.headers.get("cache-control", "")
    url, ticket, token = _link_parts(r)

    # Stored exactly as an emailed ticket: digests, never the token.
    async def row():
        async with w.factory() as s:
            return await s.get(EducatorPasskeyInvitation, ticket)
    stored = w.run(row)
    assert stored.token_digest == hashlib.sha256(token.encode()).digest()
    assert token.encode() not in stored.token_digest

    first = _enroll(w, ticket, token)
    assert first.status_code == 200, first.text
    assert _count(w, EducatorWebAuthnCredential) == 1
    second = _enroll(w, ticket, token)
    assert second.status_code == 401
    assert _count(w, EducatorWebAuthnCredential) == 1


def test_an_expired_shown_link_is_refused(world, monkeypatch):
    w = world
    _unconfigured(monkeypatch)
    r = w.client.post(INVITE, json=BODY, headers=w.admin())
    assert r.status_code == 202, r.text
    _, ticket, token = _link_parts(r)

    async def expire():
        async with w.factory() as s:
            t = await s.get(EducatorPasskeyInvitation, ticket)
            t.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await s.commit()
    w.run(expire)
    assert _enroll(w, ticket, token).status_code == 401
    assert _count(w, EducatorWebAuthnCredential) == 0


def test_the_link_never_reaches_logs_or_the_audit_trail(world, monkeypatch, caplog, capfd):
    w = world
    _unconfigured(monkeypatch)
    caplog.set_level(logging.DEBUG)
    r = w.client.post(INVITE, json=BODY, headers=w.admin())
    assert r.status_code == 202, r.text
    url, ticket, token = _link_parts(r)
    _enroll(w, ticket, token)
    events = w.audit_events()
    invited = [e for e in events if e["event"] == "educator.passkey_invited"]
    assert len(invited) == 1 and "delivery=shown_to_admin" in invited[0]["detail"]
    captured = capfd.readouterr()
    haystacks = [caplog.text, captured.out, captured.err, json.dumps(events, default=str)]
    for text in haystacks:
        assert token not in text
        assert url not in text
        assert BODY["institutional_email"] not in text


@pytest.mark.parametrize("claims", [
    {"role": "parent", "auth_method": "password"},   # not a fresh passkey session
    {"role": "educator", "auth_method": "webauthn_uv"},
    {"role": "child"},
])
def test_non_admin_callers_are_still_refused_and_get_no_link(world, monkeypatch, claims):
    from core.security import create_access_token
    w = world
    _unconfigured(monkeypatch)
    token = create_access_token(dict(claims))
    r = w.client.post(INVITE, json=BODY, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code in (401, 403), r.text
    assert "enrollment_url" not in r.text and "educator-enroll" not in r.text
    assert _count(w, EducatorPasskeyInvitation) == 0


def test_an_unelevated_admin_is_still_refused_and_gets_no_link(world, monkeypatch):
    w = world
    _unconfigured(monkeypatch)
    monkeypatch.setattr(settings, "elevation_enforced", True)
    r = w.client.post(INVITE, json=BODY, headers=w.admin())
    assert r.status_code == 403, r.text
    assert r.json()["detail"].get("elevation_required") is True
    assert "educator-enroll" not in r.text
    assert _count(w, EducatorPasskeyInvitation) == 0


def test_concurrent_duplicates_without_mail_give_one_link(world, monkeypatch):
    import asyncio

    import services.educator_invites as invites
    w = world
    _unconfigured(monkeypatch)
    real_add = invites._add_ticket

    async def slow_add(*args, **kwargs):
        staged = await real_add(*args, **kwargs)
        await asyncio.sleep(0.5)  # the winner's transaction stays open meanwhile
        return staged
    monkeypatch.setattr(invites, "_add_ticket", slow_add)
    n = 3
    barrier = threading.Barrier(n)
    results: list = [None] * n
    base, headers = str(w.client.base_url), w.admin()

    def one(i: int) -> None:
        with httpx.Client(base_url=base, timeout=60) as c:
            barrier.wait()
            results[i] = c.post(INVITE, json=BODY, headers=headers)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=90)
    codes = sorted(r.status_code for r in results)
    assert codes == [202] + [422] * (n - 1), [r.text for r in results]
    for r in results:
        if r.status_code == 422:
            assert "enrollment_url" not in r.text and "educator-enroll" not in r.text
    assert _count(w, ClassicalEducator, ClassicalEducator.username == BODY["username"]) == 1
    assert _count(w, EducatorPasskeyInvitation) == 1


# ── mail configured: unchanged, the link is emailed and never returned ────

class _Sink(BaseHTTPRequestHandler):
    messages: list = []

    def log_message(self, *args):
        pass

    def do_POST(self):  # noqa: N802
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        type(self).messages.append(json.loads(raw))
        data = b'{"id": "synthetic"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_configured_mail_emails_the_link_and_never_returns_it(world, monkeypatch):
    import services.email_service as email_service
    w = world
    _unconfigured(monkeypatch)
    _Sink.messages = []
    sink = ThreadingHTTPServer(("127.0.0.1", 0), _Sink)
    threading.Thread(target=sink.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(settings, "resend_api_key", "synthetic-sink-key")
        monkeypatch.setattr(settings, "resend_from_address", "bede@qualification.agnusdei.ai")
        monkeypatch.setattr(settings, "resend_api_base_url", f"http://127.0.0.1:{sink.server_port}")
        monkeypatch.setattr(email_service, "_http_client", None)
        r = w.client.post(INVITE, json=BODY, headers=w.admin())
    finally:
        sink.shutdown()
    assert r.status_code == 202, r.text
    assert r.json() == {"sent": True, "username": BODY["username"],
                        "message": "Passkey invite sent to verified school mailbox"}
    assert "educator-enroll" not in r.text
    assert len(_Sink.messages) == 1
    assert _Sink.messages[0]["to"] == [BODY["institutional_email"]]
    assert LINK.search(_Sink.messages[0]["html"].replace("&amp;", "&"))
    invited = [e for e in w.audit_events() if e["event"] == "educator.passkey_invited"]
    assert len(invited) == 1 and "delivery=email" in invited[0]["detail"]
    assert urlsplit(ORIGIN).netloc not in invited[0]["detail"]


def test_a_request_whose_commit_loses_the_race_never_returns_a_link(monkeypatch):
    """The link may leave issue_invitation_for_admin only after its commit
    succeeded. A loser whose COMMIT (rather than its flush) hits the unique
    index must not get one. Forced here, since a real race rarely loses at
    exactly this point."""
    import asyncio

    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from core.database import Base
    from core.encryption import initialize_encryption
    from routers import educator_passkeys as routes

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

            async def losing_commit():
                raise IntegrityError("INSERT", {}, Exception("unique"))
            monkeypatch.setattr(db, "commit", losing_commit)
            try:
                result = await routes.invite_educator(
                    routes.InviteRequest(**BODY),
                    admin={"role": "parent", "auth_method": "webauthn_uv"}, db=db)
            except Exception as exc:  # the loser's outcome: anything but a link
                result = exc
        await engine.dispose()
        return result

    outcome = asyncio.run(go())
    assert not isinstance(outcome, dict), outcome
