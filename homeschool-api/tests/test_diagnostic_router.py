"""
Router-level tests for the demo's diagnostic-preview endpoints:
POST /auth/diagnostic-login, GET /diagnostic/summary, POST /diagnostic/chat.
Called directly (same pattern as test_extract_narration_router.py/
test_feedback.py) rather than through a full TestClient, since
require_auth's JWT/fingerprint plumbing isn't what's under test here.
"""
import pytest
from fastapi import HTTPException
from starlette.requests import Request

import core.demo_code_session as demo_code_session
from core.config import settings
from models.schemas import DiagnosticLoginRequest
from routers.auth import diagnostic_login
from routers.diagnostic import get_diagnostic_summary
from services.diagnostic_demo import get_mastery_summary_demo, record_skill_evidence_demo


def _fake_request() -> Request:
    scope = {
        "type": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [(b"user-agent", b"pytest")],
    }
    return Request(scope)


def setup_function():
    demo_code_session._codes = {}


@pytest.mark.asyncio
async def test_diagnostic_login_404s_when_pin_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "diagnostic_pin", "")
    code = demo_code_session.generate_code()
    with pytest.raises(HTTPException) as exc_info:
        await diagnostic_login(DiagnosticLoginRequest(code=code, pin="384756"), _fake_request())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_diagnostic_login_rejects_wrong_pin(monkeypatch):
    monkeypatch.setattr(settings, "diagnostic_pin", "384756")
    code = demo_code_session.generate_code()
    with pytest.raises(HTTPException) as exc_info:
        await diagnostic_login(DiagnosticLoginRequest(code=code, pin="000000"), _fake_request())
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_diagnostic_login_rejects_unknown_demo_code(monkeypatch):
    monkeypatch.setattr(settings, "diagnostic_pin", "384756")
    with pytest.raises(HTTPException) as exc_info:
        await diagnostic_login(DiagnosticLoginRequest(code="000000", pin="384756"), _fake_request())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_diagnostic_login_succeeds_and_issues_a_diagnostic_parent_token(monkeypatch):
    monkeypatch.setattr(settings, "diagnostic_pin", "384756")
    code = demo_code_session.generate_code()
    resp = await diagnostic_login(DiagnosticLoginRequest(code=code, pin="384756"), _fake_request())
    assert resp.role == "diagnostic_parent"
    assert resp.access_token


@pytest.mark.asyncio
async def test_diagnostic_summary_404s_before_any_evidence():
    code = demo_code_session.generate_code("Ellie", "3")
    with pytest.raises(HTTPException) as exc_info:
        await get_diagnostic_summary(_fake_request(), auth={"role": "diagnostic_parent", "code": code})
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_diagnostic_summary_reflects_recorded_evidence():
    code = demo_code_session.generate_code("Ellie", "3")
    await record_skill_evidence_demo(code, "3-5", "probe.oa.multiplication_facts", "correct")

    summary = await get_diagnostic_summary(_fake_request(), auth={"role": "diagnostic_parent", "code": code})
    assert summary.student_name == "Ellie"
    assert summary.evidence_count == 1


@pytest.mark.asyncio
async def test_diagnostic_summary_rejects_non_diagnostic_parent_role():
    from routers.diagnostic import _require_diagnostic_parent
    with pytest.raises(HTTPException) as exc_info:
        _require_diagnostic_parent(auth={"role": "demo_code", "code": "123456"})
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_render_mastery_context_mentions_gaps_and_next_steps():
    from routers.diagnostic import _render_mastery_context

    code = demo_code_session.generate_code("Ellie", "3")
    await record_skill_evidence_demo(code, "3-5", "probe.oa.multiplication_facts", "correct")
    summary = get_mastery_summary_demo(code, "Ellie")

    context = _render_mastery_context(summary)
    assert "Ellie" in context
    assert "direct answers, not Socratic" in context
