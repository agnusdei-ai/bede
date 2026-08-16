"""
P9 device revocation, end to end (docs/DEVICE_IDENTITY_DESIGN.md's Option
C) — login registers a device, a revoked device is refused at its next
login AND on its next already-issued-token request, and the admin
list/revoke endpoints are reachable through the real guard chain.

Two halves, mirroring tests/test_privileged_elevation.py's own split:
  - The login()-level half calls routers/auth.py's login() directly (same
    pattern as tests/test_auth_login_lockout.py) — cheaper, and enough to
    prove login-time registration/refusal.
  - The TestClient half runs against the ASSEMBLED app, because that is
    the only thing that proves core/deps.py's per-request check is
    actually wired into the real dependency-injection graph rather than
    just correct in isolation (P11's point).
"""
import asyncio
import tempfile

import pytest
import pytest_asyncio
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from core import device_registry
from core.config import settings
from core.database import Base, get_db
from core.security import decode_token
from models.schemas import LoginRequest
from routers.auth import login

pytestmark = [pytest.mark.usefixtures("demo_db")]
# Applied individually to the async (login()-direct-call) tests below, not
# as a blanket module mark — the TestClient half is synchronous (TestClient
# drives its own event loop per request), and marking those with asyncio
# too produces a pytest warning for a mark that does nothing.


@pytest.fixture(autouse=True)
def _reset_cache():
    device_registry._set_cache(set())
    yield
    device_registry._set_cache(set())


def _fake_request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 12345), "headers": [(b"user-agent", b"pytest")]})


# ── Schema-level: length bound ──────────────────────────────────────────────

def test_an_oversized_device_id_is_rejected_by_the_schema():
    """Hardening fix: device_id had no length bound before this, so a
    value longer than DeviceRecord.device_id's String(64) column would
    reach the database unvalidated and fail as an unhandled DataError
    (500) instead of a clean rejection here (422 once FastAPI parses the
    request body)."""
    with pytest.raises(ValidationError):
        LoginRequest(role="parent", credential="x", device_id="x" * 65)


def test_a_device_id_at_exactly_the_bound_is_still_accepted():
    LoginRequest(role="parent", credential="x", device_id="x" * 64)


# ── login()-level: registration, refusal ────────────────────────────────────

@pytest_asyncio.fixture
async def db_session(demo_db):
    async with demo_db() as session:
        yield session


@pytest.mark.asyncio
async def test_login_with_a_device_id_registers_the_device_and_embeds_the_claim(db_session):
    resp = await login(
        LoginRequest(role="parent", credential=settings.parent_password, device_id="dev-1"),
        _fake_request(), db_session,
    )
    payload = decode_token(resp.access_token)
    assert payload["device_id"] == "dev-1"

    from core.database import DeviceRecord
    row = await db_session.get(DeviceRecord, "dev-1")
    assert row is not None
    assert row.last_role == "parent"


@pytest.mark.asyncio
async def test_login_without_a_device_id_is_unaffected(db_session):
    """A caller driving the API directly (or an older client) that omits
    device_id must see zero behavior change — no rejection, no crash, no
    device record created."""
    resp = await login(LoginRequest(role="parent", credential=settings.parent_password), _fake_request(), db_session)
    payload = decode_token(resp.access_token)
    assert "device_id" not in payload


@pytest.mark.asyncio
async def test_child_login_also_registers_a_device(db_session):
    resp = await login(
        LoginRequest(role="child", credential=settings.child_pin, device_id="tablet-1"),
        _fake_request(), db_session,
    )
    payload = decode_token(resp.access_token)
    assert payload["device_id"] == "tablet-1"
    assert payload["role"] == "child"

    from core.database import DeviceRecord
    row = await db_session.get(DeviceRecord, "tablet-1")
    assert row.last_role == "child"


@pytest.mark.asyncio
async def test_a_shared_tablet_shows_whichever_role_logged_in_most_recently(db_session):
    """One physical device, both roles — deliberately NOT one row per
    (device, role) pair; see DeviceRecord's own docstring."""
    await login(LoginRequest(role="parent", credential=settings.parent_password, device_id="shared"), _fake_request(), db_session)
    await login(LoginRequest(role="child", credential=settings.child_pin, device_id="shared"), _fake_request(), db_session)

    from core.database import DeviceRecord
    row = await db_session.get(DeviceRecord, "shared")
    assert row.last_role == "child"


