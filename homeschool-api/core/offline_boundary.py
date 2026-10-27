"""Opt-in Python network boundary for a single-machine offline installation.

Not an OS sandbox: operators must also deny external egress for the API,
model server, database, and browser. Models must be provisioned beforehand.
"""
from __future__ import annotations

import ipaddress
import socket
import sys
from urllib.parse import urlsplit

_installed = False


def is_loopback_host(host: object) -> bool:
    if host in (None, "", "localhost", b"localhost"):
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="replace")
    try:
        address = ipaddress.ip_address(str(host))
        mapped = getattr(address, "ipv4_mapped", None)
        return (mapped or address).is_loopback
    except ValueError:
        return False


def validate_local_model_url(url: str) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or not is_loopback_host(parsed.hostname)
            or parsed.username or parsed.password):
        raise ValueError("Offline installations require a loopback local model URL")


def _audit_network(event: str, args: tuple) -> None:
    if event in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr"):
        if not is_loopback_host(args[0]):
            raise PermissionError("Offline installation: external name resolution denied")
    elif event in ("socket.connect", "socket.sendto", "socket.sendmsg"):
        sock, address = args[:2]
        if sock.family == socket.AF_UNIX:
            return
        # A connected socket's sendmsg may have no destination; its connect
        # was already checked. Never permit an external explicit destination.
        if address is None and event == "socket.sendmsg":
            return
        if (sock.family not in (socket.AF_INET, socket.AF_INET6)
                or not isinstance(address, tuple) or not address
                or not is_loopback_host(address[0])):
            raise PermissionError("Offline installation: external network access denied")


def install_offline_boundary(settings) -> None:
    """Install before importing network clients; a restart is needed to disable."""
    global _installed
    if not settings.bede_offline_installation:
        return
    validate_local_model_url(settings.local_llm_base_url)
    if not _installed:
        sys.addaudithook(_audit_network)
        _installed = True
