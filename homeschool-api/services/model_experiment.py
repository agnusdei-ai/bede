"""Temporary, blind demo experiment: today's stack vs. US-developed open models.

Off unless every one of DEMO_MODEL_EXPERIMENT_SALT, EXPERIMENT_LLM_BASE_URL,
EXPERIMENT_LLM_API_KEY and EXPERIMENT_TUTOR_MODEL is set, so no deployment
changes behaviour without all four. Built to be REMOVED after the experiment:
this module, its config block, the `bind()` calls in routers/tutor.py and
routers/sandbox.py, the hook in services/adapters/router.py, and the
disclosure lines naming OpenRouter all go together (docs/DEMO_MODEL_EXPERIMENT.md).

Each public-demo session (a demo code) is assigned an arm by a keyed hash of
its code, so the assignment is stable for the whole session, roughly 50/50
across sessions, and unpredictable without the salt. The open arm serves the
tutor turn from EXPERIMENT_TUTOR_MODEL. That is the only model slot a demo
visitor reaches: every tool call is made inline in the tutor's own streamed
reply, and the session summary and learner-profile synthesis are parent-only.
To compare two open models, run the experiment twice with a different
EXPERIMENT_TUTOR_MODEL. Three things deliberately do NOT move:

* **Moderation.** The pre-turn safety classifier fails open, so a weaker or
  reasoning-budget-starved model there would silently stop self-harm
  screening for a child. `services/moderation.py` calls `suspended()` around
  its call, and the classifier stays on the production stack in both arms.
  A visitor cannot perceive moderation, so this costs the blind test nothing.
* **Voice.** Text-to-speech and transcription are not chat-model calls.
* **Real families.** Only demo_code sessions are ever bound.

If the open model errors, the turn fails over to the production stack exactly
as any provider failure does, so a visitor is never left without an answer.

The arm is revealed only in the operator's own feedback email
(routers/feedback.py), after the guess has been written and sent.
"""
from __future__ import annotations

import contextlib
import contextvars
import hashlib
import hmac
from typing import Any, Iterator, Optional
from urllib.parse import urlsplit

from core.config import settings

ARM_OPEN = "open"
ARM_BASELINE = "baseline"

# The adapter name FailoverClient uses for the open arm. Deliberately not one
# of services/adapters/router.py's _KNOWN_ADAPTERS, so it can never appear in
# BEDE_ADAPTER_ORDER, the admin provider switcher, or a household's routing.
ADAPTER_NAME = "experiment"

_bound_code: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "bede_model_experiment_code", default=None,
)

_client: Any = None


def enabled() -> bool:
    if not (
        settings.demo_model_experiment_salt
        and settings.experiment_llm_base_url
        and settings.experiment_llm_api_key
        and settings.experiment_tutor_model
    ):
        return False
    # The key travels in an Authorization header; never over plain HTTP.
    return urlsplit(settings.experiment_llm_base_url).scheme == "https"


def arm_for(code: str) -> str:
    digest = hmac.new(
        settings.demo_model_experiment_salt.encode(), code.encode(), hashlib.sha256,
    ).digest()
    return ARM_OPEN if digest[0] & 1 else ARM_BASELINE


def bind(code: Optional[str]) -> None:
    """Bind this request's demo code. Called only for the demo_code role.
    Each request runs in its own context copy, so this never leaks into
    another request and needs no reset."""
    if code:
        _bound_code.set(code)


def current_arm() -> Optional[str]:
    code = _bound_code.get()
    if not code or not enabled():
        return None
    return arm_for(code)


@contextlib.contextmanager
def suspended() -> Iterator[None]:
    """Serve the enclosed calls from the production stack whatever the arm."""
    token = _bound_code.set(None)
    try:
        yield
    finally:
        _bound_code.reset(token)


def client() -> Any:
    global _client
    if _client is None:
        from services.adapters.openai_compatible_adapter import OpenAICompatibleClient

        _client = OpenAICompatibleClient(
            base_url=settings.experiment_llm_base_url,
            api_key=settings.experiment_llm_api_key,
            model=settings.experiment_tutor_model,
        )
    return _client
