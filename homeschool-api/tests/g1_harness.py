"""Real-app HTTP/SSE harness for the G1 authorization, voice and tutoring tests.

Everything here is synthetic: Synthetic Campus One / Two, Synthetic Teacher
One / Two, and Synthetic Learner One / Two, whose display names are
deliberately IDENTICAL so any display-name keying shows up as a leak.

The assembled ``main.app`` is served by a REAL uvicorn server on a loopback
port, in its own thread and event loop, and driven with a real ``httpx``
client. ``TestClient`` is deliberately not used: its transport runs the app
to completion before returning any body, so an SSE stream cannot be read
incrementally while other requests (a chunk, a revocation) are sent. Every
request, background audit task, SSE stream and database coroutine runs on
the server's one loop; ``World.run`` submits a coroutine to it. Campuses, learners, memberships, grants and revocations are
created through the real admin HTTP routes. Teacher identities are created by
the real ``provision_educator`` service, and their tokens carry the same
claims a passkey login issues (``auth_method=webauthn_uv``); the passkey
ceremony itself is another lane's subject.

Database. SQLite in memory by default. Set ``G1_TEST_DATABASE_URL`` to an
asyncpg URL to run the identical tests against Postgres. That URL should name
a NON-superuser role that owns its database, which is how the application
runs in production (it creates its own tables). The harness creates every
table, runs the test, and drops every table again.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL_ENV = "G1_TEST_DATABASE_URL"
SAME_NAME = "Synthetic Learner"
ADMIN_CLAIMS = {"role": "parent", "auth_method": "webauthn_uv"}


_SQLITE_DIR = None


def database_url() -> str:
    """Postgres when configured; otherwise a FILE-backed SQLite database.

    Not ``:memory:`` with ``StaticPool``: that gives every session the one
    shared connection, so a revalidation, an audit write and the request's
    own session interleave inside one transaction. Revalidation then fails
    closed for the wrong reason and audit writes are silently lost, which
    is a test artifact (production runs Postgres) and made these tests
    flaky. A file database with a connection per session has real
    isolation."""
    global _SQLITE_DIR
    if os.environ.get(PG_URL_ENV):
        return os.environ[PG_URL_ENV]
    import tempfile
    _SQLITE_DIR = tempfile.TemporaryDirectory(prefix="g1-harness-")
    return f"sqlite+aiosqlite:///{_SQLITE_DIR.name}/g1.db"


def backend_name() -> str:
    return "postgres" if os.environ.get(PG_URL_ENV) else "sqlite"


def _engine():
    url = database_url()
    if url.startswith("sqlite"):
        return create_async_engine(
            url, poolclass=NullPool,
            connect_args={"check_same_thread": False, "timeout": 30},
        )
    # NullPool: every session opens its own connection, as the revalidation
    # path deliberately does, and nothing outlives the test's loop.
    return create_async_engine(url, poolclass=NullPool)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@dataclass
class World:
    client: object
    factory: object
    campus_one: str = ""
    campus_two: str = ""
    teacher_one: str = ""
    teacher_two: str = ""
    learner_one: str = ""
    learner_two: str = ""
    extra: dict = field(default_factory=dict)

    # ── tokens ────────────────────────────────────────────────────────────
    def admin(self) -> dict:
        from core.security import create_access_token
        return bearer(create_access_token(dict(ADMIN_CLAIMS)))

    loop: object = None

    def run(self, coro_fn, *args):
        """Run a coroutine on the server's loop and wait for its result."""
        return asyncio.run_coroutine_threadsafe(coro_fn(*args), self.loop).result(timeout=60)

    def credential_version(self, teacher_id: str) -> int:
        async def read():
            from core.database import ClassicalEducator
            async with self.factory() as s:
                return (await s.get(ClassicalEducator, teacher_id)).credential_version
        return self.run(read)

    def teacher(self, teacher_id: str, ev: int | None = None) -> dict:
        """A token exactly as a passkey login issues it, at the teacher's
        CURRENT credential version unless one is given (a stale token)."""
        from core.security import create_access_token
        return bearer(create_access_token({
            "role": "educator", "sub": teacher_id, "auth_method": "webauthn_uv",
            "ev": self.credential_version(teacher_id) if ev is None else ev,
        }))

    # ── admin actions through the real routes ─────────────────────────────
    def revoke(self, campus: str, teacher: str, learner: str) -> None:
        r = self.client.delete(
            f"/pilot/campuses/{campus}/educators/{teacher}/learners/{learner}",
            headers=self.admin(),
        )
        assert r.status_code == 204, r.text

    def grant(self, campus: str, teacher: str, learner: str) -> None:
        r = self.client.post(
            f"/pilot/campuses/{campus}/educators/{teacher}/learners/{learner}",
            headers=self.admin(),
        )
        assert r.status_code == 204, r.text

    def authorize_campus(self, campus: str, name: str = "Synthetic Administrator") -> None:
        """Opt the campus in through the REAL data-authorization endpoint with
        the REAL current notice hash. Never a bypass of the gate."""
        shown = self.client.get(f"/pilot/campuses/{campus}/data-authorization",
                                headers=self.admin())
        assert shown.status_code == 200, shown.text
        r = self.client.post(
            f"/pilot/campuses/{campus}/data-authorization",
            json={"notice_hash": shown.json()["notice_hash"], "authorizer_name": name,
                  "authorizer_role": "administrator"},
            headers=self.admin(),
        )
        assert r.status_code in (200, 201), r.text

    def audit_events(self) -> list[dict]:
        """Every audit row, after the fire-and-forget audit writes already
        scheduled on the server's loop have finished (log_event_nowait), so
        a read never races the write it is looking for."""
        async def read():
            from core.audit import _background_tasks, read_audit_log
            loop = asyncio.get_running_loop()
            while pending := tuple(
                t for t in _background_tasks if t.get_loop() is loop and not t.done()
            ):
                await asyncio.gather(*pending, return_exceptions=True)
            async with self.factory() as s:
                return await read_audit_log(s, limit=500)
        return self.run(read)


