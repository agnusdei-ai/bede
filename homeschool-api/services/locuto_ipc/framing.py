"""
Wire framing — bede-ipc-spec.md §3, implemented literally rather than
reinterpreted:

    version   : u8
    msg_type  : u8
    length    : u32, big-endian
    body      : length bytes, CBOR (RFC 8949), deterministic encoding

HEADER_LEN = 6. MAX_BODY_LEN = 262_144 (256 KiB). A declared `length` over
the bound is refused BEFORE a byte is reserved for it — read_frame() checks
the header's length field before ever calling reader.readexactly() for the
body, so an attacker (or a bug) cannot make this allocate ahead of the
bound it's supposed to enforce.

CBOR via `cbor2` — deterministic (canonical) encoding on write, and
`decode()` below is the one function that raises FrameError as SPEC
prescribes (unknown fields must be a request-level "Refused"/"Error"
outcome, not silently accepted — that's a protocol.py-level decision,
downstream of this module; this module cares only about the frame itself
being well-formed CBOR).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any

import cbor2

HEADER_LEN = 6
MAX_BODY_LEN = 262_144  # 256 KiB — bede-ipc-spec.md §3

_HEADER_STRUCT = struct.Struct(">BBI")  # version(u8) msg_type(u8) length(u32 BE)

PROTOCOL_VERSION = 1


class FrameError(Exception):
    """A malformed frame — bad header, oversized length, or unparseable
    CBOR body. Callers (server.py) must treat this as a reason to close
    the connection, never as a reason to retry or to interpret partial
    data."""


@dataclass(frozen=True)
class Frame:
    version: int
    msg_type: int
    body: dict[str, Any]


def encode_header(version: int, msg_type: int, body_len: int) -> bytes:
    if not (0 <= version <= 255):
        raise FrameError(f"version out of range: {version!r}")
    if not (0 <= msg_type <= 255):
        raise FrameError(f"msg_type out of range: {msg_type!r}")
    if body_len > MAX_BODY_LEN:
        raise FrameError(f"body_len {body_len} exceeds MAX_BODY_LEN {MAX_BODY_LEN}")
    return _HEADER_STRUCT.pack(version, msg_type, body_len)


def decode_header(raw: bytes) -> tuple[int, int, int]:
    """Returns (version, msg_type, length). Raises FrameError on a
    malformed header or a declared length over MAX_BODY_LEN — this is the
    check that must run before the caller reads a single body byte."""
    if len(raw) != HEADER_LEN:
        raise FrameError(f"header must be exactly {HEADER_LEN} bytes, got {len(raw)}")
    version, msg_type, length = _HEADER_STRUCT.unpack(raw)
    if length > MAX_BODY_LEN:
        raise FrameError(f"declared length {length} exceeds MAX_BODY_LEN {MAX_BODY_LEN}")
    return version, msg_type, length


def encode_body(body: dict[str, Any]) -> bytes:
    """Deterministic (canonical) CBOR encoding — spec §3's own requirement,
    and the same reason canonical encoding matters anywhere two independent
    implementations must agree byte-for-byte on what a given value encodes
    to."""
    return cbor2.dumps(body, canonical=True)


def decode_body(raw: bytes) -> dict[str, Any]:
    """Raises FrameError on unparseable CBOR, or on a body that doesn't
    decode to a map — every message type in this protocol has a
    map-shaped body (bede-ipc-spec.md §5), so anything else is malformed
    by construction, not a valid-but-unexpected shape."""
    try:
        value = cbor2.loads(raw)
    except Exception as exc:  # cbor2 raises its own exception hierarchy
        raise FrameError(f"unparseable CBOR body: {exc}") from exc
    if not isinstance(value, dict):
        raise FrameError(f"body must decode to a CBOR map, got {type(value).__name__}")
    return value


def encode_frame(msg_type: int, body: dict[str, Any]) -> bytes:
    """One complete frame — header + body — ready to write to the socket."""
    body_bytes = encode_body(body)
    header = encode_header(PROTOCOL_VERSION, msg_type, len(body_bytes))
    return header + body_bytes
