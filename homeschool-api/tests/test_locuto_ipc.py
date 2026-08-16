"""
Tests for services/locuto_ipc/ — Bede's half of the proposed Locuto local-IPC
connector (agnusdei-ai/locuto's docs/bede-ipc-spec.md). v1 scope: transport,
framing, handshake, and Request/Response dispatch with an EMPTY capability
registry — see that package's own __init__.py docstring for why no real
capability is registered yet.
"""
import asyncio
import os
import socket
import struct
import tempfile
import time
from pathlib import Path

import cbor2
import pytest

import services.locuto_ipc.capabilities as capabilities_module
import services.locuto_ipc.peer_auth as peer_auth
import services.locuto_ipc.server as server_module
from core.config import settings
from services.adapters.router import LocalAdapterUnavailableError
from services.locuto_ipc.framing import (
    FrameError,
    HEADER_LEN,
    MAX_BODY_LEN,
    decode_body,
    decode_header,
    encode_body,
    encode_frame,
    encode_header,
)
from services.locuto_ipc.protocol import (
    HelloAckBody,
    MsgType,
    Outcome,
    RequestBody,
    ResponseBody,
    error,
    refused,
    unavailable,
)

# ── framing.py ────────────────────────────────────────────────────────────

def test_header_roundtrip():
    header = encode_header(1, MsgType.HELLO, 42)
    version, msg_type, length = decode_header(header)
    assert (version, msg_type, length) == (1, MsgType.HELLO, 42)


def test_header_is_exactly_six_bytes():
    header = encode_header(1, MsgType.PING, 0)
    assert len(header) == HEADER_LEN == 6


def test_decode_header_rejects_wrong_length():
    with pytest.raises(FrameError):
        decode_header(b"\x01\x02\x03")


def test_decode_header_rejects_oversized_declared_length():
    """The bound MUST be enforced from the header alone, before any body
    byte is read — this is what stops an attacker from making the server
    allocate ahead of the bound meant to prevent exactly that."""
    oversized = struct.pack(">BBI", 1, MsgType.REQUEST, MAX_BODY_LEN + 1)
    with pytest.raises(FrameError):
        decode_header(oversized)


def test_encode_header_rejects_oversized_body_len():
    with pytest.raises(FrameError):
        encode_header(1, MsgType.REQUEST, MAX_BODY_LEN + 1)


def test_body_roundtrip_via_cbor():
    body = {"a": 1, "b": "text", "c": b"\x00\x01", "d": [1, 2, 3]}
    encoded = encode_body(body)
    assert decode_body(encoded) == body


def test_decode_body_rejects_unparseable_cbor():
    with pytest.raises(FrameError):
        decode_body(b"\xff\xff\xff not cbor")


def test_decode_body_rejects_a_non_map_top_level_value():
    # A valid CBOR array, not a map — every message body in this protocol
    # is map-shaped (bede-ipc-spec.md §5), so this must be refused.
    encoded = cbor2.dumps([1, 2, 3])
    with pytest.raises(FrameError):
        decode_body(encoded)


def test_encode_frame_produces_header_plus_body():
    frame = encode_frame(MsgType.PING, {})
    version, msg_type, length = decode_header(frame[:HEADER_LEN])
    assert msg_type == MsgType.PING
    assert length == len(frame) - HEADER_LEN
    assert decode_body(frame[HEADER_LEN:]) == {}


# ── protocol.py ───────────────────────────────────────────────────────────

def _valid_request_body(**overrides):
    body = {
        "request_id": b"0" * 16,
        "capability": "SomeCapability",
        "input": {"foo": "bar"},
        "expiry": int(time.time()) + 60,
        "max_response_bytes": 4096,
    }
    body.update(overrides)
    return body


def test_request_body_parses_a_valid_shape():
    req = RequestBody.from_body(_valid_request_body())
    assert req.capability == "SomeCapability"
    assert req.max_response_bytes == 4096
    assert not req.is_expired()


