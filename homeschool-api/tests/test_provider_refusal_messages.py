"""
When an AI provider refuses, say why, in words someone can act on.

On 2026-11-17 every demo lesson failed for three reasons at once (OpenAI out
of credit, Mistral's plan without the model, Claude refusing) and all three
reached the child as "Something went wrong on my end", with nothing for the
parent. These pin:

- the classifier, against the exact error shapes the providers returned that
  day (OpenAI's "no credits" is a 429, Anthropic's empty balance is a 400, so
  the status code alone would misfile both);
- the failover switch attaching each provider's reason when all of them fail,
  through the REAL FailoverClient, so the wiring is tested and not only the
  classifier;
- the child's message and the audit detail on a real /tutor/chat turn;
- the parent sandbox naming the providers and the anonymous demo not doing so;
- the parent-run "Check AI providers" endpoint, including its throttle.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import httpx
import openai
import pytest
from fastapi import HTTPException
from starlette.requests import Request

import routers.admin as admin_module
import routers.sandbox as sandbox_module
import routers.tutor as tutor_module
from core.audit import AuditEvent
from core.config import settings
from models.schemas import GradeStage, SandboxChatRequest, SandboxDemoChatRequest, SessionConfig, Subject, TutorRequest
from services.adapters import provider_errors, router
from services.ai_service import ai_unavailable_response

# ── the provider errors exactly as they were worded on 2026-11-17 ────────────


def _err(lib, cls_name, status, message):
    response = httpx.Response(status, request=httpx.Request("POST", "https://example.invalid/v1"))
    return getattr(lib, cls_name)(message, response=response, body=None)


def openai_no_credit():
    return _err(openai, "RateLimitError", 429,
                "Error code: 429 - You have no credits remaining. Add credits to continue using the API.")


def mistral_model_not_on_plan():
    return _err(openai, "PermissionDeniedError", 403,
                "Error code: 403 - This model is not available in your subscription tier")


def mistral_rate_limited():
    return _err(openai, "RateLimitError", 429, "Error code: 429 - Rate limit exceeded")


def anthropic_no_credit():
    return _err(anthropic, "BadRequestError", 400,
                "Your credit balance is too low to access the Anthropic API.")


@pytest.mark.parametrize("make, code", [
    (openai_no_credit, "no_credit"),
    (mistral_model_not_on_plan, "model_not_on_plan"),
    (mistral_rate_limited, "rate_limited"),
    (anthropic_no_credit, "no_credit"),
    (lambda: _err(anthropic, "AuthenticationError", 401, "invalid x-api-key"), "bad_key"),
    (lambda: _err(openai, "NotFoundError", 404, "The model `x` does not exist"), "model_not_on_plan"),
    (lambda: _err(anthropic, "BadRequestError", 400, "messages: field required"), "refused"),
    (lambda: ConnectionError("connection reset"), "unreachable"),
    (lambda: TimeoutError(), "unreachable"),
    (lambda: ValueError("something else"), "unknown"),
])
def test_each_refusal_gets_the_reason_that_names_what_to_fix(make, code):
    problem = provider_errors.classify(make())
    assert problem.code == code
    assert problem.message == provider_errors.message_for(code)


def test_the_detail_is_the_providers_own_words_and_bounded():
    problem = provider_errors.classify(_err(openai, "RateLimitError", 429, "x" * 2000))
    assert len(problem.detail) <= 240


# ── the real failover switch records each provider's reason ──────────────────


class _Failing:
    def __init__(self, exc):
        self._exc = exc

    async def __aenter__(self):
        raise self._exc

    async def __aexit__(self, *exc):
        return None


def _failover(**built):
    s = settings.model_copy()
    s.bede_adapter_order = ",".join(built)
    s.bede_force_adapter = ""
    s.anthropic_api_key = "sk-ant"
    s.openai_api_key = "sk-openai"
    s.mistral_api_key = "sk-mistral"
    s.local_llm_base_url = ""
    fc = router.FailoverClient(s)
    fc._built = {
        name: SimpleNamespace(messages=SimpleNamespace(
            stream=(lambda e: (lambda **kw: _Failing(e)))(exc),
            create=AsyncMock(side_effect=exc),
        ))
        for name, exc in built.items()
    }
    return fc


async def _every_provider_refuses_a_stream():
    fc = _failover(openai=openai_no_credit(), mistral=mistral_model_not_on_plan(),
                   anthropic=anthropic_no_credit())
    try:
        async with fc.messages.stream(model="m", messages=[]):
            pass
    except Exception as exc:  # the exception a real lesson turn would see
        return exc
    raise AssertionError("expected every provider to refuse")


@pytest.mark.asyncio
async def test_when_every_provider_refuses_each_reason_travels_with_the_error():
    exc = await _every_provider_refuses_a_stream()
    assert router.provider_failures(exc) == (
        ("openai", "no_credit"), ("mistral", "model_not_on_plan"), ("anthropic", "no_credit"),
    )


@pytest.mark.asyncio
async def test_create_records_the_reasons_too():
    fc = _failover(openai=openai_no_credit(), mistral=mistral_rate_limited())
    with pytest.raises(Exception) as info:
        await fc.messages.create(model="m", messages=[])
    assert router.provider_failures(info.value) == (("openai", "no_credit"), ("mistral", "rate_limited"))


def test_an_ordinary_error_carries_no_provider_reasons():
    assert router.provider_failures(RuntimeError("our bug")) == ()


# ── the lesson turn: the child's words and the audit record ──────────────────


def _request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 1), "headers": [(b"user-agent", b"pytest")]})


def _tutor_request() -> TutorRequest:
    return TutorRequest(
        session_config=SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery),
        current_subject=Subject.science, conversation_history=[], child_message="Why is the sky blue?",
    )


@pytest.fixture
def tutor_audit(monkeypatch):
    # The moderation step would otherwise make a real network call.
    monkeypatch.setattr(tutor_module, "classify_child_message", AsyncMock(return_value={
        "flagged": False, "categories": [], "confidence": "low", "should_block": False}))
    calls = []
    monkeypatch.setattr(tutor_module, "log_event_nowait", lambda event, **kw: calls.append((event, kw)))
    return calls


async def _collect(response):
    """The text the reader sees, decoded from the SSE JSON chunks."""
    import json

    texts = []
    async for chunk in response.body_iterator:
        payload = json.loads(chunk)
        texts.append(payload.get("content", ""))
    return texts


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", ["en", "es"])
async def test_a_turn_no_provider_could_answer_tells_the_child_plainly(monkeypatch, tutor_audit, locale):
    refusal = await _every_provider_refuses_a_stream()

    async def refused(*args, **kwargs):
        raise refusal
        yield  # pragma: no cover

    monkeypatch.setattr(tutor_module, "stream_tutor_response", refused)
    response = await tutor_module.chat(
        _tutor_request(), _request(), auth={"role": "parent", "locale": locale}, db=None)
    body = "".join(await _collect(response))

    assert ai_unavailable_response(locale).split(".")[0] in body
    assert "went wrong" not in body
    # The child is never told about providers or billing.
    for word in ("openai", "mistral", "anthropic", "credit", "billing"):
        assert word not in body.lower()

    detail = [kw for e, kw in tutor_audit if e == AuditEvent.AI_BACKEND_FAILURE][0]["detail"]
    assert "providers=openai:no_credit,mistral:model_not_on_plan,anthropic:no_credit" in detail


@pytest.mark.asyncio
async def test_a_bug_in_bede_still_reads_as_before(monkeypatch, tutor_audit):
    async def broken(*args, **kwargs):
        raise RuntimeError("our bug")
        yield  # pragma: no cover

    monkeypatch.setattr(tutor_module, "stream_tutor_response", broken)
    response = await tutor_module.chat(_tutor_request(), _request(), auth={"role": "parent"}, db=None)
    body = "".join(await _collect(response))
    assert "went wrong" in body
    detail = [kw for e, kw in tutor_audit if e == AuditEvent.AI_BACKEND_FAILURE][0]["detail"]
    assert "providers=" not in detail


def test_both_locales_have_the_unavailable_message():
    assert ai_unavailable_response("en") != ai_unavailable_response("es")
    assert ai_unavailable_response("fr") == ai_unavailable_response("en")


# ── Ask Bede: the parent is told which provider and why; a demo visitor is not


@pytest.fixture
def sandbox_audit(monkeypatch):
    monkeypatch.setattr(settings, "sandbox_pin", "111222")
    calls = []
    monkeypatch.setattr(sandbox_module, "log_event_nowait", lambda event, **kw: calls.append((event, kw)))
    return calls


@pytest.mark.asyncio
async def test_the_parent_sandbox_names_each_provider_and_what_to_fix(monkeypatch, sandbox_audit):
    refusal = await _every_provider_refuses_a_stream()

    async def refused(*args, **kwargs):
        raise refusal
        yield  # pragma: no cover

    monkeypatch.setattr(sandbox_module, "stream_sandbox_response", refused)
    response = await sandbox_module.chat(
        SandboxChatRequest(sandbox_pin="111222", message="test"), _request(), auth={"role": "parent"})
    body = "".join(await _collect(response))
    assert "openai" in body and "mistral" in body and "anthropic" in body
    assert "credit" in body.lower()
    assert "Check AI providers" in body
    detail = [kw for e, kw in sandbox_audit if e == AuditEvent.AI_BACKEND_FAILURE][0]["detail"]
    assert "providers=openai:no_credit" in detail


@pytest.mark.asyncio
@pytest.mark.usefixtures("demo_db")
async def test_the_public_demo_gets_the_plain_notice_not_the_operators_billing(monkeypatch, sandbox_audit):
    import core.demo_code_session as demo_code_session

    refusal = await _every_provider_refuses_a_stream()

    async def refused(*args, **kwargs):
        raise refusal
        yield  # pragma: no cover

    monkeypatch.setattr(sandbox_module, "stream_sandbox_response", refused)
    code = await demo_code_session.generate_code()
    response = await sandbox_module.demo_chat(
        SandboxDemoChatRequest(message="test"), _request(), auth={"role": "demo_code", "code": code})
    body = "".join(await _collect(response))
    assert ai_unavailable_response("en").split(".")[0] in body
    for word in ("openai", "mistral", "anthropic", "credit"):
        assert word not in body.lower()


# ── POST /admin/ai-provider/check ────────────────────────────────────────────


@pytest.fixture
def three_providers(monkeypatch):
    monkeypatch.setattr(settings, "bede_adapter_order", "openai,mistral,anthropic")
    monkeypatch.setattr(settings, "bede_force_adapter", "")
    monkeypatch.setattr(settings, "openai_api_key", "sk-openai")
    monkeypatch.setattr(settings, "mistral_api_key", "sk-mistral")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant")
    monkeypatch.setattr(settings, "local_llm_base_url", "")
    monkeypatch.setattr(admin_module, "_last_provider_check", 0.0)
    answers = {
        "openai": AsyncMock(return_value=SimpleNamespace(content=[])),
        "mistral": AsyncMock(side_effect=mistral_rate_limited()),
        "anthropic": AsyncMock(side_effect=anthropic_no_credit()),
    }
    monkeypatch.setattr(router, "_build", lambda name, s: SimpleNamespace(
        messages=SimpleNamespace(create=answers[name])))
    return answers


@pytest.mark.asyncio
async def test_the_check_says_which_providers_answer_and_why_the_others_do_not(three_providers):
    results = {r["provider"]: r for r in (await admin_module.check_ai_providers(_={}))["results"]}
    assert results["openai"]["ok"] is True
    assert results["mistral"] == {
        "provider": "mistral", "ok": False, "code": "rate_limited",
        "message": provider_errors.message_for("rate_limited"),
        "detail": results["mistral"]["detail"],
    }
    assert results["anthropic"]["code"] == "no_credit"
    assert "credit balance" in results["anthropic"]["detail"]
    # One tiny request each, never more.
    for create in three_providers.values():
        assert create.await_count == 1
        assert create.await_args.kwargs["max_tokens"] <= 5


@pytest.mark.asyncio
async def test_the_check_cannot_be_run_again_within_half_a_minute(three_providers):
    await admin_module.check_ai_providers(_={})
    with pytest.raises(HTTPException) as info:
        await admin_module.check_ai_providers(_={})
    assert info.value.status_code == 429
    assert three_providers["openai"].await_count == 1


def test_the_check_route_is_mounted_for_parents_only():
    from core.deps import require_parent

    route = next(r for r in admin_module.router.routes if r.path.endswith("/ai-provider/check"))
    assert "POST" in route.methods
    assert any(d.call is require_parent for d in route.dependant.dependencies)
