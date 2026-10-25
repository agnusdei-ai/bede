"""Anthropic adapter — the trivial case.

`anthropic.AsyncAnthropic` already IS the shape ai_service.py was written
against (it defines the Messages API this whole adapter layer translates other
providers TO), so the "adapter" here is just its constructor. Keeping it behind
a function rather than inlining `anthropic.AsyncAnthropic(...)` in the router is
what lets the router treat every provider uniformly.

Returning the real SDK object (not a wrapper) is load-bearing: the default,
zero-env-var configuration resolves `_client` to exactly this, so the existing
tests that do `patch.object(ai_service._client.messages, "stream", ...)` keep
patching a genuine SDK client exactly as they did before this refactor.
"""

from __future__ import annotations

import anthropic


def build_anthropic_client(api_key: str) -> anthropic.AsyncAnthropic:
    # Guard the factory itself: a direct caller must not bypass the router's
    # institutional pilot provider policy. Check before constructing an SDK
    # client so a denied request cannot instantiate a cloud transport.
    from core.coppa_provider_policy import approved_provider
    if not approved_provider("anthropic"):
        raise PermissionError("COPPA provider qualification required")
    return anthropic.AsyncAnthropic(api_key=api_key)
