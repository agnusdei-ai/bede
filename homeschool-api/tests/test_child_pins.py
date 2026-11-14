"""
Per-child PINs (core/child_pin.py; owner decision 2026-11-07, #761 follow-up).

The gap: every child signed in with one shared CHILD_PIN and the session was
bound to a learner by the tablet's ChildLearnerBinding. A device id is a
client-held UUID, not a secret, so anyone with the shared PIN who learned
another tablet's id could sign in as that tablet's child.

Everything here runs over real HTTP through the assembled app (SQLite per
test). Learners are saved by the real parent route, PINs are set by the real
elevated parent route after a real /auth/elevate, and child tokens come from
the real /auth/login. Sample names only. Every guard was verified by
breaking it (see the PR description).
"""
import asyncio
import tempfile

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core import consent, device_registry
from core.config import settings
from core.database import Base, ChildPin, get_db
from core.security import create_access_token, decode_token
from core.student_keys import clear_cache

pytestmark = pytest.mark.real_consent

ONE = "Sample Learner One"
TWO = "Sample Learner Two"
THREE = "Sample Learner Three"  # never gets a PIN: the shared-PIN control
TABLET_A = "sample-tablet-a"
TABLET_B = "sample-tablet-b"
TABLET_C = "sample-tablet-c"
PIN_ONE = "481937"
PIN_TWO = "730582"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    from core.middleware import reset_rate_limiter
    reset_rate_limiter()
    device_registry._set_cache(set())
    monkeypatch.setattr(settings, "hosted_profile", False)
    monkeypatch.setattr(settings, "educator_pilot_enabled", False)
    monkeypatch.setattr(settings, "demo_pin", "")
    monkeypatch.setattr(settings, "consent_install_ack_hash", "")
    monkeypatch.setattr(settings, "consent_install_ack_at", "")
    monkeypatch.setattr(settings, "elevation_enforced", True)
    # The per-IP auth limiter is not what these tests are about, and the
    # lockout tests need more than ten attempts a minute to reach it.
    monkeypatch.setattr(settings, "rate_limit_auth_per_minute", 10_000)
    yield
    device_registry._set_cache(set())
    reset_rate_limiter()


@pytest.fixture
def ctx(monkeypatch, test_client_with_database_context):
    import main
    import core.database as database_module
    import core.encryption as encryption_module

    url = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/child_pins.sqlite"

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
    if encryption_module._DATA_KEY is None:
        from Crypto.Random import get_random_bytes
        monkeypatch.setattr(encryption_module, "_DATA_KEY", get_random_bytes(32))
    clear_cache()

    async def _override():
        async with factory() as session:
            yield session

    main.app.dependency_overrides[get_db] = _override
    with test_client_with_database_context(main.app, engine) as c:
        parent = _parent_headers()
        cfg = lambda n: {"student_name": n, "subjects": ["history"], "grade": "3", "grade_stage": "3-5"}
        saved = c.post("/pod/configs", headers=parent, json={
            "configs": [cfg(ONE), cfg(TWO), cfg(THREE)], "consent_notice_hash": consent.notice_hash(),
        })
        assert saved.status_code == 204, saved.text
        elevated = c.post("/auth/elevate", json={"password": settings.parent_password}, headers=parent)
        assert elevated.status_code == 200, elevated.text

        def rows():
            async def _q():
                async with factory() as s:
                    return {r.student_name: r for r in (await s.execute(select(ChildPin))).scalars().all()}
            return c.portal.call(_q)

        yield c, parent, rows
        main.app.dependency_overrides.pop(get_db, None)
    clear_cache()


def _parent_headers():
    return {"Authorization": f"Bearer {create_access_token({'sub': 'parent', 'role': 'parent'})}"}


def _set_pin(c, parent, name, pin):
    return c.put(f"/pod/child-pins/{name}", json={"pin": pin}, headers=parent)


def _assign(c, parent, device, name):
    r = c.post(f"/auth/child-devices/{device}/learner", json={"student_name": name}, headers=parent)
    assert r.status_code == 200, r.text


def _login(c, credential, *, name=None, device=None):
    body = {"role": "child", "credential": credential}
    if name is not None:
        body["student_name"] = name
    if device is not None:
        body["device_id"] = device
    return c.post("/auth/login", json=body)


def _headers(resp):
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _reads(c, headers, name):
    return c.get(f"/pod/configs/{name}", headers=headers).status_code


# ── Own PIN ─────────────────────────────────────────────────────────────────

def test_own_pin_signs_in_as_that_learner_only(ctx):
    c, parent, _ = ctx
    assert _set_pin(c, parent, ONE, PIN_ONE).status_code == 204
    resp = _login(c, PIN_ONE, name=ONE)
    claims = decode_token(resp.json()["access_token"])
    assert claims["learner"] == ONE and claims["role"] == "child"
    headers = _headers(resp)
    assert _reads(c, headers, ONE) == 200
    assert _reads(c, headers, TWO) == 404  # bound server-side to the verified learner
    assert c.get("/auth/validate", headers=headers).status_code == 200


