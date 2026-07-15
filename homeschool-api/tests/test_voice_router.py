"""
Tests for routers/voice.py — voice biometric enrollment, verification,
override, and deletion. Before this file, no test in the suite imported
anything from routers/voice.py at all: the parent-only gating on
enrollment/override/deletion and the require_real_user gating on
verify/transcribe were implemented but unverified by CI.

Two kinds of check, deliberately kept separate:

1. "Wiring" tests assert each endpoint's auth dependency is literally
   Depends(require_parent) or Depends(require_real_user) by inspecting the
   function signature's default Depends object — this is what actually
   catches a silent regression (e.g. someone swaps require_parent for
   require_auth by accident), which calling the endpoint directly with a
   hand-built auth dict cannot catch, since bypassing FastAPI's dependency
   injection also bypasses whatever the real dependency would have
   enforced.
2. "Logic" tests call the endpoint functions directly with a hand-built
   auth dict and a fake Request (same pattern as test_diagnostic_router.py
   and test_parent_agreement.py), mocking services.voice_auth so no real
   audio processing or database is needed, to confirm each endpoint's own
   behavior (audit events, response shape, error handling).
"""
import inspect
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, UploadFile
from starlette.requests import Request

from core.deps import require_parent, require_real_user
from routers import voice


def _fake_request() -> Request:
    scope = {
        "type": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [(b"user-agent", b"pytest")],
    }
    return Request(scope)


def _upload(data: bytes, filename: str = "sample.wav") -> UploadFile:
    import io
    return UploadFile(filename=filename, file=io.BytesIO(data))


_WAV_MAGIC = b"RIFF" + b"\x00" * 40


def _dependency_of(func, param_name: str):
    """The callable a FastAPI Depends(...) default actually wraps, or None
    if that parameter isn't Depends-backed."""
    default = inspect.signature(func).parameters[param_name].default
    return getattr(default, "dependency", None)


# ── Wiring: does each endpoint actually require the role it claims to? ──────

@pytest.mark.parametrize(
    "endpoint,param",
    [
        (voice.enroll, "_"),
        (voice.override_verification, "_"),
        (voice.get_profiles, "_"),
        (voice.remove_profile, "_"),
    ],
)
def test_parent_only_endpoints_depend_on_require_parent(endpoint, param):
    assert _dependency_of(endpoint, param) is require_parent


@pytest.mark.parametrize(
    "endpoint,param",
    [
        (voice.verify, "auth"),
        (voice.transcribe, "auth"),
    ],
)
def test_real_user_endpoints_depend_on_require_real_user(endpoint, param):
    assert _dependency_of(endpoint, param) is require_real_user


