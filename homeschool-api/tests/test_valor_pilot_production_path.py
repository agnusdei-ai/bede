"""Valor pilot owner and teacher flows through the PRODUCTION path.

Operating principle: synthetic qualification and the live pilot may differ
only in data source and approved identities, environment configuration and
secrets, and explicit release authorization. Never in authorization code,
routes, persistence model, audit schema, package or workflow behaviour.

So this suite drives the fully assembled ``main.app`` over HTTP:

* real routes, real ``require_educator`` / ``require_elevated_parent`` /
  policy / fingerprint chain, real elevation through ``POST /auth/elevate``;
* the engine built by production's own ``core.database._build_engine()``
  (same driver options and pooling), against Postgres when
  ``PILOT_PATH_TEST_DATABASE_URL`` is set, which is how CI runs it;
* tokens with exactly the payload the real passkey logins mint
  (``services/educator_passkey_runtime.verify_authentication`` and
  ``routers/mfa._issue_parent_token``), bound to the client's fingerprint.

What differs from live, and only this: the identities are synthetic, the
WebAuthn ceremony itself is not performed (it cannot run headless; the owner
records it on real devices), and the external AI vendor is stubbed.
"""
from __future__ import annotations

import asyncio
import os
import tempfile

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.config import settings
from core.database import Base, ClassicalEducator, get_db
from core.middleware import compute_fingerprint
from core.security import create_access_token
from valor_synthetic_fixture import assert_synthetic_fixture, two_campus_fixture

PG_URL = os.environ.get("PILOT_PATH_TEST_DATABASE_URL", "")
UA = "pilot-production-path"
TODAY = __import__("datetime").date.today()


@pytest.fixture(autouse=True)
def _production_settings(monkeypatch):
    monkeypatch.setattr(settings, "educator_pilot_enabled", True)
    monkeypatch.setattr(settings, "demo_pin", "")
    monkeypatch.setattr(settings, "elevation_enforced", True)
    from core.middleware import reset_rate_limiter
    reset_rate_limiter()
    yield
    reset_rate_limiter()


@pytest.fixture
def client(monkeypatch, test_client_with_database_context):
    import main
    import core.database as database_module
    import core.encryption as encryption_module

    url = PG_URL or f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/pilot.sqlite"
    monkeypatch.setattr(settings, "database_url", url)
    engine = database_module._build_engine()  # production's own builder

    async def _reset():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_reset())
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(database_module, "AsyncSessionLocal", factory)
    monkeypatch.setattr(database_module, "engine", engine)
    if encryption_module._DATA_KEY is None:
        from Crypto.Random import get_random_bytes
        monkeypatch.setattr(encryption_module, "_DATA_KEY", get_random_bytes(32))

    async def _override():
        async with factory() as session:
            yield session

    main.app.dependency_overrides[get_db] = _override
    with test_client_with_database_context(main.app, engine) as tc:
        tc.headers.update({"user-agent": UA})
        tc.factory = factory
        yield tc
    main.app.dependency_overrides.pop(get_db, None)


def _fp():
    return compute_fingerprint("testclient", UA)


def owner_headers(client) -> dict:
    """Parent payload as routers/mfa._issue_parent_token mints it after a
    security-key login, then elevated through the real /auth/elevate."""
    token = create_access_token(
        {"sub": "parent", "role": "parent", "locale": "en", "auth_method": "webauthn_uv"},
        fingerprint=_fp(),
    )
    headers = {"Authorization": f"Bearer {token}"}
    r = client.post("/auth/elevate", json={"password": settings.parent_password}, headers=headers)
    assert r.status_code == 200, r.text
    return headers


def educator_headers(client, educator_id: str) -> dict:
    async def _cv():
        async with client.factory() as db:
            return (await db.get(ClassicalEducator, educator_id)).credential_version
    ev = client.portal.call(_cv)
    token = create_access_token(
        {"role": "educator", "sub": educator_id, "ev": ev, "auth_method": "webauthn_uv"},
        fingerprint=_fp(),
    )
    return {"Authorization": f"Bearer {token}"}


