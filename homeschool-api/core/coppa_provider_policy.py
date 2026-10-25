"""Child-data model egress qualification.

School pilot mode automatically blocks unqualified external model routes,
even if a public-demo switch is also configured by mistake. Outside the school pilot,
BEDE_COPPA_ENFORCE remains opt-in to avoid changing public demo behavior.
Never treat a credential, request flag or privacy statement as approval.
"""
from __future__ import annotations

import os
from ipaddress import ip_address, ip_network
from urllib.parse import urlsplit

_EXTERNAL = frozenset({"openai", "anthropic", "mistral"})
_TRUE = frozenset({"1", "true", "yes", "on"})
_PRIVATE_MODEL_NETWORKS = tuple(ip_network(cidr) for cidr in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7",
))


def enforcement_enabled() -> bool:
    """Enforce local-only inference for the real school pilot, fail closed.

    Import settings lazily: this module is also imported by the provider
    router while the application initializes. The demo is a separate
    synthetic-only surface and retains its existing opt-in behavior.
    """
    if os.environ.get("BEDE_COPPA_ENFORCE", "").strip().lower() in _TRUE:
        return True
    from core.config import settings
    # A public-demo switch must never downgrade an explicitly enabled
    # institutional pilot to unrestricted cloud routing. If both flags are
    # accidentally enabled, prefer the stricter local-only boundary.
    # The public demo alone (educator_pilot_enabled=False) is unchanged.
    return bool(settings.educator_pilot_enabled)


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
        # Normalize IPv4-mapped IPv6 before applying exact network rules.
        address = getattr(address, "ipv4_mapped", None) or address
        if address.is_loopback or any(address in network for network in _PRIVATE_MODEL_NETWORKS
                                      if address.version == network.version):
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