@pytest.mark.asyncio
async def test_a_revoked_device_is_refused_after_correct_credentials_are_verified(db_session):
    """The device check runs only once the password has already verified —
    NOT before. See test_a_wrong_password_never_reveals_device_revocation_
    status below for why: checking first would make this endpoint a
    pre-authentication oracle."""
    await login(LoginRequest(role="parent", credential=settings.parent_password, device_id="dev-1"), _fake_request(), db_session)
    await device_registry.revoke(db_session, "dev-1")

    with pytest.raises(HTTPException) as exc_info:
        await login(LoginRequest(role="parent", credential=settings.parent_password, device_id="dev-1"), _fake_request(), db_session)
    assert exc_info.value.status_code == 401
    assert "revoked" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_a_wrong_password_never_reveals_device_revocation_status(db_session):
    """Regression test for a real pre-authentication oracle a security
    review found: an earlier version checked device revocation BEFORE
    verifying the password, so a caller submitting a real device_id with
    ANY (or no valid) credential could learn whether that device was
    revoked without ever proving they held it. A wrong password must now
    get the ordinary "Invalid credentials" response regardless of whether
    the device happens to be revoked -- the two cases must be
    indistinguishable to a caller who doesn't already know the password."""
    await login(LoginRequest(role="parent", credential=settings.parent_password, device_id="dev-1"), _fake_request(), db_session)
    await device_registry.revoke(db_session, "dev-1")

    with pytest.raises(HTTPException) as exc_info:
        await login(LoginRequest(role="parent", credential="totally-wrong", device_id="dev-1"), _fake_request(), db_session)
    assert "revoked" not in exc_info.value.detail.lower()
    assert exc_info.value.detail == "Invalid credentials"

    # Confirm the two failure modes are byte-for-byte identical from the
    # caller's side -- a NON-revoked device with the same wrong password
    # must produce the exact same response.
    with pytest.raises(HTTPException) as exc_info_control:
        await login(LoginRequest(role="parent", credential="totally-wrong", device_id="never-registered"), _fake_request(), db_session)
    assert exc_info_control.value.detail == exc_info.value.detail
    assert exc_info_control.value.status_code == exc_info.value.status_code


@pytest.mark.asyncio
async def test_a_wrong_pin_never_reveals_device_revocation_status_for_a_child(db_session):
    """Same oracle, the child-role route into it."""
    await login(LoginRequest(role="child", credential=settings.child_pin, device_id="tablet-1"), _fake_request(), db_session)
    await device_registry.revoke(db_session, "tablet-1")

    wrong_pin = "1234" if settings.child_pin != "1234" else "5678"
    with pytest.raises(HTTPException) as exc_info:
        await login(LoginRequest(role="child", credential=wrong_pin, device_id="tablet-1"), _fake_request(), db_session)
    assert "revoked" not in exc_info.value.detail.lower()
    assert exc_info.value.detail == "Invalid credentials"


@pytest.mark.asyncio
async def test_revoking_one_device_does_not_affect_a_different_device(db_session):
    await login(LoginRequest(role="parent", credential=settings.parent_password, device_id="dev-1"), _fake_request(), db_session)
    await login(LoginRequest(role="parent", credential=settings.parent_password, device_id="dev-2"), _fake_request(), db_session)
    await device_registry.revoke(db_session, "dev-1")

    resp = await login(LoginRequest(role="parent", credential=settings.parent_password, device_id="dev-2"), _fake_request(), db_session)
    assert decode_token(resp.access_token)["device_id"] == "dev-2"


@pytest.mark.asyncio
async def test_demo_code_login_never_sends_or_registers_a_device(db_session):
    """demo_code is anonymous and already has its own one-time-code
    identity — LoginRequest.device_id exists for parent/child only."""
    from core.demo_code_session import generate_code
    code = await generate_code()  # manages its own session internally — see its own docstring
    resp = await login(LoginRequest(role="demo_code", credential=code), _fake_request(), db_session)
    payload = decode_token(resp.access_token)
    assert "device_id" not in payload


# ── TestClient: the real guard chain, end to end ────────────────────────────

@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from core.middleware import reset_rate_limiter
    reset_rate_limiter()
    yield
    reset_rate_limiter()