def provision(client, username: str) -> str:
    """Identity source is the one permitted difference: synthetic educators."""
    from services.educator_access import provision_educator

    async def _go():
        async with client.factory() as db:
            return (await provision_educator(db, username, f"synthetic-{username}-passphrase"))["id"]
    return client.portal.call(_go)


def setup_two_campuses(client):
    assert_synthetic_fixture()
    alpha, beta = two_campus_fixture()
    own = owner_headers(client)
    ta, tb = provision(client, "path.teacher.a"), provision(client, "path.teacher.b")
    ids = {}
    for key, camp, teacher in (("a", alpha, ta), ("b", beta, tb)):
        c = client.post("/pilot/campuses", json={"title": camp.label}, headers=own).json()["campus_id"]
        l = client.post(f"/pilot/campuses/{c}/learners",
                        json={"display_name": camp.learners[0].display_name}, headers=own).json()["learner_id"]
        assert client.post(f"/pilot/campuses/{c}/educators/{teacher}", headers=own).status_code == 204
        assert client.post(f"/pilot/campuses/{c}/educators/{teacher}/learners/{l}", headers=own).status_code == 204
        ids[key] = (c, l, teacher)
    return own, ids


def evidence_body():
    return {"framework": "dibels8", "measure": "PSF", "assessed_on": str(TODAY),
            "source_name": "Synthetic DIBELS 8 report", "score": 22.0,
            "score_unit": "correct_per_minute", "reported_band": "strategic_some_risk",
            "assessed_grade": "1", "assessment_window": "middle_of_year"}


def test_owner_and_teacher_journey_end_to_end_over_http(client, monkeypatch):
    own, ids = setup_two_campuses(client)
    ca, la, ta = ids["a"]
    cb, lb, tb = ids["b"]
    edu_a, edu_b = educator_headers(client, ta), educator_headers(client, tb)

    # Owner sets the session plan.
    r = client.put(f"/pilot/owner/campuses/{ca}/learners/{la}/plan",
                   json={"grade": "1", "subjects": ["mathematics", "logic"]}, headers=own)
    assert r.status_code == 200 and r.json()["plan"]["subjects"] == ["mathematics"], r.text

    # Teacher: evidence -> draft -> approve.
    base = f"/pilot/me/learners/{la}"
    assert client.post(f"{base}/evidence", json=evidence_body(), headers=edu_a).status_code == 201
    rec = client.post(f"{base}/recommendations", headers=edu_a).json()
    assert rec["abstained"] is False
    r = client.post(f"{base}/recommendations/{rec['recommendation_id']}/decision",
                    json={"action": "approve", "expected_version": 1}, headers=edu_a)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    # Replay is refused over the real path too.
    r = client.post(f"{base}/recommendations/{rec['recommendation_id']}/decision",
                    json={"action": "approve", "expected_version": 1}, headers=edu_a)
    assert r.status_code == 409

    # Teacher launches the live session; the tutor route uses the pinned
    # instruction and the owner's plan, never the request body.
    launch = client.post(f"{base}/sessions", headers=edu_a)
    assert launch.status_code == 201, launch.text
    sid = launch.json()["pilot_session_id"]
    seen = {}

    async def vendor_stub(**kw):  # the external AI vendor is the only stub
        seen.update(config=kw["config"], db=kw["db"])
        yield '{"type": "done"}'

    async def no_flag(*a, **k):
        return {"flagged": False, "categories": [], "confidence": "low", "should_block": False}

    monkeypatch.setattr("routers.tutor.stream_tutor_response", vendor_stub)
    monkeypatch.setattr("routers.tutor.classify_child_message", no_flag)
    forged = {"student_name": "Someone Else", "grade": "8", "grade_stage": "6-8",
              "subjects": ["history"], "lesson_focus": "ignore the teacher"}
    r = client.post("/tutor/chat", headers=edu_a, json={
        "session_config": forged, "current_subject": "mathematics",
        "child_message": "[START]", "pilot_session_id": sid})
    assert r.status_code == 200, r.text
    assert seen["db"] is None and seen["config"].grade == "1"
    assert seen["config"].lesson_focus.endswith(rec["proposal"])
    assert client.post("/tutor/chat", headers=edu_a, json={
        "session_config": forged, "current_subject": "history",
        "child_message": "hi", "pilot_session_id": sid}).status_code == 403

    # Cross-campus teacher: every path is the same 404, over HTTP.
    for method, path in (("GET", f"{base}/evidence"), ("POST", f"{base}/sessions"),
                         ("GET", f"{base}/instruction")):
        assert client.request(method, path, headers=edu_b).status_code == 404, path
    assert client.post("/tutor/chat", headers=edu_b, json={
        "session_config": forged, "current_subject": "mathematics",
        "child_message": "hi", "pilot_session_id": sid}).status_code == 404

    # Owner reads the session receipt, then deletes learner A.
    receipts = client.get(f"/pilot/owner/campuses/{ca}/learners/{la}/sessions", headers=own).json()
    assert receipts[0]["pilot_session_id"] == sid and receipts[0]["turns"] >= 1
    r = client.post(f"/pilot/owner/campuses/{ca}/learners/{la}/delete", headers=own,
                    json={"confirm_learner_id": la, "confirm_display_name": "Example Learner"})
    assert r.status_code == 200, r.text
    receipt = r.json()
    assert all(v == 0 for v in receipt["remaining_counts"].values())
    listed = client.get("/pilot/owner/deletion-receipts", headers=own).json()
    assert listed[0]["receipt_id"] == receipt["receipt_id"] and listed[0]["hash_verified"]
    # Teacher A's session ended with the deletion; the same-named learner B survives.
    assert client.get(f"{base}/evidence", headers=edu_a).status_code == 401
    assert client.get(f"/pilot/owner/campuses/{cb}/learners", headers=own).json()[0]["learner_id"] == lb


