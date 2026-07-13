"""
Router-level tests for the demo's diagnostic-preview endpoints:
GET /diagnostic/summary, POST /diagnostic/chat. No separate login — these
are reachable with the exact same demo_code token the child's own session
already has (like the "Ask Bede" sandbox preview), since this is
single-session, non-sensitive preview data. Called directly (same pattern
as test_extract_narration_router.py/test_feedback.py) rather than through
a full TestClient, since require_auth's JWT/fingerprint plumbing isn't
what's under test here.

Postgres-backed (see core.database.DemoCodeSession/DiagnosticPreviewUse)
rather than in-memory dicts, so every test here runs against the isolated
per-test SQLite engine the `demo_db` fixture (tests/conftest.py) swaps in
for core.database.AsyncSessionLocal.
"""
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import core.demo_code_session as demo_code_session
import core.diagnostic_preview_quota as quota
from routers.diagnostic import diagnostic_chat, get_diagnostic_summary
from models.schemas import DiagnosticChatRequest
from services.diagnostic_demo import get_mastery_summary_demo, record_skill_evidence_demo

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


def _fake_request(ip: str = "127.0.0.1") -> Request:
    scope = {
        "type": "http",
        "client": (ip, 12345),
        "headers": [(b"user-agent", b"pytest")],
    }
    return Request(scope)


async def _quota_codes(ip: str) -> list[str]:
    from sqlalchemy import select
    from core.database import AsyncSessionLocal, DiagnosticPreviewUse

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DiagnosticPreviewUse.code).where(DiagnosticPreviewUse.ip_hash == quota._hash_ip(ip))
        )
        return [row[0] for row in result.all()]


async def test_diagnostic_summary_404s_before_any_evidence():
    code = await demo_code_session.generate_code("Ellie", "3")
    with pytest.raises(HTTPException) as exc_info:
        await get_diagnostic_summary(_fake_request(), auth={"role": "demo_code", "code": code})
    assert exc_info.value.status_code == 404


async def test_diagnostic_summary_reflects_recorded_evidence():
    code = await demo_code_session.generate_code("Ellie", "3")
    await record_skill_evidence_demo(code, "3-5", "probe.oa.multiplication_facts", "correct")

    summary = await get_diagnostic_summary(_fake_request(), auth={"role": "demo_code", "code": code})
    assert summary.student_name == "Ellie"
    assert summary.evidence_count == 1


async def test_diagnostic_summary_rejects_non_demo_code_roles():
    from routers.diagnostic import _require_demo_code
    for role in ("parent", "child", None):
        with pytest.raises(HTTPException) as exc_info:
            _require_demo_code(auth={"role": role, "code": "123456"})
        assert exc_info.value.status_code == 403


async def test_templated_diagnostic_reply_mentions_gaps_and_next_steps():
    from routers.diagnostic import _templated_diagnostic_reply

    code = await demo_code_session.generate_code("Ellie", "3")
    await record_skill_evidence_demo(code, "3-5", "probe.oa.multiplication_facts", "correct")
    summary = await get_mastery_summary_demo(code, "Ellie")

    reply = _templated_diagnostic_reply(summary)
    assert "Ellie" in reply
    assert "monthly/annual plans" in reply


async def test_templated_diagnostic_reply_handles_no_evidence_without_a_summary():
    from routers.diagnostic import _templated_diagnostic_reply

    reply = _templated_diagnostic_reply(None)
    assert "No math evidence" in reply
    assert "monthly/annual plans" not in reply  # this branch's own shorter CTA, not the full one
    assert "We'd love to talk" in reply


async def test_diagnostic_chat_never_calls_the_live_model(monkeypatch):
    """The whole point of this unit: the demo/free tier's diagnostic chat
    must consume zero API usage — assert stream_sandbox_response is never
    even imported/called from this path anymore."""
    import services.ai_service as ai_service

    mock_stream = AsyncMock(side_effect=AssertionError("must not call the live model"))
    monkeypatch.setattr(ai_service, "stream_sandbox_response", mock_stream)

    code = await demo_code_session.generate_code("Ellie", "3")
    await record_skill_evidence_demo(code, "3-5", "probe.oa.multiplication_facts", "correct")
    req = DiagnosticChatRequest(message="How is Ellie doing?")

    response = await diagnostic_chat(req, _fake_request(), auth={"role": "demo_code", "code": code})

    body_chunks = [chunk async for chunk in response.body_iterator]
    assert any("Ellie" in str(chunk) for chunk in body_chunks)
    mock_stream.assert_not_called()


