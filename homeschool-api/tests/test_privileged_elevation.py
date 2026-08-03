"""
Privileged access elevation (docs/ARCHITECTURE_PRINCIPLES.md P8,
core/elevation.py).

Two halves, and the split matters.

The unit half exercises core/elevation.py directly: grants, expiry,
per-session scoping.

The integration half runs against the ASSEMBLED app through TestClient with
a real signed token, because that is the only thing that proves the control
is actually wired. Every existing test of these endpoints calls the route
function directly with `_={"role": "parent"}`, which bypasses FastAPI's
dependency resolution entirely — so all of them kept passing when the guard
was added, and all of them would keep passing if it were removed again. A
control nothing fails without is not a control. That is P11's point, and
this file is where the management plane satisfies it.
"""
import asyncio
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

from core import elevation
from core.config import settings
from core.database import Base, PrivilegedElevation, get_db
from core.security import create_access_token



@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


# ── The mechanism ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_session_is_not_elevated_until_it_elevates(db):
    assert await elevation.is_elevated(db, "session-a") is False


@pytest.mark.asyncio
async def test_granting_elevates_that_session(db):
    await elevation.grant(db, "session-a")
    assert await elevation.is_elevated(db, "session-a") is True


@pytest.mark.asyncio
async def test_elevation_belongs_to_one_session_not_to_the_parent(db):
    """Elevating on the desktop must not elevate the tablet still logged in
    in the kitchen — the grant is keyed on the token's jti."""
    await elevation.grant(db, "desktop")
    assert await elevation.is_elevated(db, "tablet") is False


@pytest.mark.asyncio
async def test_a_token_with_no_session_id_is_never_elevated(db):
    """Covers tokens issued before P8 and every non-parent role. Fails in the
    safe direction: re-login, rather than an unidentifiable session silently
    counting as elevated."""
    assert await elevation.is_elevated(db, None) is False
    assert await elevation.is_elevated(db, "") is False


@pytest.mark.asyncio
async def test_an_expired_grant_no_longer_elevates(db):
    await elevation.grant(db, "session-a")
    row = await db.get(PrivilegedElevation, "session-a")
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()

    assert await elevation.is_elevated(db, "session-a") is False


@pytest.mark.asyncio
async def test_re_elevating_resets_the_clock_rather_than_stacking(db):
    await elevation.grant(db, "session-a")
    row = await db.get(PrivilegedElevation, "session-a")
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db.commit()
    assert await elevation.is_elevated(db, "session-a") is False

    await elevation.grant(db, "session-a")
    assert await elevation.is_elevated(db, "session-a") is True
    # Still one row — a re-elevation updates, it doesn't accumulate.
    assert await elevation.active_count(db) == 1


@pytest.mark.asyncio
async def test_dropping_ends_elevation_immediately(db):
    await elevation.grant(db, "session-a")
    assert await elevation.drop(db, "session-a") is True
    assert await elevation.is_elevated(db, "session-a") is False
    assert await elevation.drop(db, "session-a") is False


@pytest.mark.asyncio
async def test_expiry_is_absolute_not_a_sliding_window(db):
    """Checking elevation must not extend it. A sliding window would let one
    password entry hold administrator rights for the whole session as long as
    someone kept clicking, which is the property this exists to remove."""
    await elevation.grant(db, "session-a")
    first = (await db.get(PrivilegedElevation, "session-a")).expires_at

    for _ in range(3):
        assert await elevation.is_elevated(db, "session-a") is True
    await db.refresh(await db.get(PrivilegedElevation, "session-a"))

    assert (await db.get(PrivilegedElevation, "session-a")).expires_at == first


@pytest.mark.asyncio
async def test_purging_removes_only_expired_grants(db):
    await elevation.grant(db, "live")
    await elevation.grant(db, "stale")
    stale = await db.get(PrivilegedElevation, "stale")
    stale.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.commit()

    assert await elevation.purge_expired(db) == 1
    assert await db.get(PrivilegedElevation, "stale") is None
    assert await elevation.is_elevated(db, "live") is True