@pytest.fixture
def client(monkeypatch):
    """The real, fully assembled app with only its database swapped out —
    same fixture shape as tests/test_privileged_elevation.py's `client`;
    see that file's docstring for why each piece is built the way it is.

    elevation_enforced is turned OFF here deliberately: P8's own step-up
    flow is exhaustively tested elsewhere (test_privileged_elevation.py),
    and re-driving a full password re-entry in every test here would test
    P8 a second time instead of isolating P9's own behavior. With it off,
    POST /admin/devices/{id}/revoke behaves like require_parent, which is
    exactly what we want this file to exercise.
    """
    import main
    import core.database as database_module

    monkeypatch.setattr(settings, "elevation_enforced", False)

    url = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/devices.sqlite"

    async def _create():
        eng = create_async_engine(url, poolclass=NullPool)
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await eng.dispose()

    asyncio.run(_create())

    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

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
    test_client = TestClient(main.app)
    test_client.db_factory = factory  # convenience for tests that need a session outside a request
    yield test_client
    main.app.dependency_overrides.pop(get_db, None)
    asyncio.run(engine.dispose())


def test_a_token_from_a_revoked_device_is_rejected_on_its_very_next_request(client):
    # NOTE: GET /auth/validate deliberately does NOT go through this check —
    # it re-implements a lightweight JWT+fingerprint validation of its own
    # (routers/auth.py) and, pre-existing this feature, doesn't check
    # credentials_version either. This test uses /admin/status instead,
    # specifically because it IS reached through core/deps.py's
    # require_parent -> _validate_token, which is the actual enforcement
    # point this test needs to prove.
    login_resp = client.post("/auth/login", json={"role": "parent", "credential": settings.parent_password, "device_id": "dev-1"})
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Works before revocation.
    assert client.get("/admin/status", headers=headers).status_code == 200

    revoke_resp = client.post("/admin/devices/dev-1/revoke", headers=headers)
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["revoked"] is True

    # The SAME already-issued token — not a fresh login — now fails, even
    # though it's the very token that JUST successfully made the revoke
    # call above. This is the property that makes revocation real rather
    # than just blocking future logins: revoking the device you're
    # currently on ends your own access immediately too, which is the
    # correct behavior for "I think someone else has this device."
    blocked = client.get("/admin/status", headers=headers)
    assert blocked.status_code == 401
    assert "revoked" in blocked.json()["detail"].lower()


def test_a_revoked_devices_next_login_attempt_is_also_refused(client):
    login_resp = client.post("/auth/login", json={"role": "parent", "credential": settings.parent_password, "device_id": "dev-1"})
    token = login_resp.json()["access_token"]
    client.post("/admin/devices/dev-1/revoke", headers={"Authorization": f"Bearer {token}"})

    second_attempt = client.post("/auth/login", json={"role": "parent", "credential": settings.parent_password, "device_id": "dev-1"})
    assert second_attempt.status_code == 401
    assert "revoked" in second_attempt.json()["detail"].lower()