# ── Diagnostic preview quota (per-IP cap, see core/diagnostic_preview_quota.py) ──


async def test_a_404_summary_before_any_evidence_does_not_consume_quota():
    code = await demo_code_session.generate_code("Ellie", "3")
    with pytest.raises(HTTPException):
        await get_diagnostic_summary(_fake_request(), auth={"role": "demo_code", "code": code})

    assert await quota.has_quota("127.0.0.1", "any-other-code") is True
    assert await _quota_codes("127.0.0.1") == []


async def test_a_successful_summary_consumes_one_use_of_quota():
    code = await demo_code_session.generate_code("Ellie", "3")
    await record_skill_evidence_demo(code, "3-5", "probe.oa.multiplication_facts", "correct")

    await get_diagnostic_summary(_fake_request(), auth={"role": "demo_code", "code": code})

    assert await _quota_codes("127.0.0.1") == [code]


async def test_repeated_summary_calls_for_the_same_code_do_not_double_spend_quota():
    code = await demo_code_session.generate_code("Ellie", "3")
    await record_skill_evidence_demo(code, "3-5", "probe.oa.multiplication_facts", "correct")

    for _ in range(5):
        await get_diagnostic_summary(_fake_request(), auth={"role": "demo_code", "code": code})

    assert len(await _quota_codes("127.0.0.1")) == 1


async def test_diagnostic_chat_without_evidence_does_not_consume_quota():
    code = await demo_code_session.generate_code("Ellie", "3")
    req = DiagnosticChatRequest(message="How is Ellie doing?")

    await diagnostic_chat(req, _fake_request(), auth={"role": "demo_code", "code": code})

    assert await _quota_codes("127.0.0.1") == []


async def test_diagnostic_chat_with_evidence_consumes_one_use_of_quota():
    code = await demo_code_session.generate_code("Ellie", "3")
    await record_skill_evidence_demo(code, "3-5", "probe.oa.multiplication_facts", "correct")
    req = DiagnosticChatRequest(message="How is Ellie doing?")

    await diagnostic_chat(req, _fake_request(), auth={"role": "demo_code", "code": code})

    assert code in await _quota_codes("127.0.0.1")


async def test_require_diagnostic_quota_blocks_a_new_code_once_the_ip_is_exhausted():
    from routers.diagnostic import _require_diagnostic_quota

    ip = "127.0.0.1"
    for i in range(quota.DIAGNOSTIC_PREVIEW_QUOTA):
        await quota.record_use(ip, f"used-{i}")

    with pytest.raises(HTTPException) as exc_info:
        await _require_diagnostic_quota(_fake_request(ip), auth={"role": "demo_code", "code": "brand-new-code"})
    assert exc_info.value.status_code == 429


async def test_require_diagnostic_quota_still_allows_a_previously_used_code():
    from routers.diagnostic import _require_diagnostic_quota

    ip = "127.0.0.1"
    for i in range(quota.DIAGNOSTIC_PREVIEW_QUOTA):
        await quota.record_use(ip, f"used-{i}")

    result = await _require_diagnostic_quota(_fake_request(ip), auth={"role": "demo_code", "code": "used-0"})
    assert result["code"] == "used-0"


async def test_exhausting_quota_for_one_ip_never_blocks_another_ip():
    from routers.diagnostic import _require_diagnostic_quota

    for i in range(quota.DIAGNOSTIC_PREVIEW_QUOTA):
        await quota.record_use("1.2.3.4", f"used-{i}")

    result = await _require_diagnostic_quota(_fake_request("9.9.9.9"), auth={"role": "demo_code", "code": "brand-new-code"})
    assert result["code"] == "brand-new-code"
