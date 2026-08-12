"""
Message-type table and Request/Response body shapes — bede-ipc-spec.md §4
and §5, transcribed as a closed set rather than an open one: an
unrecognized msg_type is refused on receipt (server.py closes the
connection), never skipped as though it might be a forward-compatible
extension. A new message type is a spec change on the Locuto side first,
never something either implementation invents locally.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Any, Optional


class MsgType(IntEnum):
    HELLO = 0x01
    HELLO_ACK = 0x02
    REQUEST = 0x03
    RESPONSE = 0x04
    PING = 0x05
    PONG = 0x06
    BYE = 0x07
    # 0x08-0xFF are reserved and refused on receipt — see server.py's
    # dispatch, which closes the connection for anything not listed above
    # rather than silently ignoring it.


class Outcome(str, Enum):
    """bede-ipc-spec.md §5's closed outcome set. String-valued (not an
    int) because it travels inside a CBOR map body, not the frame header —
    only msg_type lives in the fixed header."""

    SUCCEEDED = "Succeeded"
    REFUSED = "Refused"
    UNAVAILABLE = "Unavailable"
    ERROR = "Error"


@dataclass(frozen=True)
class RequestBody:
    """bede-ipc-spec.md §5's Request body. `input` is a capability-specific
    CBOR map, deliberately typed as Any here — capabilities.py's registry
    (empty in v1) is what would give each capability its own real input
    schema; nothing here presumes what any of them looks like."""

    request_id: bytes  # 16 random bytes, for audit correlation only
    capability: str
    input: dict[str, Any]
    expiry: int  # Unix timestamp
    max_response_bytes: int

    def is_expired(self, now: Optional[float] = None) -> bool:
        return (now if now is not None else time.time()) > self.expiry

    @classmethod
    def from_body(cls, body: dict[str, Any]) -> "RequestBody":
        try:
            request_id = body["request_id"]
            capability = body["capability"]
            input_ = body["input"]
            expiry = body["expiry"]
            max_response_bytes = body["max_response_bytes"]
        except KeyError as exc:
            raise ValueError(f"Request body missing required field: {exc}") from exc
        if not isinstance(request_id, bytes) or len(request_id) != 16:
            raise ValueError("request_id must be exactly 16 bytes")
        if not isinstance(capability, str):
            raise ValueError("capability must be a string")
        if not isinstance(input_, dict):
            raise ValueError("input must be a CBOR map")
        if not isinstance(expiry, (int, float)):
            raise ValueError("expiry must be a Unix timestamp")
        if not isinstance(max_response_bytes, int) or max_response_bytes < 0:
            raise ValueError("max_response_bytes must be a non-negative integer")
        return cls(
            request_id=request_id,
            capability=capability,
            input=input_,
            expiry=int(expiry),
            max_response_bytes=max_response_bytes,
        )


@dataclass(frozen=True)
class ResponseBody:
    """bede-ipc-spec.md §5's Response body. `output` is present only when
    outcome is Succeeded — enforced in to_body() below, not left to the
    caller to remember."""

    request_id: bytes
    outcome: Outcome
    output: Optional[dict[str, Any]] = None

    def to_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "request_id": self.request_id,
            "outcome": self.outcome.value,
        }
        if self.outcome is Outcome.SUCCEEDED:
            body["output"] = self.output if self.output is not None else {}
        return body


def unavailable(request_id: bytes) -> ResponseBody:
    """bede-ipc-spec.md §7's disclosed-unavailability shape — the response
    a Request handler must produce when resolve_local_only() raises
    LocalAdapterUnavailableError, and the ONLY response it may produce in
    that case (never a retry against a different adapter)."""
    return ResponseBody(request_id=request_id, outcome=Outcome.UNAVAILABLE)


def refused(request_id: bytes) -> ResponseBody:
    """The response for a Request naming a capability not in the (v1:
    empty) registry, or an expired Request."""
    return ResponseBody(request_id=request_id, outcome=Outcome.REFUSED)


def error(request_id: bytes) -> ResponseBody:
    """Reserved for a malformed request or an internal fault distinct
    from 'the backend is unreachable right now' — spec §7."""
    return ResponseBody(request_id=request_id, outcome=Outcome.ERROR)


@dataclass(frozen=True)
class HelloBody:
    protocol_version: int
    client_identity: str = ""


@dataclass(frozen=True)
class HelloAckBody:
    """`policy_hash` is a partial answer to decision-packets.md packet 12,
    not a resolution of it — see LOCUTO_CONNECTOR_DECISIONS.md packet 2.
    It gives Locuto something concrete to log and compare across sessions;
    it is not `agents.md` §5's full measurement bar (publisher-signed
    runtime, independently verified hash-pin)."""

    protocol_version: int
    server_identity: str
    policy_hash: str
    adapter_identity: str

    def to_body(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "server_identity": self.server_identity,
            "policy_hash": self.policy_hash,
            "adapter_identity": self.adapter_identity,
        }
