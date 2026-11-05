"""Reading progress for the Practice Coach's progress bar (services/practice/progress.py)."""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from models.practice import PhotoPage, ReadPhotosRequest
from routers import practice as practice_router
from services.practice import extract, progress
from tests.test_practice_coach import GOLDEN, PNG, _routing, b64


@pytest.fixture(autouse=True)
def fresh():
    progress.clear()
    yield
    progress.clear()


class Watching:
    """A reader that records, at each model call, what the progress bar would show."""

    def __init__(self, owner, pid):
        self.seen, self.owner, self.pid = [], owner, pid
        self.messages = self

    async def create(self, **kwargs):
        self.seen.append(progress.read(self.owner, self.pid))
        return type("R", (), {"content": [type("B", (), {"text": json.dumps(GOLDEN["assessment"])})()]})()


DEMO = {"role": "demo_code", "code": "progress-demo"}
PID = "a1b2c3d4-e5f6-4711-8899-aabbccddeeff"


@pytest.fixture
def quota(monkeypatch):
    import core.demo_code_session as session

    async def yes(code):
        return True

    monkeypatch.setattr(session, "has_message_quota", yes)
    monkeypatch.setattr(session, "record_message", yes)


@pytest.mark.asyncio
async def test_progress_counts_pages_read_as_each_group_finishes(monkeypatch, quota):
    owner = progress.owner_of(DEMO)
    reader = Watching(owner, PID)
    _routing(monkeypatch, local=True, cloud=None, local_client=reader)
    req = ReadPhotosRequest(subject="latin", pages=[PhotoPage(data=b64(PNG))] * 14, route="local", progress_id=PID)
    await practice_router.demo_read_assessment(req, auth=DEMO)
    # The total is known before the first page is read, then grows a group at a time.
    assert [(s["stage"], s["done"], s["total"]) for s in reader.seen] == [
        ("reading", 0, 14), ("reading", 6, 14), ("reading", 12, 14)]
    assert await practice_router.demo_progress(PID, auth=DEMO) == {"stage": "reading", "done": 14, "total": 14}


@pytest.mark.asyncio
async def test_one_family_cannot_see_anothers_progress(monkeypatch, quota):
    _routing(monkeypatch, local=True, cloud=None, local_client=Watching("x", PID))
    req = ReadPhotosRequest(subject="latin", pages=[PhotoPage(data=b64(PNG))], route="local", progress_id=PID)
    await practice_router.demo_read_assessment(req, auth=DEMO)
    with pytest.raises(HTTPException) as exc:
        await practice_router.demo_progress(PID, auth={"role": "demo_code", "code": "someone-else"})
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_unknown_or_malformed_ids_are_not_found():
    for pid in ("never-used-id-123", "../../etc", "x"):
        with pytest.raises(HTTPException) as exc:
            await practice_router.demo_progress(pid, auth=DEMO)
        assert exc.value.status_code == 404


def test_progress_holds_only_numbers_and_a_stage():
    progress.update("o", PID, stage="reading", done=3, total=9)
    assert progress.read("o", PID) == {"stage": "reading", "done": 3, "total": 9}
    assert set(progress._entries[("o", PID)]) == {"stage", "done", "total", "updated"}


def test_old_entries_expire_and_the_store_is_bounded(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(progress.time, "monotonic", lambda: clock[0])
    progress.update("o", PID, stage="reading", done=1, total=2)
    clock[0] += progress.TTL_SECONDS + 1
    assert progress.read("o", PID) is None
    monkeypatch.setattr(progress, "MAX_ENTRIES", 5)
    for n in range(20):
        progress.update("o", f"id-{n:08d}", stage="reading")
    assert len(progress._entries) <= 5


def test_a_reading_without_a_progress_id_records_nothing():
    assert progress.reporter("o", None) is None
    progress.update("o", None, stage="reading")
    assert not progress._entries


def test_every_progress_route_is_guarded_like_its_surface():
    from core.deps import require_demo_practice_preview, require_educator, require_parent

    guards = {"/practice/progress/{progress_id}": require_parent,
              "/practice/educator/progress/{progress_id}": require_educator,
              "/practice/demo/progress/{progress_id}": require_demo_practice_preview}
    import inspect
    for route in practice_router.router.routes:
        if route.path in guards:
            deps = [p.default.dependency for p in inspect.signature(route.endpoint).parameters.values()
                    if hasattr(p.default, "dependency")]
            assert guards.pop(route.path) in deps
    assert not guards
