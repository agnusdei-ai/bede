"""The temporary blind demo model experiment (services/model_experiment.py).

Pins the properties that make it safe to run on the public demo: it is off
unless fully configured, only demo sessions are ever assigned an arm, the
assignment holds for a whole session, the open arm reaches the open model on
the real call path and fails over to production, moderation never moves, and
the arm is revealed only in the operator's feedback email.
"""
import pytest
from starlette.requests import Request

import core.demo_code_session as demo_code_session
from core.config import settings
from models.schemas import GradeStage, SessionConfig, Subject, TutorRequest
from services import model_experiment
from services.adapters.router import FailoverClient

pytestmark = pytest.mark.asyncio

SALT = "test-salt"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    model_experiment._bound_code.set(None)
    monkeypatch.setattr(model_experiment, "_client", None)
    yield
    model_experiment._bound_code.set(None)


@pytest.fixture
def armed(monkeypatch):
    monkeypatch.setattr(settings, "demo_model_experiment_salt", SALT)
    monkeypatch.setattr(settings, "experiment_llm_base_url", "https://openrouter.example/api/v1")
    monkeypatch.setattr(settings, "experiment_llm_api_key", "sk-test")
    monkeypatch.setattr(settings, "experiment_tutor_model", "google/gemma-4-31b-it")


def _code_for(arm: str) -> str:
    for i in range(1000):
        code = f"code-{i}"
        if model_experiment.arm_for(code) == arm:
            return code
    raise AssertionError("no code found")


async def test_off_by_default_even_when_a_code_is_bound():
    model_experiment.bind("anything")
    assert model_experiment.enabled() is False
    assert model_experiment.current_arm() is None


@pytest.mark.parametrize("missing", [
    "demo_model_experiment_salt", "experiment_llm_base_url",
    "experiment_llm_api_key", "experiment_tutor_model",
])
async def test_every_setting_is_required(armed, monkeypatch, missing):
    monkeypatch.setattr(settings, missing, "")
    assert model_experiment.enabled() is False


async def test_refuses_plain_http(armed, monkeypatch):
    monkeypatch.setattr(settings, "experiment_llm_base_url", "http://openrouter.example/api/v1")
    assert model_experiment.enabled() is False


async def test_assignment_is_stable_balanced_and_keyed(armed, monkeypatch):
    codes = [f"code-{i}" for i in range(2000)]
    arms = [model_experiment.arm_for(c) for c in codes]
    assert arms == [model_experiment.arm_for(c) for c in codes]
    opens = arms.count(model_experiment.ARM_OPEN)
    assert 900 < opens < 1100
    monkeypatch.setattr(settings, "demo_model_experiment_salt", "another-salt")
    assert [model_experiment.arm_for(c) for c in codes] != arms


async def test_unbound_requests_never_reach_the_open_model(armed):
    assert model_experiment.current_arm() is None
    assert model_experiment.ADAPTER_NAME not in FailoverClient(settings)._live_order()


async def test_baseline_arm_keeps_the_production_order(armed):
    model_experiment.bind(_code_for(model_experiment.ARM_BASELINE))
    assert model_experiment.ADAPTER_NAME not in FailoverClient(settings)._live_order()


class _Fake:
    def __init__(self, raises=None):
        self.calls = []
        self.raises = raises
        self.messages = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        return "reply"


async def test_open_arm_is_served_by_the_open_model_and_fails_over(armed, monkeypatch):
    import openai

    model_experiment.bind(_code_for(model_experiment.ARM_OPEN))
    client = FailoverClient(settings)
    assert client._live_order()[0] == model_experiment.ADAPTER_NAME

    open_model = _Fake()
    monkeypatch.setattr(model_experiment, "_client", open_model)
    assert await client.messages.create(model="x", messages=[]) == "reply"
    assert len(open_model.calls) == 1

    # A failing open model must not leave the visitor without an answer.
    failing = _Fake(raises=openai.APIConnectionError(request=None))
    production = _Fake()
    monkeypatch.setattr(model_experiment, "_client", failing)
    monkeypatch.setattr("services.adapters.router._configured_order", lambda s: ["openai"])
    monkeypatch.setattr(client, "_built", {"openai": production})

    async def _no_alert(*a, **k):
        return None

    monkeypatch.setattr("services.adapters.router._best_effort_failover_alert", _no_alert)
    client = FailoverClient(settings)
    client._built = {"openai": production}
    assert await client.messages.create(model="x", messages=[]) == "reply"
    assert len(failing.calls) == 1 and len(production.calls) == 1


