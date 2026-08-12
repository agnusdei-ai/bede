"""
The Unix-domain-socket listener — bede-ipc-spec.md §1, §2, §7 tied
together. Run as `python -m services.locuto_ipc` (see __main__.py), a
separate process from the main FastAPI `api` app — see this package's
__init__.py docstring for why.

Per-connection flow (§1: one connection per capability invocation, strictly
request/response, never multiplexed):

    accept()
      -> peer credential check (peer_auth.check_peer) -> close if not allowed
      -> read Hello -> send HelloAck
      -> read ONE of: Request (-> dispatch, send Response, then expect Bye/close),
                      Ping (-> Pong, keep waiting), Bye (-> close)
      -> a second Request on an already-served connection is refused and the
         connection is closed — one connection serves exactly one invocation

Kill-switch (§7): `settings.locuto_ipc_enabled` is checked once, at
`serve()` startup — this process simply never binds the socket at all when
it's False, matching this codebase's "empty/off = disabled" convention
elsewhere (DEMO_PIN, sandbox_pin, mcp_external_enabled). This is a
restart-based switch, not a live no-restart one: turning it off means
stopping this process (or restarting it with the flag flipped), same as
every other env-based setting here. A live, no-restart toggle would need
the same DB-backed override pattern core/provider_state.py uses for
AI-provider switching — real, larger scope, and not required for v1's
"stops accepting new connections" requirement, which a process that never
binds the listener satisfies unconditionally.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import stat
import time
from pathlib import Path

from . import capabilities, protocol
from .framing import FrameError, MAX_BODY_LEN, decode_body, decode_header, encode_frame, HEADER_LEN
from .peer_auth import PeerAuthError, check_peer, default_allowed_uids
from .protocol import MsgType, Outcome, RequestBody, ResponseBody
from core.config import settings
from services.adapters.router import LocalAdapterUnavailableError, resolve_local_only

log = logging.getLogger(__name__)

SERVER_IDENTITY = "bede-locuto-ipc"


def _policy_hash() -> str:
    """A partial answer to LOCUTO_CONNECTOR_DECISIONS.md packet 2, not a
    resolution of it — see protocol.HelloAckBody's own docstring. Hashes
    the current (v1: empty) capability registry's names, sorted, so the
    hash changes the moment a real capability is registered and Locuto has
    something concrete to compare across sessions."""
    names = sorted(capabilities.CAPABILITIES.keys())
    digest = hashlib.sha256(",".join(names).encode("utf-8")).hexdigest()
    return digest


def _adapter_identity() -> str:
    """What HelloAck reports about the model backing capability calls —
    the local adapter's model name if configured, or 'unavailable' if
    resolve_local_only() would raise right now. Never a base_url, API key,
    or anything else that could leak deployment topology unnecessarily."""
    try:
        resolve_local_only(settings)
    except LocalAdapterUnavailableError:
        return "unavailable"
    return f"local:{settings.local_llm_model}"


async def _read_frame(reader: asyncio.StreamReader) -> tuple[int, int, dict]:
    """Reads exactly one frame. Raises FrameError (malformed) or
    asyncio.IncompleteReadError (peer closed mid-frame) — server.py's
    caller treats both as "close the connection", never as data to
    interpret partially."""
    header_raw = await reader.readexactly(HEADER_LEN)
    version, msg_type, length = decode_header(header_raw)  # raises FrameError if length > MAX_BODY_LEN
    body_raw = await reader.readexactly(length)
    body = decode_body(body_raw)
    return version, msg_type, body


async def _write_frame(writer: asyncio.StreamWriter, msg_type: int, body: dict) -> None:
    writer.write(encode_frame(msg_type, body))
    await writer.drain()


async def _dispatch_request(body: dict) -> ResponseBody:
    """The §6 enforcement point. A capability handler, if one is ever
    registered, is called here and ONLY here — this is the single place a
    Request's capability name is looked up and invoked, so it is also the
    single place that can be audited/tested for "never calls
    get_default_client()/resolve_with_failover()". v1's empty registry
    means every real capability name currently returns Refused; the
    LocalAdapterUnavailableError translation below exists for the first
    capability that DOES get registered, proven correct now rather than
    written for the first time under deadline pressure later."""
    try:
        req = RequestBody.from_body(body)
    except ValueError as exc:
        log.warning("Malformed Request body: %s", exc)
        # No request_id could be parsed reliably — respond with whatever
        # raw value was present, or an empty placeholder, since Error
        # still needs *a* request_id to echo per the wire shape.
        raw_id = body.get("request_id") if isinstance(body.get("request_id"), bytes) else b"\x00" * 16
        return protocol.error(raw_id)

    if req.is_expired():
        log.info("Refused expired Request capability=%r request_id=%s", req.capability, req.request_id.hex())
        return protocol.refused(req.request_id)

    handler = capabilities.get_handler(req.capability)
    if handler is None:
        log.info("Refused unregistered capability=%r request_id=%s", req.capability, req.request_id.hex())
        return protocol.refused(req.request_id)

    try:
        output = await handler(req.input)
    except LocalAdapterUnavailableError:
        # bede-ipc-spec.md §6/§7: never caught-and-retried against a
        # different adapter. Unavailable is the only permitted outcome.
        log.warning("resolve_local_only() unavailable for capability=%r", req.capability)
        return protocol.unavailable(req.request_id)
    except Exception:
        log.exception("Capability handler failed: capability=%r", req.capability)
        return protocol.error(req.request_id)

    return ResponseBody(request_id=req.request_id, outcome=Outcome.SUCCEEDED, output=output)


async def _handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer_desc = "unknown"
    try:
        sock = writer.get_extra_info("socket")
        if sock is None:
            log.warning("No underlying socket available for peer credential check — closing")
            return
        try:
            uid = check_peer(sock, default_allowed_uids())
            peer_desc = f"uid={uid}"
        except PeerAuthError as exc:
            log.warning("Peer credential check failed, closing connection: %s", exc)
            return

        try:
            _version, msg_type, body = await _read_frame(reader)
        except (FrameError, asyncio.IncompleteReadError) as exc:
            log.warning("Malformed or incomplete Hello from %s: %s", peer_desc, exc)
            return
        if msg_type != MsgType.HELLO:
            log.warning("Expected Hello from %s, got msg_type=%r — closing", peer_desc, msg_type)
            return

        await _write_frame(
            writer,
            MsgType.HELLO_ACK,
            {
                "protocol_version": 1,
                "server_identity": SERVER_IDENTITY,
                "policy_hash": _policy_hash(),
                "adapter_identity": _adapter_identity(),
            },
        )

        served_request = False
        while True:
            try:
                _version, msg_type, body = await _read_frame(reader)
            except asyncio.IncompleteReadError:
                return  # peer closed — ordinary end of connection
            except FrameError as exc:
                log.warning("Malformed frame from %s: %s — closing", peer_desc, exc)
                return

            if msg_type == MsgType.PING:
                await _write_frame(writer, MsgType.PONG, {})
                continue
            if msg_type == MsgType.BYE:
                return
            if msg_type == MsgType.REQUEST:
                if served_request:
                    # §1: one connection serves exactly one invocation.
                    log.warning("Second Request on an already-served connection from %s — closing", peer_desc)
                    return
                served_request = True
                response = await _dispatch_request(body)
                await _write_frame(writer, MsgType.RESPONSE, response.to_body())
                continue
            log.warning("Unrecognized/reserved msg_type=%r from %s — closing", msg_type, peer_desc)
            return
    except (ConnectionError, asyncio.IncompleteReadError):
        # The peer disappeared mid-write (broken pipe, reset) — an ordinary
        # disconnect, not a bug. Logged at debug so it doesn't read as an
        # error every time a client drops off, while still being visible
        # if someone's actually watching for it.
        log.debug("Connection from %s ended abruptly", peer_desc)
    except Exception:
        log.exception("Unexpected error handling connection from %s", peer_desc)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


def _prepare_socket_path(path: str) -> None:
    """bede-ipc-spec.md §2: parent directory not group- or world-writable,
    socket file mode 0600. Creates the parent directory (0700) if it
    doesn't exist; removes a stale socket file left over from a previous
    run (a Unix socket bind() fails on an existing path unconditionally)."""
    p = Path(path)
    parent = p.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(parent, 0o700)  # mkdir's mode is masked by umask; be explicit
    if p.exists():
        if stat.S_ISSOCK(p.stat().st_mode):
            p.unlink()
        else:
            raise RuntimeError(f"{path} exists and is not a socket — refusing to remove it")


async def serve(socket_path: str | None = None) -> None:
    """Binds and serves forever. Refuses to start at all if
    settings.locuto_ipc_enabled is False at startup — matching this
    codebase's "empty/off = disabled" convention (DEMO_PIN, sandbox_pin,
    mcp_external_enabled)."""
    if not settings.locuto_ipc_enabled:
        log.info("locuto_ipc_enabled is False — not starting the listener")
        return

    path = socket_path or settings.locuto_ipc_socket_path
    _prepare_socket_path(path)

    server = await asyncio.start_unix_server(_handle_connection, path=path)
    os.chmod(path, 0o600)
    log.info("Locuto IPC listener bound at %s", path)

    try:
        async with server:
            await server.serve_forever()
    finally:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass
