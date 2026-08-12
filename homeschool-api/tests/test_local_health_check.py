"""
main.py's _periodic_local_health_check — the proactive half of "AI backend
failure alerting" (see CLAUDE.md). Reactive detection (a real turn failing)
is already covered by tests/test_tutor_stream_resilience.py and
tests/test_sandbox_stream_resilience.py; this file covers the background
loop that catches a dead local model server BEFORE any child ever hits it.

asyncio.sleep is faked to raise CancelledError after a fixed number of
calls — the standard way to run a `while True` loop body a known number of
times in a test without actually waiting _LOCAL_HEALTH_CHECK_INTERVAL_SECONDS
real seconds, and without leaking a still-running background task.
CancelledError is a BaseException (not Exception) in modern Python, so it
correctly propagates through the loop's own `except Exception` guard the
same way a real task.cancel() would.
"""
import asyncio

import pytest

import main
from core.audit import AuditEvent

pytestmark = pytest.mark.asyncio


def _sleep_then_cancel(n_calls: int):
    """Returns a fake asyncio.sleep that lets the loop body run `n_calls`
    times, then raises CancelledError on the next sleep."""
    calls = []

    async def _fake_sleep(seconds):
        calls.append(seconds)
        if len(calls) > n_calls:
            raise asyncio.CancelledError()

    return _fake_sleep, calls


async def test_logs_ai_backend_failure_when_local_becomes_unreachable(monkeypatch):
    fake_sleep, calls = _sleep_then_cancel(1)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)

    async def _fake_check(*a, **kw):
        return False

    monkeypatch.setattr("services.adapters.router.check_local_adapter_reachable", _fake_check)

    logged = []

    async def _fake_log_event(event, **kwargs):
        logged.append((event, kwargs))

    monkeypatch.setattr(main, "log_event", _fake_log_event)

    with pytest.raises(asyncio.CancelledError):
        await main._periodic_local_health_check()

    assert calls == [main._LOCAL_HEALTH_CHECK_INTERVAL_SECONDS] * 2
    assert logged == [
        (AuditEvent.AI_BACKEND_FAILURE, {"success": False, "detail": "cause=health_check adapter=local"}),
    ]


async def test_no_log_when_local_is_reachable(monkeypatch):
    fake_sleep, _ = _sleep_then_cancel(1)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)

    async def _fake_check(*a, **kw):
        return True

    monkeypatch.setattr("services.adapters.router.check_local_adapter_reachable", _fake_check)

    logged = []
    monkeypatch.setattr(main, "log_event", lambda *a, **kw: logged.append((a, kw)))

    with pytest.raises(asyncio.CancelledError):
        await main._periodic_local_health_check()

    assert logged == []


async def test_no_log_when_local_is_not_the_current_primary(monkeypatch):
    """check_local_adapter_reachable() returns None (not False) when local
    isn't configured or isn't currently primary — nothing to alert on."""
    fake_sleep, _ = _sleep_then_cancel(1)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)

    async def _fake_check(*a, **kw):
        return None

    monkeypatch.setattr("services.adapters.router.check_local_adapter_reachable", _fake_check)

    logged = []
    monkeypatch.setattr(main, "log_event", lambda *a, **kw: logged.append((a, kw)))

    with pytest.raises(asyncio.CancelledError):
        await main._periodic_local_health_check()

    assert logged == []


async def test_survives_an_exception_from_the_health_check_and_keeps_looping(monkeypatch):
    """Mirrors _periodic_data_purge's own contract: one failed check must
    never crash the whole background loop, only log a warning and retry
    next interval."""
    fake_sleep, calls = _sleep_then_cancel(3)
    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)

    async def _flaky_check(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr("services.adapters.router.check_local_adapter_reachable", _flaky_check)

    with pytest.raises(asyncio.CancelledError):
        await main._periodic_local_health_check()

    # The loop must have survived 3 exceptions to reach the 4th sleep call
    # that finally raises CancelledError.
    assert len(calls) == 4