def test_revoking_an_unknown_device_id_404s(client):
    login_resp = client.post("/auth/login", json={"role": "parent", "credential": settings.parent_password, "device_id": "dev-1"})
    token = login_resp.json()["access_token"]
    resp = client.post("/admin/devices/never-existed/revoke", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404


def test_get_admin_devices_lists_what_has_logged_in(client):
    login_resp = client.post("/auth/login", json={"role": "parent", "credential": settings.parent_password, "device_id": "dev-1"})
    token = login_resp.json()["access_token"]
    resp = client.get("/admin/devices", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert any(d["device_id"] == "dev-1" and d["revoked"] is False for d in body)


def test_admin_status_reports_device_counts(client):
    # Two devices: revoking one must not lock out the parent's OWN check of
    # the resulting counts, so the assertion below is made from the still-
    # trusted device's token, not the one being revoked.
    dev1 = client.post("/auth/login", json={"role": "parent", "credential": settings.parent_password, "device_id": "dev-1"}).json()["access_token"]
    dev2_headers = {"Authorization": "Bearer " + client.post(
        "/auth/login", json={"role": "parent", "credential": settings.parent_password, "device_id": "dev-2"},
    ).json()["access_token"]}

    client.post("/admin/devices/dev-1/revoke", headers={"Authorization": f"Bearer {dev1}"})

    body = client.get("/admin/status", headers=dev2_headers).json()
    assert body["devices"]["total"] == 2
    assert body["devices"]["revoked"] == 1


def test_child_role_cannot_reach_the_device_admin_endpoints(client):
    child_login = client.post("/auth/login", json={"role": "child", "credential": settings.child_pin, "device_id": "tablet-1"})
    child_token = child_login.json()["access_token"]
    headers = {"Authorization": f"Bearer {child_token}"}

    assert client.get("/admin/devices", headers=headers).status_code == 403
    assert client.post("/admin/devices/tablet-1/revoke", headers=headers).status_code == 403


@pytest.fixture(autouse=True)
def _reset_totp_step():
    """core/mfa_challenge.py's TOTP anti-replay tracker is a single
    process-global int — a fresh secret enrolled per test can still
    collide purely on wall-clock timestep with an unrelated test. See
    tests/test_recovery_router.py's identical fixture."""
    import core.mfa_challenge as mfa_challenge_module
    mfa_challenge_module._last_totp_step = None
    yield
    mfa_challenge_module._last_totp_step = None


def test_completing_mfa_still_carries_the_device_id_through(client):
    """The parent-with-MFA-enrolled path mints a parent_pending token first
    (routers/auth.py) and completes it via routers/mfa.py's TOTP verify —
    device_id must survive that hop, not just the direct no-MFA path the
    other tests above exercise."""
    import pyotp
    from services import mfa_service

    async def _enroll():
        async with client.db_factory() as session:
            secret, _ = await mfa_service.enroll_totp(session)
            await mfa_service.confirm_totp(session, pyotp.TOTP(secret).now())
            return secret

    secret = asyncio.run(_enroll())

    login_resp = client.post("/auth/login", json={"role": "parent", "credential": settings.parent_password, "device_id": "dev-1"})
    assert login_resp.status_code == 200
    body = login_resp.json()
    assert body["mfa_required"] is True
    pending_token = body["access_token"]

    code = pyotp.TOTP(secret).now()
    verify_resp = client.post(
        "/mfa/totp/authenticate/verify",
        json={"code": code},
        headers={"Authorization": f"Bearer {pending_token}"},
    )
    assert verify_resp.status_code == 200
    final_token = verify_resp.json()["access_token"]
    payload = decode_token(final_token)
    assert payload["device_id"] == "dev-1"

    from core.database import DeviceRecord

    async def _check():
        async with client.db_factory() as session:
            return await session.get(DeviceRecord, "dev-1")
    row = asyncio.run(_check())
    assert row is not None


def test_a_device_revoked_mid_login_cannot_complete_its_second_factor(client):
    """The defense-in-depth backstop, and a real race worth pinning.

    For an MFA-enrolled parent, login() checks device revocation right
    after the password verifies — which is BEFORE the parent_pending token
    is issued, so a device already revoked at that moment never gets one.
    This test covers the window that check cannot: the parent enters their
    password on the tablet, and *while* they are reaching for their
    authenticator, revokes that tablet from a different device.

    Nothing in routers/auth.py or routers/mfa.py handles that — the
    already-issued pending token is what carries the turn forward. What
    stops it is core/deps.py's per-request check, reached via
    require_mfa_pending -> _validate_token. That is the property this
    pins: revocation does not depend on catching a device at login time,
    because every subsequent request re-checks. It is also why moving
    login()'s own check later would buy nothing — this backstop already
    covers the outcome, so the earlier check exists purely to fail
    clearly rather than to be the thing that actually stops it."""
    import pyotp
    from core import device_registry
    from services import mfa_service

    # The tablet is already a known, registered device — a family that has
    # been using it, and only later turned MFA on. This ordering matters:
    # login() reaches touch() only when a REAL token is issued, so a device
    # whose very first login is an MFA one is not registered (and so not
    # revokable) until that login completes. See routers/auth.py's touch()
    # call site and routers/mfa.py's _issue_parent_token.
    first_login = client.post("/auth/login", json={"role": "parent", "credential": settings.parent_password, "device_id": "dev-1"})
    assert first_login.status_code == 200
    assert first_login.json().get("mfa_required") is False

    async def _enroll():
        async with client.db_factory() as session:
            secret, _ = await mfa_service.enroll_totp(session)
            await mfa_service.confirm_totp(session, pyotp.TOTP(secret).now())
            return secret

    secret = asyncio.run(_enroll())

    # Password step succeeds — the device is still trusted at this instant.
    login_resp = client.post("/auth/login", json={"role": "parent", "credential": settings.parent_password, "device_id": "dev-1"})
    assert login_resp.status_code == 200
    assert login_resp.json()["mfa_required"] is True
    pending_token = login_resp.json()["access_token"]

    # ...and only now does the parent revoke it from elsewhere.
    async def _revoke():
        async with client.db_factory() as session:
            return await device_registry.revoke(session, "dev-1")
    assert asyncio.run(_revoke()) is True

    # The pending token is real and correctly signed, and the TOTP code is
    # genuine — the ONLY thing refusing this is the device revocation.
    verify_resp = client.post(
        "/mfa/totp/authenticate/verify",
        json={"code": pyotp.TOTP(secret).now()},
        headers={"Authorization": f"Bearer {pending_token}"},
    )
    assert verify_resp.status_code == 401
    assert "revoked" in verify_resp.json()["detail"].lower()
