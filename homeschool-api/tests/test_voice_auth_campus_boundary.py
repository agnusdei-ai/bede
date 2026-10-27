"""Fail-closed boundary for legacy name-keyed voice profiles (synthetic only).

Institutional learners use immutable campus/learner UUIDs; the legacy
voice_profiles table does not. Every name-keyed biometric endpoint must
deny once any campus exists, including disabled campuses. A failed campus
lookup must also deny. No real student audio or records are used here.
"""
import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from routers import voice as voice_router


@pytest.mark.parametrize("path,method", [
    ("/voice/enroll", "POST"),
    ("/voice/verify", "POST"),
    ("/voice/override", "POST"),
    ("/voice/profiles", "GET"),
    ("/voice/profiles/{student_name}", "DELETE"),
])
def test_all_name_keyed_biometric_routes_enforce_scope(path, method):
    routes = [
        r for r in voice_router.router.routes
        if isinstance(r, APIRoute) and r.path == path and method in r.methods
    ]
    assert len(routes) == 1
    assert any(
        dep.call is voice_router._require_household_biometric_scope
        for dep in routes[0].dependant.dependencies
    ), f"{method} {path} bypasses the institutional biometric boundary"


@pytest.mark.asyncio
async def test_existing_campus_denies_even_a_parent_token(monkeypatch):
    async def campus_exists(_db):
        return True

    monkeypatch.setattr(voice_router.pilot_authz, "campus_mode_active", campus_exists)
    with pytest.raises(HTTPException) as exc:
        await voice_router._require_household_biometric_scope(object())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_campus_lookup_failure_denies(monkeypatch):
    async def unavailable(_db):
        raise RuntimeError("synthetic database outage")

    monkeypatch.setattr(voice_router.pilot_authz, "campus_mode_active", unavailable)
    with pytest.raises(HTTPException) as exc:
        await voice_router._require_household_biometric_scope(object())
    assert exc.value.status_code == 404
    assert "database outage" not in str(exc.value.detail)


@pytest.mark.asyncio
async def test_single_household_without_campus_remains_supported(monkeypatch):
    async def no_campus(_db):
        return False

    monkeypatch.setattr(voice_router.pilot_authz, "campus_mode_active", no_campus)
    assert await voice_router._require_household_biometric_scope(object()) is None