@pytest.mark.asyncio
async def test_session_ids_are_unique_and_unguessable():
    ids = {elevation.new_jti() for _ in range(500)}
    assert len(ids) == 500
    assert all(len(i) >= 20 for i in ids)


@pytest.mark.asyncio
async def test_every_parent_token_carries_a_session_id():
    """Centralised in create_access_token so no issue site can forget it — a
    parent session with no jti could never be elevated, and the symptom would
    read as 'the audit log is broken', not 'this token is malformed'."""
    from core.security import decode_token

    assert decode_token(create_access_token({"sub": "parent", "role": "parent"})).get("jti")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["child", "demo_code"])
async def test_non_parent_tokens_get_no_session_id(role):
    from core.security import decode_token

    assert "jti" not in decode_token(create_access_token({"sub": role, "role": role}))


# ── The assembled app: is the control actually wired? ───────────────────────

# Every management-plane endpoint the elevation gate is supposed to cover.
# Listed here rather than derived from the routers so that removing a guard
# fails this file instead of quietly shrinking the list.
GUARDED = [
    ("GET",    "/admin/audit"),
    ("POST",   "/admin/license"),
    ("POST",   "/admin/ai-provider"),
    ("DELETE", "/pod/configs/Emma"),
    ("POST",   "/mfa/webauthn/register/options"),
    ("POST",   "/mfa/webauthn/register/verify"),
    ("DELETE", "/mfa/webauthn/1"),
    ("POST",   "/mfa/totp/enroll"),
    ("POST",   "/mfa/totp/confirm"),
    ("DELETE", "/mfa/totp"),
    ("POST",   "/mfa/recovery-pin/enroll"),
    ("DELETE", "/mfa/recovery-pin"),
    ("POST",   "/mfa/recovery-code/enroll"),
    ("DELETE", "/mfa/recovery-code"),
]

# Parent endpoints that must NOT require elevation. Requiring a password for
# the ordinary parent day would train a parent to retype it reflexively,
# which is how step-up stops being a signal and becomes an obstacle people
# route around.
UNGUARDED = [
    ("GET", "/admin/status"),
    ("GET", "/admin/license"),
    ("GET", "/admin/ai-provider"),
    ("GET", "/mfa/status"),
]


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """/auth/elevate sits under the per-IP auth rate limit (10/min) — the
    same bucket as /auth/login, and deliberately so: an endpoint that
    compares a submitted password is a password oracle whether or not the
    caller already holds a session. That limit is module-global and every
    test here calls from the same address, so without this the later tests
    in the file get 429s instead of the status they assert."""
    from core.middleware import reset_rate_limiter
    reset_rate_limiter()
    yield
    reset_rate_limiter()


@pytest.fixture
def client(monkeypatch):
    """The real, fully assembled app with only its database swapped out.

    Deliberately NOT wrapped in `with TestClient(...)`: the context manager
    runs main.py's lifespan, which builds tables against the real
    DATABASE_URL and would try to reach Postgres. Nothing in the lifespan is
    what these tests are about — the guards are dependency-resolution
    behaviour.

    A file-backed SQLite with NullPool rather than the in-memory StaticPool
    used elsewhere in the suite: TestClient drives each request on its own
    event loop, and an aiosqlite connection pooled across loops raises
    "Event loop is closed". NullPool opens a fresh connection per checkout,
    so it doesn't matter which loop asks.
    """
    import main
    import core.database as database_module

    url = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/elevation.sqlite"

    async def _create():
        eng = create_async_engine(url, poolclass=NullPool)
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await eng.dispose()

    asyncio.run(_create())

    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # core/audit.py and friends open their own sessions rather than taking
    # the injected one, so the override alone would leave them pointed at
    # Postgres.
    monkeypatch.setattr(database_module, "AsyncSessionLocal", factory)
    monkeypatch.setattr(database_module, "engine", engine)

    import core.encryption as encryption_module
    if encryption_module._DATA_KEY is None:
        from Crypto.Random import get_random_bytes
        monkeypatch.setattr(encryption_module, "_DATA_KEY", get_random_bytes(32))

    async def _override():
        async with factory() as session:
            yield session

    main.app.dependency_overrides[get_db] = _override
    yield TestClient(main.app)
    main.app.dependency_overrides.pop(get_db, None)
    # Dispose on a fresh loop — the loops TestClient ran requests on are
    # already closed, and leaving the engine undisposed surfaces as an
    # "Event loop is closed" ResourceWarning during teardown.
    asyncio.run(engine.dispose())


