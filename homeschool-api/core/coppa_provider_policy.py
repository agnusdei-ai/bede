"""Child-data model egress qualification.

School pilot mode automatically blocks unqualified external model routes,
regardless of the legacy opt-in environment flag. Outside the school pilot,
BEDE_COPPA_ENFORCE remains opt-in to avoid changing public demo behavior.
Never treat a credential, request flag or privacy statement as approval.
"""
from __future__ import annotations

import os

_EXTERNAL = frozenset({"openai", "anthropic", "mistral"})
_TRUE = frozenset({"1", "true", "yes", "on"})


def enforcement_enabled() -> bool:
    """Enforce local-only inference for the real school pilot, fail closed.

    Import settings lazily: this module is also imported by the provider
    router while the application initializes. The demo is a separate
    synthetic-only surface and retains its existing opt-in behavior.
    """
    if os.environ.get("BEDE_COPPA_ENFORCE", "").strip().lower() in _TRUE:
        return True
    from core.config import settings
    return bool(settings.educator_pilot_enabled and not settings.is_demo_deployment)


def approved_provider(name: str) -> bool:
    """Fail closed for cloud providers when COPPA enforcement is enabled.

    A separately signed, time-bounded provider approval registry is still
    required before any external provider can be allowed in this mode.
    """
    if not enforcement_enabled():
        return True
    return name == "local"


def require_external_feature(feature: str) -> None:
    """Guard direct external audio/embedding/other child-data egress."""
    if enforcement_enabled():
        raise PermissionError(
            f"COPPA: external {feature} is disabled pending provider qualification"
        )