# ── Logic: enroll ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enroll_rejects_fewer_than_two_samples():
    with pytest.raises(HTTPException) as exc_info:
        await voice.enroll(
            _fake_request(),
            student_name="Emma",
            samples=[_upload(_WAV_MAGIC)],
            db=object(),
            _={"role": "parent"},
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_enroll_rejects_more_than_five_samples():
    with pytest.raises(HTTPException) as exc_info:
        await voice.enroll(
            _fake_request(),
            student_name="Emma",
            samples=[_upload(_WAV_MAGIC) for _ in range(6)],
            db=object(),
            _={"role": "parent"},
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_enroll_rejects_a_non_audio_file():
    with pytest.raises(HTTPException) as exc_info:
        await voice.enroll(
            _fake_request(),
            student_name="Emma",
            samples=[_upload(b"not audio at all", filename="notes.txt"), _upload(_WAV_MAGIC)],
            db=object(),
            _={"role": "parent"},
        )
    assert exc_info.value.status_code == 415


@pytest.mark.asyncio
async def test_enroll_succeeds_and_logs_the_audit_event():
    with patch.object(
        voice, "enroll_student", AsyncMock(return_value={
            "student_name": "Emma", "samples_used": 2, "method": "resemblyzer",
        }),
    ) as mock_enroll, patch.object(voice, "log_event", AsyncMock()) as mock_log:
        result = await voice.enroll(
            _fake_request(),
            student_name="Emma",
            samples=[_upload(_WAV_MAGIC), _upload(_WAV_MAGIC)],
            db=object(),
            _={"role": "parent"},
        )

    assert result == {
        "success": True, "student_name": "Emma", "samples_used": 2, "method": "resemblyzer",
    }
    mock_enroll.assert_awaited_once()
    mock_log.assert_awaited_once()
    assert mock_log.call_args.kwargs["student_name"] == "Emma"


@pytest.mark.asyncio
async def test_enroll_failure_logs_a_failed_audit_event_and_returns_422():
    with patch.object(
        voice, "enroll_student", AsyncMock(side_effect=ValueError("no usable samples")),
    ), patch.object(voice, "log_event", AsyncMock()) as mock_log:
        with pytest.raises(HTTPException) as exc_info:
            await voice.enroll(
                _fake_request(),
                student_name="Emma",
                samples=[_upload(_WAV_MAGIC), _upload(_WAV_MAGIC)],
                db=object(),
                _={"role": "parent"},
            )

    assert exc_info.value.status_code == 422
    assert mock_log.call_args.kwargs["success"] is False


# ── Logic: override / delete ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_override_logs_the_audit_event_and_delegates_to_the_service():
    with patch.object(voice, "parent_override", return_value={"overridden": "Emma"}) as mock_override, \
         patch.object(voice, "log_event", AsyncMock()) as mock_log:
        result = await voice.override_verification(
            _fake_request(), student_name="Emma", _={"role": "parent"},
        )

    assert result == {"overridden": "Emma"}
    mock_override.assert_called_once_with("Emma")
    mock_log.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_profile_404s_when_nothing_was_deleted():
    with patch.object(voice, "delete_profile", AsyncMock(return_value=False)), \
         patch.object(voice, "log_event", AsyncMock()) as mock_log:
        with pytest.raises(HTTPException) as exc_info:
            await voice.remove_profile("Emma", _fake_request(), db=object(), _={"role": "parent"})

    assert exc_info.value.status_code == 404
    mock_log.assert_not_awaited()


@pytest.mark.asyncio
async def test_remove_profile_logs_the_audit_event_on_success():
    with patch.object(voice, "delete_profile", AsyncMock(return_value=True)), \
         patch.object(voice, "log_event", AsyncMock()) as mock_log:
        result = await voice.remove_profile("Emma", _fake_request(), db=object(), _={"role": "parent"})

    assert result == {"deleted": "Emma"}
    mock_log.assert_awaited_once()
    assert mock_log.call_args.kwargs["detail"] == "profile deleted"


# ── Logic: verify ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_logs_pass_event_when_verified():
    with patch.object(
        voice, "verify_student",
        AsyncMock(return_value={"verified": True, "score": 0.9, "level": "high", "message": "ok"}),
    ), patch.object(voice, "log_event", AsyncMock()) as mock_log:
        result = await voice.verify(
            _fake_request(), student_name="Emma", audio=_upload(_WAV_MAGIC),
            db=object(), auth={"role": "child"},
        )

    assert result["verified"] is True
    assert mock_log.call_args.kwargs["success"] is True
    assert mock_log.call_args.args[0] == voice.AuditEvent.VOICE_VERIFY_PASS


@pytest.mark.asyncio
async def test_verify_logs_fail_event_when_not_verified():
    with patch.object(
        voice, "verify_student",
        AsyncMock(return_value={"verified": False, "score": 0.2, "level": "low", "message": "no match"}),
    ), patch.object(voice, "log_event", AsyncMock()) as mock_log:
        result = await voice.verify(
            _fake_request(), student_name="Emma", audio=_upload(_WAV_MAGIC),
            db=object(), auth={"role": "child"},
        )

    assert result["verified"] is False
    assert mock_log.call_args.kwargs["success"] is False
    assert mock_log.call_args.args[0] == voice.AuditEvent.VOICE_VERIFY_FAIL
