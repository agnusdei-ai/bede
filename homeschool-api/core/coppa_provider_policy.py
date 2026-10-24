"""COPPA model egress qualification.

Opt-in enforcement preserves existing deployments while qualification is staged.
Set BEDE_COPPA_ENFORCE=true before accepting child data. Never treat a
provider credential, request flag, or public privacy statement as approval.
"""
from __future__ import annotations

import os

_EXTERNAL = frozenset({"openai", "anthropic", "mistral"})
_TRUE = frozenset({"1", "true", "yes", "on"})


def enforcement_enabled() -> bool:
    return os.environ.get("BEDE_COPPA_ENFORCE", "").strip().lower() in _TRUE


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
