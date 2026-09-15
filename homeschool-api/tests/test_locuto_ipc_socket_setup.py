"""The listener must not crash-loop when it cannot use its socket directory.

The socket lives in a bind-mount (docker-compose.yml) so a native Locuto
process on the host can reach it. Docker creates a missing bind-mount source
as ROOT-owned; this container runs as `sage`. `os.chmod` on a directory you
do not own raises EPERM -- "Operation not permitted", which is a different
errno from a permissions denial -- and that killed the process on every
start.

Under `restart: unless-stopped` that is an infinite restart loop, and the
loop is not merely untidy: it reprints its traceback continuously, and
`docker compose logs` is exactly what production-regression's own "Dump logs
on failure" step captures. A looping listener therefore DROWNS the
diagnostics for every other failure in the stack -- observed directly, where
a 205-line tail of that job's log contained nothing but this traceback while
a real failure elsewhere went unreadable.

What bede-ipc-spec.md §2 actually requires is that the directory not be
group- or world-writable -- never that this process was the one to set that.
So a directory that already complies is accepted; one that is genuinely
permissive and cannot be tightened is still refused.
"""

import asyncio
import os
import stat
import tempfile
from pathlib import Path

import pytest

import services.locuto_ipc.server as server_module


def test_a_directory_we_own_is_still_tightened_to_0700():
    """The ordinary path is unchanged."""
    with tempfile.TemporaryDirectory() as tmp:
        sock = Path(tmp) / "nested" / "locuto.sock"
        server_module._prepare_socket_path(str(sock))
        assert stat.S_IMODE(sock.parent.stat().st_mode) == 0o700


def test_a_compliant_directory_we_cannot_chmod_is_accepted(monkeypatch, caplog):
    """Docker's root-owned bind-mount source: mode 0755, chmod raises EPERM.
    0755 is not group- or world-WRITABLE, so §2 is already satisfied."""
    with tempfile.TemporaryDirectory() as tmp:
        parent = Path(tmp) / "bede-locuto"
        parent.mkdir(mode=0o755)
        os.chmod(parent, 0o755)

        def _refuse(*_args, **_kwargs):
            raise PermissionError(1, "Operation not permitted")

        monkeypatch.setattr(server_module.os, "chmod", _refuse)
        server_module._prepare_socket_path(str(parent / "locuto.sock"))

    assert any("satisfies" in r.getMessage() for r in caplog.records), (
        "accepting an already-compliant directory should say so in the log, so a "
        "deployer can tell 'we could not tighten it, and did not need to' apart "
        "from 'we tightened it'"
    )


def test_a_group_writable_directory_we_cannot_chmod_is_still_refused(monkeypatch):
    """The guarantee is not waived just because we cannot enforce it."""
    with tempfile.TemporaryDirectory() as tmp:
        parent = Path(tmp) / "shared"
        parent.mkdir(mode=0o777)
        os.chmod(parent, 0o777)

        def _refuse(*_args, **_kwargs):
            raise PermissionError(1, "Operation not permitted")

        monkeypatch.setattr(server_module.os, "chmod", _refuse)
        with pytest.raises(PermissionError, match="group- or world-writable"):
            server_module._prepare_socket_path(str(parent / "locuto.sock"))


@pytest.mark.parametrize(
    "mode,expected",
    [(0o700, False), (0o755, False), (0o770, True), (0o707, True), (0o777, True)],
)
def test_the_writability_predicate(mode, expected):
    assert server_module._is_group_or_world_writable(mode) is expected


def test_a_non_socket_at_the_path_is_still_refused():
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "locuto.sock"
        target.write_text("not a socket")
        with pytest.raises(RuntimeError, match="not a socket"):
            server_module._prepare_socket_path(str(target))


@pytest.mark.asyncio
async def test_serve_idles_instead_of_exiting_when_it_cannot_bind(monkeypatch, caplog):
    """The crash loop itself. serve() must neither raise nor return."""
    monkeypatch.setattr(server_module.settings, "locuto_ipc_enabled", True, raising=False)

    def _boom(_path):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(server_module, "_prepare_socket_path", _boom)

    with tempfile.TemporaryDirectory() as tmp:
        task = asyncio.ensure_future(server_module.serve(str(Path(tmp) / "locuto.sock")))
        await asyncio.sleep(0.2)
        try:
            assert not task.done(), (
                "serve() returned or raised when the socket could not be bound. "
                "Under `restart: unless-stopped` that is an infinite restart loop "
                "which floods docker compose logs and buries every other failure."
            )
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    assert any("Idling rather than restart-looping" in r.getMessage()
               for r in caplog.records), (
        "the one-time error must say what happened and why the container stays up"
    )


@pytest.mark.asyncio
async def test_a_bind_failure_does_not_take_down_the_rest_of_the_stack(monkeypatch, caplog):
    """Stated as its own guarantee because it is the reason this is non-fatal:
    the connector is optional and its v1 capability registry is empty."""
    monkeypatch.setattr(server_module.settings, "locuto_ipc_enabled", True, raising=False)
    monkeypatch.setattr(
        server_module, "_prepare_socket_path",
        lambda _p: (_ for _ in ()).throw(PermissionError(1, "Operation not permitted")),
    )
    with tempfile.TemporaryDirectory() as tmp:
        task = asyncio.ensure_future(server_module.serve(str(Path(tmp) / "s.sock")))
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "rest of the stack is unaffected" in messages