def _parent_headers(client) -> dict:
    """A genuine signed parent token for this app.

    No fingerprint claim: validate_fingerprint's own "no fp -> allow" branch
    means the token works from the test client, and device binding is not
    what this file is testing."""
    token = create_access_token({"sub": "parent", "role": "parent"})
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("method,path", GUARDED)
def test_an_unelevated_parent_is_refused_on_the_management_plane(client, method, path):
    resp = client.request(method, path, json={}, headers=_parent_headers(client))

    assert resp.status_code == 403, f"{method} {path} returned {resp.status_code}"
    detail = resp.json()["detail"]
    assert isinstance(detail, dict) and detail.get("elevation_required") is True, (
        f"{method} {path} denied without the elevation_required marker the "
        f"frontend needs to prompt for a password: {detail!r}"
    )


@pytest.mark.parametrize("method,path", UNGUARDED)
def test_ordinary_parent_endpoints_do_not_demand_a_password(client, method, path):
    resp = client.request(method, path, headers=_parent_headers(client))

    assert resp.status_code != 403 or "elevation_required" not in str(resp.json()), (
        f"{method} {path} now requires elevation but is part of the ordinary parent day"
    )


def test_elevating_then_using_the_management_plane_succeeds(client):
    headers = _parent_headers(client)

    assert client.get("/admin/audit", headers=headers).status_code == 403

    resp = client.post(
        "/auth/elevate", json={"password": settings.parent_password}, headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["elevated"] is True

    assert client.get("/admin/audit", headers=headers).status_code == 200


def test_the_wrong_password_does_not_elevate(client):
    headers = _parent_headers(client)

    resp = client.post("/auth/elevate", json={"password": "not-the-password"}, headers=headers)
    assert resp.status_code == 401

    assert client.get("/admin/audit", headers=headers).status_code == 403


def test_elevation_does_not_leak_to_a_second_session(client):
    """Two devices, both logged in as the parent. Elevating one must not
    elevate the other — that is the whole reason the grant is keyed on jti
    rather than on the role."""
    desktop = _parent_headers(client)
    tablet = _parent_headers(client)

    client.post("/auth/elevate", json={"password": settings.parent_password}, headers=desktop)

    assert client.get("/admin/audit", headers=desktop).status_code == 200
    assert client.get("/admin/audit", headers=tablet).status_code == 403


def test_dropping_elevation_re_locks_the_management_plane(client):
    headers = _parent_headers(client)
    client.post("/auth/elevate", json={"password": settings.parent_password}, headers=headers)
    assert client.get("/admin/audit", headers=headers).status_code == 200

    assert client.request("DELETE", "/auth/elevate", headers=headers).json()["was_elevated"] is True
    assert client.get("/admin/audit", headers=headers).status_code == 403


def test_logging_out_ends_the_elevation(client):
    """A parent token is a stateless JWT valid until it expires, so "logged
    out" is a client-side claim. The elevation is the one piece of server-side
    state this session has — a token recovered after logout must not come back
    still holding management-plane privilege."""
    headers = _parent_headers(client)
    client.post("/auth/elevate", json={"password": settings.parent_password}, headers=headers)

    client.post("/auth/logout", headers=headers)

    assert client.get("/admin/audit", headers=headers).status_code == 403


def test_elevation_status_reports_the_current_state(client):
    headers = _parent_headers(client)
    assert client.get("/auth/elevate", headers=headers).json()["elevated"] is False

    client.post("/auth/elevate", json={"password": settings.parent_password}, headers=headers)
    assert client.get("/auth/elevate", headers=headers).json()["elevated"] is True


def test_a_child_cannot_elevate(client):
    token = create_access_token({"sub": "child", "role": "child"})
    resp = client.post(
        "/auth/elevate",
        json={"password": settings.parent_password},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
