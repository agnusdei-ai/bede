"""
Tests for core/audit.py's log_event_nowait() — the fire-and-forget variant
used on hot paths (login, voice verify) so the audit write's own DB
round-trip doesn't add to the user-facing response latency.
"""
import asyncio

import pytest
from sqlalchemy import select

from core.audit import AuditEvent, log_event_nowait
from core.database import AuditLog


@pytest.mark.asyncio
async def test_call_itself_returns_none_synchronously_not_a_coroutine(demo_db):
    """The whole point: callers use this with no `await`. If it returned a
    coroutine instead of scheduling a task and returning None, calling it
    unawaited would silently never run the write at all (and Python would
    warn "coroutine was never awaited")."""
    result = log_event_nowait(AuditEvent.AUTH_SUCCESS, role="parent", success=True, ip="127.0.0.1")
    assert result is None


@pytest.mark.asyncio
async def test_write_actually_lands_once_the_task_runs(demo_db):
    log_event_nowait(AuditEvent.AUTH_SUCCESS, role="child", success=True, ip="10.0.0.5", detail="test")

    # log_event_nowait only SCHEDULES the write via asyncio.create_task —
    # the caller's own coroutine keeps running immediately. Yielding once
    # here gives that scheduled task a chance to actually run.
    await asyncio.sleep(0.05)

    async with demo_db() as db:
        result = await db.execute(select(AuditLog))
        rows = result.scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_task_is_kept_alive_by_the_module_level_set(demo_db):
    """Regression guard for the exact asyncio gotcha this exists to avoid:
    a fire-and-forget task with no other strong reference can be
    garbage-collected mid-write. _background_tasks must hold one until
    the task finishes, then release it."""
    from core.audit import _background_tasks

    before = len(_background_tasks)
    log_event_nowait(AuditEvent.AUTH_SUCCESS, role="parent", success=True, ip="127.0.0.1")
    assert len(_background_tasks) == before + 1

    await asyncio.sleep(0.05)
    assert len(_background_tasks) == before  # discarded via the done callback