class _Server:
    """uvicorn on 127.0.0.1:<ephemeral>, in a daemon thread with its own loop."""

    def __init__(self, app, port: int = 0):
        import uvicorn
        self.loop = asyncio.new_event_loop()
        self.server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=port, lifespan="off", log_level="warning",
            loop="none", access_log=False,
        ))
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.server.serve())

    def start(self) -> str:
        self.thread.start()
        deadline = time.monotonic() + 15
        while not self.server.started:
            if time.monotonic() > deadline or not self.thread.is_alive():
                raise RuntimeError("test server did not start")
            time.sleep(0.02)
        port = self.server.servers[0].sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=15)
        self.loop.close()


@contextmanager
def g1_world(monkeypatch, campuses: bool = True, port: int = 0):
    import httpx
    import core.database as database
    import main
    from core.config import settings
    from core.audit import _background_tasks
    from core.database import Base, get_db
    from core.encryption import initialize_encryption
    import services.streaming_transcription as st

    monkeypatch.setattr(settings, "educator_pilot_enabled", True)
    monkeypatch.setattr(settings, "demo_pin", "")
    monkeypatch.setattr(settings, "elevation_enforced", False)
    for name in ("rate_limit_api_per_minute", "rate_limit_voice_per_minute",
                 "rate_limit_voice_stream_session_per_minute",
                 "rate_limit_auth_per_minute"):
        monkeypatch.setattr(settings, name, 100_000)

    engine = _engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", factory)
    monkeypatch.setattr(database, "engine", engine)

    async def _get_db():
        async with factory() as session:
            yield session

    app = main.app
    app.dependency_overrides[get_db] = _get_db
    st._sessions.clear()

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as s:
            await initialize_encryption(settings.master_secret, s)

    async def _teardown():
        for sid in list(st._sessions):
            st._discard(sid)
        loop = asyncio.get_running_loop()
        while pending := tuple(
            t for t in _background_tasks if t.get_loop() is loop and not t.done()
        ):
            await asyncio.gather(*pending, return_exceptions=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    server = _Server(app, port)
    try:
        base_url = server.start()
        with httpx.Client(base_url=base_url, timeout=30) as client:
            world = World(client=client, factory=factory, loop=server.loop)
            world.run(_setup)
            try:
                _seed(world) if campuses else _seed_legacy(world)
                yield world
            finally:
                world.run(_teardown)
    finally:
        server.stop()
        app.dependency_overrides.pop(get_db, None)
        st._sessions.clear()


def _seed(world: World) -> None:
    from services.educator_access import provision_educator

    async def teachers():
        async with world.factory() as s:
            one = await provision_educator(s, "synthetic.teacher.one", "synthetic-passphrase-one-strong")
        async with world.factory() as s:
            two = await provision_educator(s, "synthetic.teacher.two", "synthetic-passphrase-two-strong")
        return one["id"], two["id"]

    world.teacher_one, world.teacher_two = world.run(teachers)
    c, admin = world.client, world.admin()
    for attr, title in (("campus_one", "Synthetic Campus One"), ("campus_two", "Synthetic Campus Two")):
        r = c.post("/pilot/campuses", json={"title": title}, headers=admin)
        assert r.status_code == 201, r.text
        setattr(world, attr, r.json()["campus_id"])
    for campus in (world.campus_one, world.campus_two):
        world.authorize_campus(campus)
    for attr, campus in (("learner_one", world.campus_one), ("learner_two", world.campus_two)):
        r = c.post(f"/pilot/campuses/{campus}/learners", json={"display_name": SAME_NAME}, headers=admin)
        assert r.status_code == 201, r.text
        setattr(world, attr, r.json()["learner_id"])
    for campus, teacher in ((world.campus_one, world.teacher_one), (world.campus_two, world.teacher_two)):
        r = c.post(f"/pilot/campuses/{campus}/educators/{teacher}", headers=admin)
        assert r.status_code == 204, r.text
    world.grant(world.campus_one, world.teacher_one, world.learner_one)
    world.grant(world.campus_two, world.teacher_two, world.learner_two)


def legacy_config(name: str) -> dict:
    return {
        "student_name": name, "grade": "4", "grade_stage": "3-5",
        "subjects": ["mathematics", "living_books"],
    }


def _seed_legacy(world: World) -> None:
    """Single-household mode: NO pilot campus exists, so the name-keyed
    roster is the grant. Learner names must be unique here; that is the
    reason this mode ends the moment any campus exists."""
    from services.educator_access import provision_educator

    async def teachers():
        async with world.factory() as s:
            one = await provision_educator(s, "synthetic.teacher.one", "synthetic-passphrase-one-strong")
        async with world.factory() as s:
            two = await provision_educator(s, "synthetic.teacher.two", "synthetic-passphrase-two-strong")
        return one["id"], two["id"]

    world.teacher_one, world.teacher_two = world.run(teachers)
    world.extra["name_one"], world.extra["name_two"] = "Synthetic Learner One", "Synthetic Learner Two"
    for teacher, name in ((world.teacher_one, world.extra["name_one"]),
                          (world.teacher_two, world.extra["name_two"])):
        r = world.client.put(
            f"/educators/accounts/{teacher}/roster",
            json={"configs": [legacy_config(name)]}, headers=world.admin(),
        )
        assert r.status_code == 200, r.text


@pytest.fixture
def legacy_world(monkeypatch):
    with g1_world(monkeypatch, campuses=False) as w:
        yield w


@pytest.fixture
def world(monkeypatch):
    with g1_world(monkeypatch) as w:
        yield w


def sse_items(lines) -> list[dict]:
    """Decode the JSON ``data:`` payloads of an SSE line iterator."""
    out = []
    for line in lines:
        if line.startswith("data:"):
            out.append(json.loads(line[5:].strip()))
    return out
