"""
Plain-language reasons an AI provider refused a request.

Why this exists: on 2026-11-17 every lesson on the public demo failed for
three different reasons at once (OpenAI had no credit, Mistral's plan did not
include the model, Claude refused the request) and every one of them reached
the child as "Something went wrong on my end", and the parent as nothing at
all. The provider's own error said exactly what was wrong each time; it was
just never read.

``classify()`` turns a provider exception into one short code and a sentence
a parent can act on. It reads the exception's class, HTTP status and the
provider's own message, never the request, so nothing a child wrote can
reach it. Codes are deliberately few: each one names a different thing for
the parent to go and fix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# What each code tells the parent to do. Plain English to match the settings
# card it appears in (AIProviderSettings.tsx is not localized yet).
_MESSAGES = {
    "ok": "Answering normally.",
    "no_credit": (
        "Out of credit or billing is not set up. Add credit in this provider's "
        "billing settings."
    ),
    "model_not_on_plan": (
        "Your plan with this provider does not include the model Bede asks for. "
        "Upgrade the plan, or set this provider's model setting to one your plan includes."
    ),
    "rate_limited": (
        "Refusing because of a rate limit: too many requests or too much text "
        "per minute for your plan. A higher plan raises the limit."
    ),
    "bad_key": "The API key was rejected. Check the key, or create a new one.",
    "unreachable": "Could not be reached. It may be down, or the address may be wrong.",
    "refused": "Refused the request. The provider's own message is below.",
    "unknown": "Failed for a reason Bede does not recognise. The provider's own message is below.",
}

_CREDIT_WORDS = ("credit", "billing", "quota", "insufficient_quota", "payment", "balance")
_PLAN_WORDS = ("subscription tier", "not available in your", "does not have access to model",
               "model_not_found", "not have access")


@dataclass(frozen=True)
class ProviderProblem:
    code: str
    message: str
    detail: str = ""  # the provider's own message, trimmed; never request content


def _status(exc: BaseException) -> Optional[int]:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _provider_message(exc: BaseException) -> str:
    # The SDKs' str(exc) is "Error code: 429 - <provider message>"; that is the
    # provider's text about the account, not anything we sent.
    text = " ".join(str(exc).split())
    return text[:240]


def classify(exc: BaseException) -> ProviderProblem:
    """One code and a parent-facing sentence for a provider's refusal."""
    status = _status(exc)
    detail = _provider_message(exc)
    lowered = detail.lower()
    name = type(exc).__name__

    def problem(code: str) -> ProviderProblem:
        return ProviderProblem(code=code, message=_MESSAGES[code], detail=detail)

    # Billing first: OpenAI reports "no credits" as a 429 and Anthropic reports
    # "credit balance is too low" as a 400, so the status alone would misfile both.
    if any(word in lowered for word in _CREDIT_WORDS):
        return problem("no_credit")
    if any(word in lowered for word in _PLAN_WORDS):
        return problem("model_not_on_plan")
    if status == 429 or name == "RateLimitError":
        return problem("rate_limited")
    if status == 401 or name == "AuthenticationError":
        return problem("bad_key")
    if status == 403 or name == "PermissionDeniedError":
        return problem("model_not_on_plan")
    if status == 404 or name == "NotFoundError":
        return problem("model_not_on_plan")
    if isinstance(exc, (ConnectionError, TimeoutError)) or name in (
        "APIConnectionError", "APITimeoutError",
    ):
        return problem("unreachable")
    if status == 400 or name == "BadRequestError":
        return problem("refused")
    return problem("unknown")


def message_for(code: str) -> str:
    return _MESSAGES.get(code, _MESSAGES["unknown"])
