"""
The health check must be able to FAIL.

This file exists because of a live outage on 2026-08-04 that was diagnosed
for an hour against a dashboard reading "Deployed ✓" the entire time. The
platform was not lying about what it measured; it was measuring nothing.
`render.yaml`'s `healthCheckPath` points at `/health`, and `/health` was:

    @app.get("/health")
    async def health():
        return {"status": "ok"}

An unconditional 200. Every real endpoint in this API needs the database —
there is no in-memory fallback, by explicit design (see core/database.py) —
so an instance that cannot reach Postgres cannot serve a single request. It
still passed its own health check, so the platform kept it marked healthy,
kept routing to it, never restarted it, and never alerted. The green badge
then became *evidence* during triage, and it pointed away from the database
for the first hour of the investigation.

The class of bug matters more than the instance: a check that cannot fail is
indistinguishable from a check that passes, and the difference only shows up
on the day it needed to fail. So the assertions here are mostly about the
FAILURE path, which is the one that never ran in production.

The plan assertions at the bottom cover a second, coupled trap found the
same day — see their own docstrings.
"""
import contextlib
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import main

_REPO = Path(__file__).resolve().parents[2]
_RENDER_YAML = _REPO / "render.yaml"


def _session_factory(on_execute):
    """Stand in for main.AsyncSessionLocal.

    Deliberately mimics the real `async with AsyncSessionLocal() as db`
    shape rather than patching the endpoint's internals, so these tests
    still fail if the endpoint stops opening a session at all — which is
    the exact regression that would silently restore the old behaviour.
    """
    class _Session:
        async def execute(self, *_args, **_kwargs):
            return await on_execute()

    @contextlib.asynccontextmanager
    async def _factory():
        yield _Session()

    # AsyncSessionLocal is called as AsyncSessionLocal(), and the result is
    # used as an async context manager — so the factory itself must be the
    # callable, not the context manager.
    return lambda: _factory()


# TestClient is used WITHOUT a `with` block on purpose: entering it runs the
# app's lifespan, which requires a real Postgres. These tests are about the
# endpoint's own behaviour, not startup.
client = TestClient(main.app)


def test_health_reports_ok_when_the_database_answers():
    async def _ok():
        return None

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(main, "AsyncSessionLocal", _session_factory(_ok))
        res = client.get("/health")

    assert res.status_code == 200
    assert res.json() == {"status": "ok", "database": "ok"}


def test_health_returns_503_when_the_database_is_unreachable():
    """The assertion the old implementation could not have passed.

    Not merely "the body says degraded" — the STATUS CODE has to change,
    because the status code is the only part the deployment platform reads.
    A 200 with a sad-looking body is the same bug wearing different words.
    """
    async def _boom():
        raise OSError("connection refused")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(main, "AsyncSessionLocal", _session_factory(_boom))
        res = client.get("/health")

    assert res.status_code == 503
    assert res.json() == {"status": "degraded", "database": "unreachable"}


def test_health_returns_503_rather_than_hanging_when_the_database_hangs():
    """A hung connection must not hang the probe.

    Refused connections are the easy case. The failure that actually
    stalls a deployment is the half-open one where the socket neither
    completes nor errors, and a probe with no timeout inherits that hang —
    the platform eventually records "no response", but only after tying up
    a worker for however long its own timeout is.
    """
    import asyncio

    async def _hang():
        await asyncio.sleep(30)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(main, "_HEALTH_DB_TIMEOUT_SECONDS", 0.05)
        mp.setattr(main, "AsyncSessionLocal", _session_factory(_hang))
        res = client.get("/health")

    assert res.status_code == 503
    assert res.json() == {"status": "degraded", "database": "unreachable"}


def test_health_leaks_nothing_about_the_failure_to_an_anonymous_caller():
    """/health is public and unauthenticated (see LicenseGateMiddleware's
    allowlist), so the failure body must stay a fixed string. The actual
    exception goes to the server log, where an operator can read it and a
    passer-by cannot."""
    async def _boom():
        raise OSError(
            "could not translate host name "
            "'dpg-secret-looking-host' to address"
        )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(main, "AsyncSessionLocal", _session_factory(_boom))
        res = client.get("/health")

    body = res.text
    assert "dpg-secret-looking-host" not in body
    assert "could not translate" not in body


# ── render.yaml deployment plans ──────────────────────────────────────────
#
# The second trap found on 2026-08-04, and the reason both plans had to be
# corrected in one change rather than one at a time.
#
# The dashboard read Pro-4gb (database) and Pro (web service). render.yaml
# still said basic-256mb and free. Those two mismatches fail in OPPOSITE
# directions, which is what made them dangerous together:
#
#   * The DATABASE plan fails LOUDLY and harmlessly. Render refuses to
#     downgrade a database, so every Blueprint sync errored with
#     "cannot downgrade database from X to Y" — meaning no sync had
#     applied for as long as the drift existed.
#   * The WEB SERVICE plan fails SILENTLY and destructively. A web service
#     plan is applied as written, so the first sync to succeed would have
#     downgraded the running Pro instance back to Free with no error.
#
# The database drift was therefore *masking* the web-service drift. Fixing
# only the loud one would have unblocked syncing and immediately triggered
# the quiet one — undoing a paid upgrade as a side effect of a bug fix.
#
# A test cannot see Render's dashboard, so it cannot assert the true plan.
# What it can do is refuse the specific value that is destructive to apply
# by accident, which is the one an editor reverts to (it is the default, and
# it is what the file said for most of its history).


def _render_config():
    return yaml.safe_load(_RENDER_YAML.read_text())


def test_database_plan_is_not_free():
    plan = _render_config()["databases"][0]["plan"]
    assert plan != "free", (
        "render.yaml's database plan reverted to `free`. Render refuses to "
        "downgrade a database, so this does not take production down — it "
        "breaks every Blueprint sync instead, silently freezing all further "
        "env-var changes from this file until someone notices."
    )


def test_web_service_plan_is_not_free():
    plan = _render_config()["services"][0]["plan"]
    assert plan != "free", (
        "render.yaml's web service plan reverted to `free`. Unlike the "
        "database plan above, Render APPLIES this as written — the next "
        "successful Blueprint sync would downgrade the running instance, "
        "with no error raised anywhere."
    )


def test_health_check_path_still_points_at_the_endpoint_these_tests_cover():
    """Pins the link between the two halves of this file.

    The failure behaviour above is only worth anything while the platform
    is actually probing that path. Repointing healthCheckPath elsewhere
    (or dropping it) would restore the original silent-failure mode
    without touching a single line of the endpoint these tests exercise.
    """
    assert _render_config()["services"][0]["healthCheckPath"] == "/health"
    assert any(
        getattr(r, "path", None) == "/health" for r in main.app.routes
    ), "render.yaml probes /health but the app no longer serves that route"