@pytest.mark.parametrize("missing", ["request_id", "capability", "input", "expiry", "max_response_bytes"])
def test_request_body_rejects_a_missing_field(missing):
    body = _valid_request_body()
    del body[missing]
    with pytest.raises(ValueError):
        RequestBody.from_body(body)


def test_request_body_rejects_a_short_request_id():
    with pytest.raises(ValueError):
        RequestBody.from_body(_valid_request_body(request_id=b"tooshort"))


def test_request_body_rejects_a_non_dict_input():
    with pytest.raises(ValueError):
        RequestBody.from_body(_valid_request_body(input="not a dict"))


def test_request_body_is_expired_true_in_the_past():
    req = RequestBody.from_body(_valid_request_body(expiry=int(time.time()) - 1))
    assert req.is_expired()


def test_response_body_omits_output_unless_succeeded():
    resp = ResponseBody(request_id=b"x" * 16, outcome=Outcome.REFUSED)
    assert "output" not in resp.to_body()


def test_response_body_includes_output_when_succeeded():
    resp = ResponseBody(request_id=b"x" * 16, outcome=Outcome.SUCCEEDED, output={"text": "hi"})
    assert resp.to_body()["output"] == {"text": "hi"}


def test_response_body_succeeded_with_no_output_defaults_to_empty_map():
    resp = ResponseBody(request_id=b"x" * 16, outcome=Outcome.SUCCEEDED)
    assert resp.to_body()["output"] == {}


def test_unavailable_refused_error_helpers_produce_the_right_outcome():
    rid = b"y" * 16
    assert unavailable(rid).outcome is Outcome.UNAVAILABLE
    assert refused(rid).outcome is Outcome.REFUSED
    assert error(rid).outcome is Outcome.ERROR


def test_hello_ack_body_serializes_all_four_fields():
    ack = HelloAckBody(protocol_version=1, server_identity="bede", policy_hash="abc", adapter_identity="local:m")
    body = ack.to_body()
    assert body == {
        "protocol_version": 1,
        "server_identity": "bede",
        "policy_hash": "abc",
        "adapter_identity": "local:m",
    }


# ── peer_auth.py — real SO_PEERCRED against a live AF_UNIX socketpair ─────

def test_check_peer_returns_our_own_uid_over_a_real_socketpair():
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        uid = peer_auth.check_peer(a, frozenset({os.getuid()}))
        assert uid == os.getuid()
    finally:
        a.close()
        b.close()


def test_check_peer_rejects_a_uid_not_in_the_allowed_set():
    a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        with pytest.raises(peer_auth.PeerAuthError):
            peer_auth.check_peer(a, frozenset({os.getuid() + 99999}))
    finally:
        a.close()
        b.close()


def test_default_allowed_uids_is_just_this_process():
    assert peer_auth.default_allowed_uids() == frozenset({os.getuid()})


# ── capabilities.py ─────────────────────────────────────────────────────

def test_registry_is_empty_in_v1():
    """The whole point of this version — see the package's own docstring.
    A future PR registering a real capability is expected to change this;
    if it fails unexpectedly, that's a signal this test needs a deliberate
    update, not silent breakage."""
    assert capabilities_module.CAPABILITIES == {}


def test_is_registered_false_for_any_name_in_v1():
    assert capabilities_module.is_registered("DraftReplyFromUserSelectedText") is False


def test_get_handler_returns_none_for_an_unregistered_capability():
    assert capabilities_module.get_handler("AnythingAtAll") is None


# ── server.py — end-to-end over a real Unix socket ─────────────────────────

@pytest.fixture
def socket_path(tmp_path):
    return str(tmp_path / "sub" / "locuto.sock")


@pytest.fixture(autouse=True)
def _reset_locuto_ipc_enabled():
    original = settings.locuto_ipc_enabled
    yield
    settings.locuto_ipc_enabled = original


