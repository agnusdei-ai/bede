"""Child-data model egress qualification.

School pilot mode automatically blocks unqualified external model routes,
regardless of the legacy opt-in environment flag. Outside the school pilot,
BEDE_COPPA_ENFORCE remains opt-in to avoid changing public demo behavior.
Never treat a credential, request flag or privacy statement as approval.
"""
from __future__ import annotations

import os
from ipaddress import ip_address
from urllib.parse import urlsplit

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



def require_qualified_local_endpoint(base_url: str) -> None:
    """Reject cloud/ambiguous endpoints masquerading as the local adapter.

    Applies only when child-data egress enforcement is active. This is an
    address-shape guard, not DNS, routing, TLS or host ownership attestation.
    The school-managed Mac host may be reached through Docker Desktop's
    host.docker.internal name or a private LAN IP.
    """
    if not enforcement_enabled():
        return
    if not isinstance(base_url, str) or not base_url:
        raise PermissionError("COPPA: local model endpoint is not qualified")
    try:
        parsed = urlsplit(base_url)
        hostname = parsed.hostname
        port = parsed.port  # Reject malformed/out-of-range ports.
        if (parsed.scheme not in ("http", "https") or
                not hostname or not parsed.netloc or
                parsed.username is not None or parsed.password is not None or
                parsed.query or parsed.fragment or port == 0):
            raise ValueError("Malformed or ambiguous endpoint")
        if hostname in ("localhost", "host.docker.internal"):
            return
        address = ip_address(hostname)
        if address.is_loopback or (address.is_private and not (
            address.is_link_local or address.is_unspecified or address.is_multicast
        )):
            return
    except (ValueError, TypeError):
        pass
    raise PermissionError("COPPA: local model endpoint is not qualified")


def require_external_feature(feature: str) -> None:
    """Guard direct external audio/embedding/other child-data egress."""
    if enforcement_enabled():
        raise PermissionError(
            f"COPPA: external {feature} is disabled pending provider qualification"
        )
