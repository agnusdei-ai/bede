"""
Router-level tests for the demo's diagnostic-preview endpoints:
GET /diagnostic/summary, POST /diagnostic/chat. No separate login — these
are reachable with the exact same demo_code token the child's own session
already has (like the "Ask Bede" sandbox preview), since this is
single-session, non-sensitive preview data. Called directly (same pattern
as test_extract_narration_router.py/test_feedback.py) rather than through
a full TestClient, since require_auth's JWT/fingerprint plumbing isn't
what's under test here.
"""
import pytest
from fastapi import HTTPException
from starlette.requests import Request

import core.demo_code_session as demo_code_session
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
async def test_diagnostic_summary_404s_before_any_evidence():
    code = demo_code_session.generate_code("Ellie", "3")
    with pytest.raises(HTTPException) as exc_info:
        await get_diagnostic_summary(_fake_request(), auth={"role": "demo_code", "code": code})
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_diagnostic_summary_reflects_recorded_evidence():
    code = demo_code_session.generate_code("Ellie", "3")
    await record_skill_evidence_demo(code, "3-5", "probe.oa.multiplication_facts", "correct")

    summary = await get_diagnostic_summary(_fake_request(), auth={"role": "demo_code", "code": code})
    assert summary.student_name == "Ellie"
    assert summary.evidence_count == 1


@pytest.mark.asyncio
async def test_diagnostic_summary_rejects_non_demo_code_roles():
    from routers.diagnostic import _require_demo_code
    for role in ("parent", "child", None):
        with pytest.raises(HTTPException) as exc_info:
            _require_demo_code(auth={"role": role, "code": "123456"})
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