@pytest.fixture(autouse=True)
def _clear_capability_registry():
    """Tests below register a temp capability to exercise dispatch/§6 —
    always restore the empty registry afterward so no test's fixture
    leaks into another's "registry is empty" assumption."""
    original = dict(capabilities_module.CAPABILITIES)
    yield
    capabilities_module.CAPABILITIES.clear()
    capabilities_module.CAPABILITIES.update(original)


async def _run_server(path):
    settings.locuto_ipc_enabled = True
    task = asyncio.create_task(server_module.serve(path))
    # Wait for the socket file to actually appear rather than a fixed sleep.
    for _ in range(200):
        if Path(path).exists():
            break
        await asyncio.sleep(0.01)
    else:
        task.cancel()
        raise RuntimeError("server did not bind within timeout")
    return task


async def _connect(path):
    return await asyncio.open_unix_connection(path=path)


async def _send(writer, msg_type, body):
    writer.write(encode_frame(msg_type, body))
    await writer.drain()


async def _recv(reader):
    header = await reader.readexactly(HEADER_LEN)
    _version, msg_type, length = decode_header(header)
    body_raw = await reader.readexactly(length)
    return msg_type, decode_body(body_raw)


async def _handshake(reader, writer):
    await _send(writer, MsgType.HELLO, {"protocol_version": 1, "client_identity": "test"})
    return await _recv(reader)


