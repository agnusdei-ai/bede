"""
Issue #761: a child session may read or change only the learner its device is
bound to, on BOTH name-keyed pod routes:

    GET   /pod/configs/{student_name}
    PATCH /pod/configs/{student_name}/voice-narration

Everything runs over real HTTP through the assembled app (SQLite per test),
with learners assigned through the real parent route and child tokens issued
by the real /auth/login. tests/test_child_learner_binding.py calls the
dependency directly; this file proves the routes actually invoke it, and that
a refused PATCH writes nothing. Sample names only.
"""
import asyncio
import tempfile

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core import consent, device_registry
from core.config import settings
from core.database import Base, get_db
from core.security import create_access_token, decode_token
from core.student_keys import clear_cache

pytestmark = pytest.mark.real_consent

ONE = "Sample Learner One"
TWO = "Sample Learner Two"
TABLET_A = "sample-tablet-a"
TABLET_B = "sample-tablet-b"


def _parent():
    return {"Authorization": f"Bearer {create_access_token({'sub': 'parent', 'role': 'parent'})}"}


def _bearer(claims):
    return {"Authorization": f"Bearer {create_access_token(claims)}"}


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
    yield
    device_registry._set_cache(set())
    reset_rate_limiter()


@pytest.fixture
def client(monkeypatch, test_client_with_database_context):
    import main
    import core.database as database_module
    import core.encryption as encryption_module

    url = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/pod_scope.sqlite"

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
        cfg = lambda n: {"student_name": n, "subjects": ["history"], "grade": "3", "grade_stage": "3-5"}
        saved = c.post("/pod/configs", headers=_parent(), json={
            "configs": [cfg(ONE), cfg(TWO)], "consent_notice_hash": consent.notice_hash(),
        })
        assert saved.status_code == 204, saved.text
        yield c
        main.app.dependency_overrides.pop(get_db, None)
    clear_cache()


def _assign(c, device, name):
    r = c.post(f"/auth/child-devices/{device}/learner", json={"student_name": name}, headers=_parent())
    assert r.status_code == 200, r.text


def _child_login(c, device):
    r = c.post("/auth/login", json={"role": "child", "credential": settings.child_pin, "device_id": device})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, decode_token(token)


def _narration(c, name):
    r = c.get(f"/pod/configs/{name}", headers=_parent())
    assert r.status_code == 200, r.text
    return r.json()["voice_narration_enabled"]


def _patch(c, name, headers, value=False):
    return c.patch(f"/pod/configs/{name}/voice-narration", json={"voice_narration_enabled": value}, headers=headers)


# ── Positive paths ──────────────────────────────────────────────────────────

def test_parent_reads_and_patches_every_learner(client):
    for name in (ONE, TWO):
        assert client.get(f"/pod/configs/{name}", headers=_parent()).status_code == 200
        assert _patch(client, name, _parent()).status_code == 204
        assert _narration(client, name) is False


def test_child_reads_and_patches_only_its_own_learner(client):
    _assign(client, TABLET_A, ONE)
    child, _ = _child_login(client, TABLET_A)
    own = client.get(f"/pod/configs/{ONE}", headers=child)
    assert own.status_code == 200 and own.json()["student_name"] == ONE
    assert _patch(client, ONE, child).status_code == 204
    assert _narration(client, ONE) is False


# ── Sibling ─────────────────────────────────────────────────────────────────

def test_child_cannot_read_or_patch_a_sibling(client):
    _assign(client, TABLET_A, ONE)
    child, _ = _child_login(client, TABLET_A)
    assert client.get(f"/pod/configs/{TWO}", headers=child).status_code == 404
    assert _patch(client, TWO, child).status_code == 404
    assert _narration(client, TWO) is True  # nothing written


# ── Same learner name, separate scope ───────────────────────────────────────

def test_scope_is_the_device_binding_not_the_learner_name(client):
    """Two tablets bound to the same learner name are separate scopes. A token
    carrying tablet A's nonce under tablet B's device id is refused, and
    rebinding tablet B kills only tablet B's tokens."""
    _assign(client, TABLET_A, ONE)
    _assign(client, TABLET_B, ONE)
    a_headers, a_claims = _child_login(client, TABLET_A)
    _, b_claims = _child_login(client, TABLET_B)
    assert a_claims["learner_nonce"] != b_claims["learner_nonce"]

    spliced = _bearer({"sub": "child", "role": "child", "device_id": TABLET_B,
                       "learner_nonce": a_claims["learner_nonce"]})
    assert client.get(f"/pod/configs/{ONE}", headers=spliced).status_code == 404
    assert _patch(client, ONE, spliced).status_code == 404

    _assign(client, TABLET_B, TWO)
    old_b = _bearer({"sub": "child", "role": "child", "device_id": TABLET_B,
                     "learner_nonce": b_claims["learner_nonce"]})
    assert client.get(f"/pod/configs/{ONE}", headers=old_b).status_code == 404
    assert client.get(f"/pod/configs/{ONE}", headers=a_headers).status_code == 200
    assert _narration(client, ONE) is True


def test_a_non_household_role_naming_the_same_learner_is_refused(client):
    """An educator (separate campus/grant domain) naming a household learner
    gets nothing from these routes; its own grant checks live elsewhere."""
    educator = _bearer({"sub": "sample-educator", "role": "educator"})
    assert client.get(f"/pod/configs/{ONE}", headers=educator).status_code in (401, 403, 404)
    assert _patch(client, ONE, educator).status_code in (401, 403, 404)
    assert _narration(client, ONE) is True


# ── Unassigned, rotated, revoked ────────────────────────────────────────────

def test_unassigned_device_and_legacy_tokens_are_refused(client):
    child, claims = _child_login(client, TABLET_A)  # no binding exists
    assert "learner_nonce" not in claims
    legacy = _bearer({"sub": "child", "role": "child"})  # pre-binding token, no device
    for headers in (child, legacy):
        for name in (ONE, TWO):
            assert client.get(f"/pod/configs/{name}", headers=headers).status_code == 403
            assert _patch(client, name, headers).status_code == 403
    assert _narration(client, ONE) is True and _narration(client, TWO) is True


def test_reassigning_the_device_rotates_the_nonce_and_kills_old_tokens(client):
    _assign(client, TABLET_A, ONE)
    old, _ = _child_login(client, TABLET_A)
    _assign(client, TABLET_A, ONE)  # same learner, fresh nonce
    assert client.get(f"/pod/configs/{ONE}", headers=old).status_code == 404
    assert _patch(client, ONE, old).status_code == 404
    assert _narration(client, ONE) is True


def test_revoked_device_is_refused(client):
    _assign(client, TABLET_A, ONE)
    child, _ = _child_login(client, TABLET_A)
    device_registry._set_cache({TABLET_A})
    assert client.get(f"/pod/configs/{ONE}", headers=child).status_code in (401, 403)
    assert _patch(client, ONE, child).status_code in (401, 403)
    device_registry._set_cache(set())
    assert _narration(client, ONE) is True
