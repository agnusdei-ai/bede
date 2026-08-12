"""
Peer identity check at accept time — bede-ipc-spec.md §2: "Peer identity is
checked at the OS level, not inside the protocol." `SO_PEERCRED` (Linux) /
`LOCAL_PEERCRED` (macOS) reads the connecting process's UID directly from
the kernel before a single protocol byte is trusted.

This is the actual identity boundary the spec describes — deliberately NOT
duplicated as a token inside the CBOR protocol (RequestBody carries no
caller-identity field), matching §5's own reasoning: a capability token
traveling over an already-peer-verified socket does not need to also prove
who is calling.

Windows named-pipe client-token equivalent is out of scope for this pass —
see services/locuto_ipc/__init__.py's module docstring for why.
"""
from __future__ import annotations

import os
import socket
import struct
import sys


class PeerAuthError(Exception):
    """The connecting process's credentials could not be read, or did not
    match an allowed UID. server.py must close the connection on this,
    never proceed to read a Hello frame from an unverified peer."""


def _linux_peer_uid(sock: socket.socket) -> int:
    # struct ucred { pid_t pid; uid_t uid; gid_t gid; } — three 4-byte ints
    # on every Linux architecture this codebase targets.
    fmt = "3i"
    size = struct.calcsize(fmt)
    raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, size)
    _pid, uid, _gid = struct.unpack(fmt, raw)
    return uid


def _macos_peer_uid(sock: socket.socket) -> int:
    # macOS's LOCAL_PEERCRED returns a `struct xucred`, whose second field
    # (after a version byte, padded to 4 bytes) is cr_uid. We only need the
    # uid, not the full struct.
    LOCAL_PEERCRED = 0x1  # SOL_LOCAL socket option, from <sys/ucred.h>
    SOL_LOCAL = 0  # getsockopt at the socket's own protocol level (0)
    fmt = "I I"  # cr_version (u32), cr_uid (u32) — leading fields of xucred
    size = struct.calcsize(fmt)
    raw = sock.getsockopt(SOL_LOCAL, LOCAL_PEERCRED, size)
    _version, uid = struct.unpack(fmt, raw)
    return uid


def get_peer_uid(sock: socket.socket) -> int:
    """Reads the connecting process's UID from the kernel. Raises
    PeerAuthError on any platform this isn't implemented for, or if the
    kernel call itself fails — never returns a guessed or default value."""
    if sys.platform.startswith("linux"):
        try:
            return _linux_peer_uid(sock)
        except OSError as exc:
            raise PeerAuthError(f"SO_PEERCRED failed: {exc}") from exc
    if sys.platform == "darwin":
        try:
            return _macos_peer_uid(sock)
        except OSError as exc:
            raise PeerAuthError(f"LOCAL_PEERCRED failed: {exc}") from exc
    raise PeerAuthError(
        f"peer credential check not implemented for platform {sys.platform!r} "
        "— Unix-socket peer auth is Linux/macOS only in this version"
    )


def check_peer(sock: socket.socket, allowed_uids: frozenset[int]) -> int:
    """Returns the peer's UID if it's in allowed_uids; raises PeerAuthError
    otherwise. `allowed_uids` defaults (server.py) to just this process's
    own UID — the ordinary case where Bede and the connecting Locuto
    process run as the same local user — but is a set so a household
    running the two as different local accounts can be configured
    explicitly, per the spec's own note on that case."""
    uid = get_peer_uid(sock)
    if uid not in allowed_uids:
        raise PeerAuthError(f"peer UID {uid} not in allowed set {sorted(allowed_uids)}")
    return uid


def default_allowed_uids() -> frozenset[int]:
    """This process's own UID — the ordinary single-user-household case."""
    return frozenset({os.getuid()})