@pytest.mark.asyncio
async def test_serve_refuses_to_bind_when_disabled(socket_path):
    """Disabled means no socket — but serve() deliberately idles rather
    than returning (see server.py's own docstring: a returning coroutine
    would exit `python -m services.locuto_ipc` and Docker would
    restart-loop the always-on container), so this asserts "still running,
    never bound" rather than "returned"."""
    settings.locuto_ipc_enabled = False
    task = asyncio.create_task(server_module.serve(socket_path))
    try:
        await asyncio.sleep(0.05)
        assert not task.done()
        assert not Path(socket_path).exists()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_socket_file_permissions_match_spec(socket_path):
    task = await _run_server(socket_path)
    try:
        mode = os.stat(socket_path).st_mode & 0o777
        assert mode == 0o600
        parent_mode = os.stat(Path(socket_path).parent).st_mode & 0o777
        assert parent_mode == 0o700
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_hello_gets_a_hello_ack_with_all_four_fields(socket_path):
    task = await _run_server(socket_path)
    try:
        reader, writer = await _connect(socket_path)
        msg_type, body = await _handshake(reader, writer)
        assert msg_type == MsgType.HELLO_ACK
        assert body["protocol_version"] == 1
        assert body["server_identity"] == server_module.SERVER_IDENTITY
        assert "policy_hash" in body
        assert "adapter_identity" in body
        writer.close()
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_non_hello_first_message_closes_the_connection(socket_path):
    task = await _run_server(socket_path)
    try:
        reader, writer = await _connect(socket_path)
        await _send(writer, MsgType.PING, {})
        with pytest.raises((asyncio.IncompleteReadError, ConnectionError)):
            await _recv(reader)
        writer.close()
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_ping_gets_a_pong_and_the_connection_stays_open(socket_path):
    task = await _run_server(socket_path)
    try:
        reader, writer = await _connect(socket_path)
        await _handshake(reader, writer)
        await _send(writer, MsgType.PING, {})
        msg_type, body = await _recv(reader)
        assert msg_type == MsgType.PONG
        assert body == {}
        # Connection is still usable — a second Ping still works.
        await _send(writer, MsgType.PING, {})
        msg_type, _ = await _recv(reader)
        assert msg_type == MsgType.PONG
        writer.close()
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_bye_closes_the_connection_cleanly(socket_path):
    task = await _run_server(socket_path)
    try:
        reader, writer = await _connect(socket_path)
        await _handshake(reader, writer)
        await _send(writer, MsgType.BYE, {})
        # Server closes its side — a subsequent read hits EOF.
        data = await reader.read(1)
        assert data == b""
        writer.close()
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_request_for_an_unregistered_capability_is_refused(socket_path):
    task = await _run_server(socket_path)
    try:
        reader, writer = await _connect(socket_path)
        await _handshake(reader, writer)
        request_id = b"r" * 16
        await _send(writer, MsgType.REQUEST, {
            "request_id": request_id,
            "capability": "NotARealCapability",
            "input": {},
            "expiry": int(time.time()) + 60,
            "max_response_bytes": 4096,
        })
        msg_type, body = await _recv(reader)
        assert msg_type == MsgType.RESPONSE
        assert body["request_id"] == request_id
        assert body["outcome"] == Outcome.REFUSED.value
        assert "output" not in body
        writer.close()
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_expired_request_is_refused_before_any_capability_lookup(socket_path):
    task = await _run_server(socket_path)
    try:
        reader, writer = await _connect(socket_path)
        await _handshake(reader, writer)
        request_id = b"e" * 16
        await _send(writer, MsgType.REQUEST, {
            "request_id": request_id,
            "capability": "AnyCapability",
            "input": {},
            "expiry": int(time.time()) - 5,
            "max_response_bytes": 4096,
        })
        msg_type, body = await _recv(reader)
        assert body["outcome"] == Outcome.REFUSED.value
        writer.close()
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_a_second_request_on_the_same_connection_is_refused_and_closed(socket_path):
    """bede-ipc-spec.md §1: one connection serves exactly one invocation."""
    task = await _run_server(socket_path)
    try:
        reader, writer = await _connect(socket_path)
        await _handshake(reader, writer)
        first_id = b"1" * 16
        await _send(writer, MsgType.REQUEST, {
            "request_id": first_id, "capability": "X", "input": {},
            "expiry": int(time.time()) + 60, "max_response_bytes": 4096,
        })
        msg_type, body = await _recv(reader)
        assert body["request_id"] == first_id

        second_id = b"2" * 16
        await _send(writer, MsgType.REQUEST, {
            "request_id": second_id, "capability": "X", "input": {},
            "expiry": int(time.time()) + 60, "max_response_bytes": 4096,
        })
        with pytest.raises((asyncio.IncompleteReadError, ConnectionError)):
            await _recv(reader)
        writer.close()
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_malformed_frame_closes_the_connection(socket_path):
    task = await _run_server(socket_path)
    try:
        reader, writer = await _connect(socket_path)
        await _handshake(reader, writer)
        # A well-formed header but a body that isn't valid CBOR.
        bad_body = b"\xff\xff\xff\xff"
        writer.write(encode_header(1, MsgType.PING, len(bad_body)) + bad_body)
        await writer.drain()
        with pytest.raises((asyncio.IncompleteReadError, ConnectionError)):
            await _recv(reader)
        writer.close()
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_reserved_msg_type_closes_the_connection(socket_path):
    task = await _run_server(socket_path)
    try:
        reader, writer = await _connect(socket_path)
        await _handshake(reader, writer)
        await _send(writer, 0xAB, {})  # reserved, per §4
        with pytest.raises((asyncio.IncompleteReadError, ConnectionError)):
            await _recv(reader)
        writer.close()
    finally:
        task.cancel()


# ── §6 enforcement — the routing rule that matters most ────────────────────

