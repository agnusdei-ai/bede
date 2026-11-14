"""Idempotent campus and learner creation (routers/pilot_campuses.py).

Sample release testing found that five concurrent identical
``POST /pilot/campuses`` created five campuses, and a retry after a lost
response created a second one; learner creation behaved the same way. A
client-generated ``Idempotency-Key`` header now makes one submission create
one row, enforced by the composite primary key of ``pilot_idempotency_keys``
rather than by a check-then-insert.

Driven over real HTTP against a real uvicorn server (tests/g1_harness.py), so
concurrent requests genuinely overlap. SQLite by default; Postgres when
G1_TEST_DATABASE_URL names a non-superuser role. Sample names only.
"""
from __future__ import annotations

import threading
import uuid

import httpx
from sqlalchemy import func, select

from core.database import PilotCampus, PilotIdempotencyKey, PilotLearner
from g1_harness import world  # noqa: F401 (fixture)

CONCURRENCY = 5


def _count(w, model, *where) -> int:
    async def go():
        async with w.factory() as s:
            q = select(func.count()).select_from(model)
            for clause in where:
                q = q.where(clause)
            return (await s.execute(q)).scalar_one()
    return w.run(go)


def _concurrently(w, path: str, body: dict, headers: dict) -> list[httpx.Response]:
    """CONCURRENCY requests released together, each on its own connection."""
    barrier = threading.Barrier(CONCURRENCY)
    results: list = [None] * CONCURRENCY
    base = str(w.client.base_url)

    def one(i: int) -> None:
        with httpx.Client(base_url=base, timeout=30) as c:
            barrier.wait()
            results[i] = c.post(path, json=body, headers=headers)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(CONCURRENCY)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return results


def _key() -> dict:
    return {"Idempotency-Key": str(uuid.uuid4())}


def test_concurrent_campus_creates_with_one_key_make_exactly_one_campus(world):
    w = world
    before = _count(w, PilotCampus)
    headers = {**w.admin(), **_key()}
    rs = _concurrently(w, "/pilot/campuses", {"title": "Sample Campus Three"}, headers)
    assert [r.status_code for r in rs] == [201] * CONCURRENCY, [r.text for r in rs]
    assert len({r.json()["campus_id"] for r in rs}) == 1
    assert all(r.json() == rs[0].json() for r in rs)
    assert _count(w, PilotCampus) == before + 1
    assert _count(w, PilotIdempotencyKey) == 1


def test_concurrent_learner_creates_with_one_key_make_exactly_one_learner(world):
    w = world
    before = _count(w, PilotLearner, PilotLearner.campus_id == w.campus_one)
    headers = {**w.admin(), **_key()}
    rs = _concurrently(w, f"/pilot/campuses/{w.campus_one}/learners",
                       {"display_name": "Sample Learner Three"}, headers)
    assert [r.status_code for r in rs] == [201] * CONCURRENCY, [r.text for r in rs]
    assert all(r.json() == rs[0].json() for r in rs)
    assert rs[0].json()["display_name"] == "Sample Learner Three"
    assert _count(w, PilotLearner, PilotLearner.campus_id == w.campus_one) == before + 1


def test_a_sequential_retry_returns_the_original_campus(world):
    w = world
    headers = {**w.admin(), **_key()}
    first = w.client.post("/pilot/campuses", json={"title": "Sample Campus Four"}, headers=headers)
    again = w.client.post("/pilot/campuses", json={"title": "Sample Campus Four"}, headers=headers)
    assert (first.status_code, again.status_code) == (201, 201)
    assert again.json() == first.json()
    assert _count(w, PilotCampus, PilotCampus.title == "Sample Campus Four") == 1


def test_a_sequential_learner_retry_returns_the_original_learner(world):
    w = world
    headers = {**w.admin(), **_key()}
    path = f"/pilot/campuses/{w.campus_two}/learners"
    first = w.client.post(path, json={"display_name": "Sample Learner Four"}, headers=headers)
    again = w.client.post(path, json={"display_name": "Sample Learner Four"}, headers=headers)
    assert (first.status_code, again.status_code) == (201, 201)
    assert again.json()["learner_id"] == first.json()["learner_id"]


def test_the_same_key_with_a_different_body_is_refused(world):
    w = world
    headers = {**w.admin(), **_key()}
    ok = w.client.post("/pilot/campuses", json={"title": "Sample Campus Five"}, headers=headers)
    other = w.client.post("/pilot/campuses", json={"title": "Sample Campus Six"}, headers=headers)
    assert ok.status_code == 201
    assert other.status_code == 422, other.text
    assert _count(w, PilotCampus, PilotCampus.title == "Sample Campus Six") == 0


def test_the_same_learner_key_on_another_campus_is_refused(world):
    w = world
    headers = {**w.admin(), **_key()}
    body = {"display_name": "Sample Learner Five"}
    ok = w.client.post(f"/pilot/campuses/{w.campus_one}/learners", json=body, headers=headers)
    other = w.client.post(f"/pilot/campuses/{w.campus_two}/learners", json=body, headers=headers)
    assert ok.status_code == 201
    assert other.status_code == 422, other.text


def test_without_the_header_every_request_still_creates(world):
    """Backward compatible: a client that sends no key behaves as before."""
    w = world
    before = _count(w, PilotCampus)
    for _ in range(2):
        r = w.client.post("/pilot/campuses", json={"title": "Sample Campus Seven"},
                          headers=w.admin())
        assert r.status_code == 201
    assert _count(w, PilotCampus) == before + 2
    assert _count(w, PilotIdempotencyKey) == 0


def test_a_malformed_key_is_refused_before_anything_is_created(world):
    w = world
    before = _count(w, PilotCampus)
    r = w.client.post("/pilot/campuses", json={"title": "Sample Campus Eight"},
                      headers={**w.admin(), "Idempotency-Key": "short"})
    assert r.status_code == 422
    assert _count(w, PilotCampus) == before


def test_the_claim_stores_no_learner_name(world):
    w = world
    headers = {**w.admin(), **_key()}
    w.client.post(f"/pilot/campuses/{w.campus_one}/learners",
                  json={"display_name": "Sample Learner Six"}, headers=headers)

    async def rows():
        async with w.factory() as s:
            return (await s.execute(select(PilotIdempotencyKey))).scalars().all()
    for row in w.run(rows):
        assert "Sample" not in " ".join(str(v) for v in vars(row).values())
