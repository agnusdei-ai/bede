"""Concurrent identical educator invites (routers/educator_passkeys.py).

Synthetic release testing sent three identical ``POST
/auth/educator-passkey/invite`` requests at once and got [202, 500, 500]: the
losers hit the unique index on ``classical_educators.username`` and the
``IntegrityError`` escaped as a 500. They must get the same 422 a sequential
duplicate gets, and no second invitation email may be sent.

Driven over real HTTP against a real uvicorn server (tests/g1_harness.py), so
the requests genuinely overlap; the email transport is replaced by a counting
stub that holds the winner's transaction open long enough for the others to
reach the index. SQLite by default; Postgres via G1_TEST_DATABASE_URL.
Synthetic identities only.
"""
from __future__ import annotations

import asyncio
import threading

import httpx
from sqlalchemy import func, select

from core.config import settings
from core.database import ClassicalEducator, EducatorPasskeyInvitation
from g1_harness import world  # noqa: F401 (fixture)

CONCURRENCY = 3
BODY = {"username": "synthetic.teacher.three",
        "institutional_email": "synthetic.teacher.three@qualification.agnusdei.ai"}


def _wire_mail(monkeypatch) -> list[str]:
    import routers.educator_passkeys as route
    import services.educator_invites as invites

    sent: list[str] = []

    async def send_email(to, subject, body):
        sent.append(to)
        await asyncio.sleep(0.5)  # the winner's transaction stays open meanwhile
        return True

    monkeypatch.setattr(settings, "webauthn_origin", "https://qualification.agnusdei.ai")
    monkeypatch.setattr(settings, "educator_institution_email_domain", "qualification.agnusdei.ai")
    monkeypatch.setattr(route, "email_configured", lambda: True)
    monkeypatch.setattr(invites, "email_configured", lambda: True)
    monkeypatch.setattr(invites, "send_email", send_email)
    return sent


def _count(w, model, *where) -> int:
    async def go():
        async with w.factory() as s:
            q = select(func.count()).select_from(model)
            for clause in where:
                q = q.where(clause)
            return (await s.execute(q)).scalar_one()
    return w.run(go)


def test_concurrent_identical_invites_give_one_202_and_422s_with_one_email(world, monkeypatch):
    w = world
    sent = _wire_mail(monkeypatch)
    barrier = threading.Barrier(CONCURRENCY)
    results: list = [None] * CONCURRENCY
    base, headers = str(w.client.base_url), w.admin()

    def one(i: int) -> None:
        with httpx.Client(base_url=base, timeout=60) as c:
            barrier.wait()
            results[i] = c.post("/auth/educator-passkey/invite", json=BODY, headers=headers)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(CONCURRENCY)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=90)

    codes = sorted(r.status_code for r in results)
    assert codes == [202] + [422] * (CONCURRENCY - 1), [r.text for r in results]
    for r in results:
        if r.status_code == 422:
            assert r.json() == {"detail": "That educator username is already enrolled"}
    assert len(sent) == 1
    assert _count(w, ClassicalEducator, ClassicalEducator.username == BODY["username"]) == 1
    assert _count(w, EducatorPasskeyInvitation) == 1


def test_a_sequential_duplicate_still_gets_the_same_422(world, monkeypatch):
    w = world
    sent = _wire_mail(monkeypatch)
    first = w.client.post("/auth/educator-passkey/invite", json=BODY, headers=w.admin())
    again = w.client.post("/auth/educator-passkey/invite",
                          json={**BODY, "institutional_email": "synthetic.other@qualification.agnusdei.ai"},
                          headers=w.admin())
    assert first.status_code == 202, first.text
    assert (again.status_code, again.json()) == (
        422, {"detail": "That educator username is already enrolled"})
    assert len(sent) == 1