@pytest.mark.asyncio
async def test_a_registered_capability_that_succeeds_returns_its_output(socket_path):
    async def handler(input_body):
        return {"echo": input_body.get("value")}

    capabilities_module.CAPABILITIES["EchoCapability"] = handler

    task = await _run_server(socket_path)
    try:
        reader, writer = await _connect(socket_path)
        await _handshake(reader, writer)
        request_id = b"s" * 16
        await _send(writer, MsgType.REQUEST, {
            "request_id": request_id, "capability": "EchoCapability", "input": {"value": 42},
            "expiry": int(time.time()) + 60, "max_response_bytes": 4096,
        })
        msg_type, body = await _recv(reader)
        assert body["outcome"] == Outcome.SUCCEEDED.value
        assert body["output"] == {"echo": 42}
        writer.close()
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_local_adapter_unavailable_from_a_handler_becomes_outcome_unavailable(socket_path):
    """The exact scenario bede-ipc-spec.md §6/§7 exist for: a capability
    handler calls resolve_local_only(), it raises because no local adapter
    is configured, and the Response must be Unavailable — never a retry
    against a different (cloud) adapter, and never surfaced as a generic
    Error."""
    async def handler(input_body):
        raise LocalAdapterUnavailableError("no local adapter configured")

    capabilities_module.CAPABILITIES["ModelBackedCapability"] = handler

    task = await _run_server(socket_path)
    try:
        reader, writer = await _connect(socket_path)
        await _handshake(reader, writer)
        request_id = b"u" * 16
        await _send(writer, MsgType.REQUEST, {
            "request_id": request_id, "capability": "ModelBackedCapability", "input": {},
            "expiry": int(time.time()) + 60, "max_response_bytes": 4096,
        })
        msg_type, body = await _recv(reader)
        assert body["outcome"] == Outcome.UNAVAILABLE.value
        assert "output" not in body
        writer.close()
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_a_handler_that_raises_an_unexpected_error_becomes_outcome_error(socket_path):
    async def handler(input_body):
        raise RuntimeError("boom")

    capabilities_module.CAPABILITIES["BrokenCapability"] = handler

    task = await _run_server(socket_path)
    try:
        reader, writer = await _connect(socket_path)
        await _handshake(reader, writer)
        request_id = b"b" * 16
        await _send(writer, MsgType.REQUEST, {
            "request_id": request_id, "capability": "BrokenCapability", "input": {},
            "expiry": int(time.time()) + 60, "max_response_bytes": 4096,
        })
        msg_type, body = await _recv(reader)
        assert body["outcome"] == Outcome.ERROR.value
        writer.close()
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_adapter_identity_reports_unavailable_when_local_is_not_configured(monkeypatch, socket_path):
    from core.config import Settings

    monkeypatch.setattr(settings, "local_llm_base_url", "")
    task = await _run_server(socket_path)
    try:
        reader, writer = await _connect(socket_path)
        _msg_type, body = await _handshake(reader, writer)
        assert body["adapter_identity"] == "unavailable"
        writer.close()
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_adapter_identity_names_the_local_model_when_configured(monkeypatch, socket_path):
    monkeypatch.setattr(settings, "local_llm_base_url", "http://gpu-box.lan:8000/v1")
    monkeypatch.setattr(settings, "local_llm_model", "Qwen/Qwen3-Coder-30B-A3B-Instruct")
    task = await _run_server(socket_path)
    try:
        reader, writer = await _connect(socket_path)
        _msg_type, body = await _handshake(reader, writer)
        assert body["adapter_identity"] == "local:Qwen/Qwen3-Coder-30B-A3B-Instruct"
        writer.close()
    finally:
        task.cancel()


@pytest.mark.asyncio
async def test_policy_hash_changes_when_the_capability_registry_changes(socket_path):
    task = await _run_server(socket_path)
    try:
        reader, writer = await _connect(socket_path)
        _msg_type, empty_body = await _handshake(reader, writer)
        writer.close()
    finally:
        task.cancel()

    capabilities_module.CAPABILITIES["Something"] = lambda i: i

    socket_path_2 = socket_path + ".2"
    task2 = await _run_server(socket_path_2)
    try:
        reader2, writer2 = await _connect(socket_path_2)
        _msg_type, changed_body = await _handshake(reader2, writer2)
        writer2.close()
    finally:
        task2.cancel()

    assert empty_body["policy_hash"] != changed_body["policy_hash"]