async def test_the_open_client_is_built_from_the_experiment_settings(armed):
    built = model_experiment.client()
    assert built._model == "google/gemma-4-31b-it"
    assert str(built._openai.base_url).startswith("https://openrouter.example/api/v1")


async def test_moderation_never_runs_on_the_open_model(armed, monkeypatch):
    from services import moderation

    model_experiment.bind(_code_for(model_experiment.ARM_OPEN))
    seen = []

    class _Recorder:
        def __init__(self):
            self.messages = self

        async def create(self, **kwargs):
            seen.append(model_experiment.current_arm())
            raise RuntimeError("stop here")

    monkeypatch.setattr("services.ai_service._client", _Recorder())
    await moderation.classify_child_message("Is the sun a star?")
    assert seen == [None]
    # ...and the session is still on the open arm afterwards.
    assert model_experiment.current_arm() == model_experiment.ARM_OPEN


def _request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 1), "headers": [(b"user-agent", b"pytest")]})


@pytest.mark.usefixtures("demo_db")
async def test_the_real_demo_chat_path_binds_the_session_for_its_whole_stream(armed, monkeypatch):
    from routers.tutor import chat

    code = await demo_code_session.generate_code(student_name="Ellie", grade="4")
    seen = []

    async def spy_stream(*args, **kwargs):
        seen.append(model_experiment.current_arm())
        yield '{"type": "done"}'

    monkeypatch.setattr("routers.tutor.stream_tutor_response", spy_stream)
    req = TutorRequest(
        session_config=SessionConfig(student_name="Sam", grade="4", grade_stage=GradeStage.core_mastery),
        current_subject=Subject.science, conversation_history=[], child_message="Why is the sky blue?",
    )
    response = await chat(req, _request(), auth={"role": "demo_code", "code": code}, db=None)
    [c async for c in response.body_iterator]
    assert seen == [model_experiment.arm_for(code)]


@pytest.mark.usefixtures("demo_db")
async def test_the_sandbox_demo_path_binds_the_session(armed, monkeypatch):
    from models.schemas import SandboxDemoChatRequest
    from routers.sandbox import demo_chat

    code = await demo_code_session.generate_code()
    seen = []

    async def spy_stream(*args, **kwargs):
        seen.append(model_experiment.current_arm())
        yield '{"type": "done"}'

    monkeypatch.setattr("routers.sandbox.stream_sandbox_response", spy_stream)
    response = await demo_chat(
        SandboxDemoChatRequest(message="Tell me about owls.", conversation_history=[]),
        _request(), auth={"role": "demo_code", "code": code},
    )
    [c async for c in response.body_iterator]
    assert seen == [model_experiment.arm_for(code)]


@pytest.mark.parametrize("role,revealed", [("demo_code", True), ("parent", False)])
async def test_the_arm_is_revealed_only_in_demo_feedback(armed, monkeypatch, role, revealed):
    from models.schemas import FeedbackRequest
    from routers import feedback

    sent = []

    async def fake_send(**kwargs):
        sent.append(kwargs["message"])
        return True

    async def fake_log(*a, **k):
        return None

    monkeypatch.setattr(settings, "feedback_email", "ops@example.com")
    monkeypatch.setattr(feedback, "send_feedback", fake_send)
    monkeypatch.setattr(feedback, "log_event", fake_log)
    code = _code_for(model_experiment.ARM_OPEN)
    await feedback.submit_feedback(
        FeedbackRequest(category="other", message="My guess: open"),
        _request(), auth={"role": role, "code": code},
    )
    assert ("[model experiment arm: open]" in sent[0]) is revealed
