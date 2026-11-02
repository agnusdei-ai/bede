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


# The route-level institutional boundary above does not replace the
# household child's device-to-learner binding (#761). Use the actual
# authorization guard with synthetic bindings; only voice inference is stubbed.
@pytest.mark.asyncio
@pytest.mark.parametrize("auth,name,revoked,expected_status", [
    ({"role": "child", "device_id": "tablet-1", "learner_nonce": "v1"}, "Bob", False, 404),
    ({"role": "child", "device_id": "tablet-1", "learner_nonce": "old"}, "Alice", False, 404),
    ({"role": "child", "device_id": "tablet-1"}, "Alice", False, 403),
    ({"role": "child", "device_id": "tablet-1", "learner_nonce": "v1"}, "Alice", True, 403),
])
async def test_voice_verify_checks_child_learner_before_audio_or_profile(
    monkeypatch, auth, name, revoked, expected_status,
):
    from io import BytesIO
    from unittest.mock import AsyncMock, patch
    from fastapi import Request, UploadFile
    from core.database import ChildLearnerBinding

    db = AsyncMock()
    db.get.return_value = ChildLearnerBinding(
        device_id="tablet-1", student_name="Alice", nonce="v1",
    )
    async def forbidden_inference(*_args, **_kwargs):
        pytest.fail("unauthorized voice profile must never be queried")
    monkeypatch.setattr(voice_router, "verify_student", forbidden_inference)
    audio = UploadFile(filename="synthetic.wav", file=BytesIO(b"RIFFsynthetic"))
    with patch("core.deps.settings") as settings, patch("core.deps.device_registry") as devices:
        settings.hosted_profile = False
        devices.is_revoked.return_value = revoked
        with pytest.raises(HTTPException) as exc:
            await voice_router.verify(
                Request({"type": "http", "headers": []}),
                student_name=name, audio=audio, db=db, auth=auth,
            )
    assert exc.value.status_code == expected_status
    assert audio.file.tell() == 0, "authorization must precede audio read"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["parent", "child"])
async def test_voice_verify_preserves_authorized_household_access(monkeypatch, role):
    from io import BytesIO
    from unittest.mock import AsyncMock, patch
    from fastapi import Request, UploadFile
    from core.database import ChildLearnerBinding

    db = AsyncMock()
    db.get.return_value = ChildLearnerBinding(
        device_id="tablet-1", student_name="Alice", nonce="v1",
    )
    calls = []
    async def synthetic_inference(student_name, audio, _db):
        calls.append((student_name, audio))
        return {"verified": False, "score": 0.0, "level": "low", "message": "Try again"}
    monkeypatch.setattr(voice_router, "verify_student", synthetic_inference)
    monkeypatch.setattr(voice_router, "log_event_nowait", lambda *_a, **_kw: None)
    auth = {"role": role}
    if role == "child":
        auth.update(device_id="tablet-1", learner_nonce="v1")
    with patch("core.deps.settings") as settings, patch("core.deps.device_registry") as devices:
        settings.hosted_profile = False
        devices.is_revoked.return_value = False
        result = await voice_router.verify(
            Request({"type": "http", "headers": []}),
            student_name="Alice",
            audio=UploadFile(filename="synthetic.wav", file=BytesIO(b"RIFFsynthetic")),
            db=db, auth=auth,
        )
    assert result["verified"] is False
    assert result["score"] == 0.0
    assert calls == [("Alice", b"RIFFsynthetic")]
    if role == "parent":
        db.get.assert_not_called()