def test_own_pin_needs_no_tablet_binding(ctx):
    """Ease of use: the child's PIN is the credential; no pairing ceremony."""
    c, parent, _ = ctx
    _set_pin(c, parent, ONE, PIN_ONE)
    headers = _headers(_login(c, PIN_ONE, name=ONE, device=TABLET_C))  # unbound tablet
    assert _reads(c, headers, ONE) == 200


# ── Shared PIN ──────────────────────────────────────────────────────────────

def test_shared_pin_refused_for_a_learner_with_own_pin(ctx):
    c, parent, _ = ctx
    _set_pin(c, parent, ONE, PIN_ONE)
    resp = _login(c, settings.child_pin, name=ONE, device=TABLET_A)
    assert resp.status_code == 401 and resp.json()["detail"] == "Invalid credentials"


def test_shared_pin_still_works_byte_for_byte_for_a_learner_without_one(ctx):
    """THREE has no PIN of its own: shared PIN + tablet binding exactly as
    before, with or without a name typed, while ONE has a PIN."""
    c, parent, _ = ctx
    _set_pin(c, parent, ONE, PIN_ONE)
    _assign(c, parent, TABLET_C, THREE)
    for name in (None, THREE):
        resp = _login(c, settings.child_pin, name=name, device=TABLET_C)
        claims = decode_token(resp.json()["access_token"])
        assert "learner" not in claims and "learner_nonce" in claims
        assert _reads(c, _headers(resp), THREE) == 200


def test_device_id_spoofing_with_the_shared_pin_fails_for_a_pin_protected_learner(ctx):
    """The #761 follow-up itself: someone with the shared PIN who knows ONE's
    tablet id signs in 'as that tablet' and gets nothing of ONE's."""
    c, parent, _ = ctx
    _assign(c, parent, TABLET_A, ONE)
    before = _headers(_login(c, settings.child_pin, device=TABLET_A))
    assert _reads(c, before, ONE) == 200  # the gap, before the PIN exists
    _set_pin(c, parent, ONE, PIN_ONE)
    assert _reads(c, before, ONE) == 404  # old shared-PIN token ended
    assert _login(c, settings.child_pin, device=TABLET_A).status_code == 401
    assert _login(c, settings.child_pin, name=ONE, device=TABLET_A).status_code == 401
    # Even a token minted by hand with the tablet's current nonce is refused:
    # the shared-PIN path never reaches a PIN-protected learner.
    async def _nonce():
        from core.database import AsyncSessionLocal, ChildLearnerBinding
        async with AsyncSessionLocal() as s:
            return (await s.get(ChildLearnerBinding, TABLET_A)).nonce
    forged = {"Authorization": "Bearer " + create_access_token(
        {"sub": "child", "role": "child", "device_id": TABLET_A, "learner_nonce": c.portal.call(_nonce)})}
    assert _reads(c, forged, ONE) == 404


def test_a_siblings_pin_cannot_sign_in_as_another_child(ctx):
    c, parent, _ = ctx
    _set_pin(c, parent, ONE, PIN_ONE)
    _set_pin(c, parent, TWO, PIN_TWO)
    assert _login(c, PIN_TWO, name=ONE).status_code == 401
    two = _headers(_login(c, PIN_TWO, name=TWO))
    assert _reads(c, two, ONE) == 404


def test_a_forged_learner_claim_is_refused(ctx):
    c, parent, _ = ctx
    _set_pin(c, parent, ONE, PIN_ONE)
    forged = {"Authorization": "Bearer " + create_access_token(
        {"sub": "child", "role": "child", "learner": ONE, "learner_pin_nonce": "guess"})}
    assert c.get("/auth/validate", headers=forged).status_code == 401


# ── Change / clear ends sessions ────────────────────────────────────────────

def test_changing_a_pin_ends_only_that_childs_sessions(ctx):
    c, parent, _ = ctx
    _set_pin(c, parent, ONE, PIN_ONE)
    _set_pin(c, parent, TWO, PIN_TWO)
    one = _headers(_login(c, PIN_ONE, name=ONE))
    two = _headers(_login(c, PIN_TWO, name=TWO))
    assert _set_pin(c, parent, ONE, "592047").status_code == 204
    assert c.get("/auth/validate", headers=one).status_code == 401
    assert _reads(c, one, ONE) == 401
    assert _reads(c, two, TWO) == 200  # sibling untouched
    assert _login(c, PIN_ONE, name=ONE).status_code == 401  # old PIN dead
    assert _reads(c, _headers(_login(c, "592047", name=ONE)), ONE) == 200


