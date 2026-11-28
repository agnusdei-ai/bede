"""
LOCAL_TTS_URL parsing: where Bede's own local voice is served.

The voice server receives every line Bede speaks, so it must be on the
family's own machine or network. Like core/scanner_url.py, locality is
decided from the LITERAL text only and never by resolving a name, because
resolving is itself a way for a name to reach somewhere remote.

Accepted hosts:
- a single-label name with no dots, which is how one compose service reaches
  another (`http://voice:5000`);
- `localhost`, and Docker Desktop's `host.docker.internal`;
- an IP literal that is loopback or private (10/8, 172.16/12, 192.168/16,
  fc00::/7), for a voice server running natively on the host or the LAN.

Anything else, including any dotted public hostname, is refused.
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


class VoiceUrlRefused(ValueError):
    pass


_NAMED_LOCAL_HOSTS = frozenset({"localhost", "host.docker.internal"})


def parse_voice_url(url: str) -> str | None:
    """-> None (no local voice) or the URL with any trailing slash removed."""
    url = (url or "").strip()
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise VoiceUrlRefused("LOCAL_TTS_URL must start with http:// or https://")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise VoiceUrlRefused("LOCAL_TTS_URL must be a plain address, with no credentials, query or fragment")
    host = (parts.hostname or "").lower()
    if not host:
        raise VoiceUrlRefused("LOCAL_TTS_URL must name a host")
    try:
        parts.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError as exc:
        raise VoiceUrlRefused("LOCAL_TTS_URL has an invalid port") from exc
    if host in _NAMED_LOCAL_HOSTS:
        return url.rstrip("/")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError as exc:
        if "." in host or ":" in host:
            raise VoiceUrlRefused(
                "LOCAL_TTS_URL must be this computer or its own network: a compose service name "
                "such as http://voice:5000, localhost, host.docker.internal, or a private IP"
            ) from exc
        return url.rstrip("/")
    if ip.is_loopback or (ip.is_private and not ip.is_link_local and not ip.is_unspecified):
        return url.rstrip("/")
    raise VoiceUrlRefused("LOCAL_TTS_URL must be a loopback or private address, never a public one")
