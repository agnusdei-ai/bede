"""
PRACTICE_SCANNER_URL parsing. Pure and dependency-free so core/config.py can
refuse a bad value at boot and services/practice/upload_safety.py can check
again, from the one definition, before it opens a socket.

The scanner receives the original, unmodified worksheet bytes, so it must be
local: a unix socket, or TCP on the loopback interface. Locality is decided
from the LITERAL text only, never by resolving a name -- resolving is itself a
path for a hostname to reach somewhere remote, and a name that resolves to
loopback today is not a promise about tomorrow. A clamd in another container
is reached through a shared unix-socket volume, not over tcp.
"""
from __future__ import annotations

import ipaddress


class ScannerUrlRefused(ValueError):
    pass


def parse_scanner_url(url: str) -> tuple | None:
    """-> None (no scanner), ("unix", path) or ("tcp", loopback_ip, port)."""
    url = (url or "").strip()
    if not url:
        return None
    if url.startswith("unix://"):
        path = url[len("unix://"):]
        if not path.startswith("/") or "\0" in path:
            raise ScannerUrlRefused("a unix scanner URL must be unix:///absolute/path")
        return ("unix", path)
    if url.startswith("tcp://"):
        rest = url[len("tcp://"):]
        host, sep, port_text = rest.rpartition(":")
        if not sep or not port_text.isdigit() or not 0 < int(port_text) < 65536:
            raise ScannerUrlRefused("a tcp scanner URL must be tcp://127.0.0.1:3310 (host and port)")
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        if host.lower() == "localhost":
            return ("tcp", "127.0.0.1", int(port_text))
        try:
            address = ipaddress.ip_address(host)  # parses text only; never resolves
        except ValueError:
            raise ScannerUrlRefused(
                "the scanner must be on this machine: use a loopback IP address or a unix socket, not a hostname"
            ) from None
        if not address.is_loopback:
            raise ScannerUrlRefused(
                "the scanner must be on this machine: only loopback addresses or a unix socket are allowed"
            )
        return ("tcp", str(address), int(port_text))
    raise ScannerUrlRefused("PRACTICE_SCANNER_URL must start with unix:// or tcp://")
