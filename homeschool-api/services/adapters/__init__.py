"""Provider-adapter layer decoupling ai_service.py from any single LLM vendor.

See base.py for the shared Anthropic-shaped vocabulary and router.py for how a
concrete adapter is selected (including the account-closure default that treats
a local vLLM/Qwen3-Coder server as the practical primary and never requires
Anthropic access to boot).
"""

from .router import (
    FailoverClient,
    get_default_client,
    resolve_with_failover,
)

__all__ = [
    "FailoverClient",
    "get_default_client",
    "resolve_with_failover",
]