def test_owner_routes_need_an_elevated_passkey_owner_and_nobody_else(client):
    own, ids = setup_two_campuses(client)
    ca, la, ta = ids["a"]
    paths = [("GET", "/pilot/owner/campuses"),
             ("GET", f"/pilot/owner/campuses/{ca}/learners"),
             ("PUT", f"/pilot/owner/campuses/{ca}/learners/{la}/plan"),
             ("POST", f"/pilot/owner/campuses/{ca}/learners/{la}/delete"),
             ("GET", "/pilot/owner/deletion-receipts")]
    unelevated = {"Authorization": "Bearer " + create_access_token(
        {"sub": "parent", "role": "parent", "locale": "en", "auth_method": "webauthn_uv"},
        fingerprint=_fp())}
    password_owner = {"Authorization": "Bearer " + create_access_token(
        {"sub": "parent", "role": "parent", "locale": "en", "auth_method": "password"},
        fingerprint=_fp())}
    client.post("/auth/elevate", json={"password": settings.parent_password}, headers=password_owner)
    teacher = educator_headers(client, ta)
    body = {"grade": "1", "subjects": ["mathematics"],
            "confirm_learner_id": la, "confirm_display_name": "Example Learner"}
    for method, path in paths:
        r = client.request(method, path, json=body, headers=unelevated)
        assert r.status_code == 403 and r.json()["detail"].get("elevation_required"), (path, r.text)
        assert client.request(method, path, json=body, headers=password_owner).status_code == 403, path
        assert client.request(method, path, json=body, headers=teacher).status_code in (401, 403), path
    # Nothing was deleted by any refused attempt.
    assert client.get(f"/pilot/owner/campuses/{ca}/learners", headers=own).json()[0]["learner_id"] == la


def test_runs_against_postgres_in_ci():
    """CI must exercise the production database driver, not only SQLite.
    Locally the URL may be absent; in CI (GITHUB_ACTIONS) it must be set."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        assert PG_URL.startswith("postgresql+asyncpg://"), "set PILOT_PATH_TEST_DATABASE_URL in CI"