def test_clearing_a_pin_ends_its_sessions_and_restores_the_shared_pin(ctx):
    c, parent, rows = ctx
    _assign(c, parent, TABLET_A, ONE)
    pre_pin_shared = _headers(_login(c, settings.child_pin, device=TABLET_A))
    _set_pin(c, parent, ONE, PIN_ONE)
    one = _headers(_login(c, PIN_ONE, name=ONE))
    assert c.delete(f"/pod/child-pins/{ONE}", headers=parent).status_code == 204
    assert ONE not in rows()
    assert _reads(c, one, ONE) == 401
    # A shared-PIN token from before the PIN existed does not come back to
    # life when the PIN is cleared: the tablet's binding nonce was rotated.
    assert _reads(c, pre_pin_shared, ONE) == 404
    assert _login(c, PIN_ONE, name=ONE).status_code == 401
    # Setting the same PIN again cannot revive the old token: a fresh nonce.
    _set_pin(c, parent, ONE, PIN_ONE)
    assert _reads(c, one, ONE) == 401
    c.delete(f"/pod/child-pins/{ONE}", headers=parent)
    shared = _headers(_login(c, settings.child_pin, device=TABLET_A))
    assert _reads(c, shared, ONE) == 200
    assert c.delete(f"/pod/child-pins/{ONE}", headers=parent).status_code == 404


# ── Lockout ─────────────────────────────────────────────────────────────────

def test_lockout_is_per_child_persisted_and_survives_ip_rotation(ctx):
    from core import child_pin, child_throttle
    c, parent, rows = ctx
    _set_pin(c, parent, ONE, PIN_ONE)
    _set_pin(c, parent, TWO, PIN_TWO)
    for i in range(child_pin.FAILURE_THRESHOLD):
        c._transport.client = (f"10.0.0.{i + 2}", 40000 + i)  # a new source address each try
        assert _login(c, "000123", name=ONE).status_code == 401
    c._transport.client = ("testclient", 50000)
    assert rows()[ONE].failure_count == child_pin.FAILURE_THRESHOLD
    assert rows()[ONE].locked_until is not None
    child_throttle.reset()  # in-process state gone, as after a restart
    locked = _login(c, PIN_ONE, name=ONE)  # the RIGHT pin, while locked
    assert locked.status_code == 401 and locked.json()["detail"] == "Invalid credentials"
    # The sibling is not locked.
    assert rows()[TWO].failure_count == 0
    assert _login(c, PIN_TWO, name=TWO).status_code == 200
    status = c.get("/pod/child-pins", headers=parent).json()["children"]
    assert status[ONE]["locked"] is True and status[TWO]["locked"] is False
    # A parent setting the PIN again clears the lock.
    _set_pin(c, parent, ONE, PIN_ONE)
    assert _login(c, PIN_ONE, name=ONE).status_code == 200


def test_no_enumeration_difference_between_wrong_pin_unknown_child_and_locked(ctx):
    from core import child_pin
    c, parent, _ = ctx
    _set_pin(c, parent, ONE, PIN_ONE)
    _set_pin(c, parent, TWO, PIN_TWO)
    for _ in range(child_pin.FAILURE_THRESHOLD):
        _login(c, "000123", name=TWO)
    responses = [
        _login(c, "000123", name=ONE),               # wrong pin
        _login(c, "000123", name="Nobody Sample"),  # unknown child
        _login(c, PIN_TWO, name=TWO),                # locked, right pin
        _login(c, settings.child_pin, name=ONE),     # shared pin, protected child
    ]
    assert {(r.status_code, r.text) for r in responses} == {(401, '{"detail":"Invalid credentials"}')}


# ── Hosted pairing still applies ────────────────────────────────────────────

def test_hosted_deployment_needs_the_childs_pin_and_an_approved_tablet(ctx, monkeypatch):
    c, parent, _ = ctx
    _set_pin(c, parent, ONE, PIN_ONE)
    monkeypatch.setattr(settings, "hosted_profile", True)
    # Wrong PIN from an unknown tablet: the plain refusal, no pending row made.
    assert _login(c, "000123", name=ONE, device=TABLET_A).status_code == 401
    assert c.get("/auth/child-devices", headers=parent).json()["devices"] == []
    # Right PIN, unpaired tablet: waits for a parent.
    assert _login(c, PIN_ONE, name=ONE, device=TABLET_A).status_code == 403
    assert c.post(f"/auth/child-devices/{TABLET_A}/approve", headers=parent).status_code == 200
    first = _login(c, PIN_ONE, name=ONE, device=TABLET_A)
    assert first.status_code == 200 and first.json()["device_token"]
    device_token = first.json()["device_token"]
    assert _reads(c, _headers(first), ONE) == 200
    # Later sign-ins need the device token AND the child's PIN.
    body = {"role": "child", "credential": PIN_ONE, "student_name": ONE, "device_id": TABLET_A}
    assert c.post("/auth/login", json=body).status_code == 403
    assert c.post("/auth/login", json={**body, "device_token": device_token}).status_code == 200
    assert c.post("/auth/login", json={**body, "credential": settings.child_pin,
                                       "device_token": device_token}).status_code == 401
    # Revoking the tablet ends the PIN session too.
    session = _headers(c.post("/auth/login", json={**body, "device_token": device_token}))
    assert c.post(f"/auth/child-devices/{TABLET_A}/revoke", headers=parent).status_code == 200
    assert _reads(c, session, ONE) == 401


# ── Management routes ───────────────────────────────────────────────────────

def test_management_routes_are_parent_only_and_need_elevation(ctx):
    c, parent, _ = ctx
    _set_pin(c, parent, ONE, PIN_ONE)
    child = _headers(_login(c, PIN_ONE, name=ONE))
    for headers in (child, {}):
        assert c.get("/pod/child-pins", headers=headers).status_code in (401, 403)
        assert _set_pin(c, headers, TWO, PIN_TWO).status_code in (401, 403)
        assert c.delete(f"/pod/child-pins/{ONE}", headers=headers).status_code in (401, 403)
    unelevated = _parent_headers()
    r = _set_pin(c, unelevated, TWO, PIN_TWO)
    assert r.status_code == 403 and r.json()["detail"]["elevation_required"] is True
    assert c.delete(f"/pod/child-pins/{ONE}", headers=unelevated).status_code == 403
    assert c.get("/pod/child-pins", headers=unelevated).status_code == 200


@pytest.mark.parametrize("bad", [
    "123456",  # sequential
    "121212",  # repeated block
    "602656",  # published example
    "12345",   # too short
    "4819370123456",  # too long
    "abcdef",
])
def test_weak_or_published_pins_are_refused(ctx, bad):
    c, parent, rows = ctx
    assert _set_pin(c, parent, ONE, bad).status_code == 400
    assert ONE not in rows()


def test_pins_that_collide_with_another_credential_are_refused(ctx, monkeypatch):
    c, parent, rows = ctx
    monkeypatch.setattr(settings, "child_pin", "385072")
    monkeypatch.setattr(settings, "sandbox_pin", "264917")
    monkeypatch.setattr(settings, "demo_pin", "917364")
    _set_pin(c, parent, TWO, PIN_TWO)
    for colliding in ("385072", "264917", "917364", PIN_TWO):
        r = _set_pin(c, parent, ONE, colliding)
        assert r.status_code == 400 and colliding not in r.text
    monkeypatch.setattr(settings, "parent_password", "572913")
    assert _set_pin(c, parent, ONE, "572913").status_code == 400
    assert ONE not in rows()


def test_setting_a_pin_for_an_unknown_student_is_refused(ctx):
    c, parent, rows = ctx
    assert _set_pin(c, parent, "Nobody Sample", PIN_ONE).status_code == 404
    assert not rows()


def test_the_pin_never_appears_in_responses_storage_or_audit(ctx):
    c, parent, rows = ctx
    r = _set_pin(c, parent, ONE, PIN_ONE)
    assert r.status_code == 204 and r.content == b""
    status = c.get("/pod/child-pins", headers=parent)
    assert PIN_ONE not in status.text
    assert set(status.json()["children"][ONE]) == {"has_pin", "locked", "changed_at"}
    row = rows()[ONE]
    assert PIN_ONE.encode() not in row.pin_hash and PIN_ONE.encode() not in row.pin_salt
    login = _login(c, PIN_ONE, name=ONE)
    assert PIN_ONE not in login.text
    _login(c, "000123", name=ONE)
    audit = c.get("/admin/audit?limit=500", headers=parent)
    assert audit.status_code == 200, audit.text
    assert "child_pin.set" in audit.text
    assert PIN_ONE not in audit.text


# ── Deletion / export ───────────────────────────────────────────────────────

def test_deleting_a_student_removes_their_pin_and_export_withholds_it(ctx):
    c, parent, rows = ctx
    _set_pin(c, parent, ONE, PIN_ONE)
    exported = c.get(f"/pod/students/{ONE}/review", headers=parent)
    assert exported.status_code == 200, exported.text
    pins = exported.json()["tables"]["child_pins"]
    assert len(pins) == 1
    assert {pins[0][k] for k in ("pin_hash", "pin_salt", "nonce")} == {"withheld: sign-in credential, not exported"}
    assert c.delete(f"/pod/configs/{ONE}", headers=parent).status_code == 204
    assert ONE not in rows()
    assert _login(c, PIN_ONE, name=ONE).status_code == 401
