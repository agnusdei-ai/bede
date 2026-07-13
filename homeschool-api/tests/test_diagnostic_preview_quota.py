"""
Real check for core/diagnostic_preview_quota.py — the per-IP cap on the
demo's diagnostic-preview feature (GET /diagnostic/summary, POST
/diagnostic/chat), added so the demo's own uncapped session length/message
count (core/demo_code_session.py) can't be paired with an uncapped
diagnostic preview to use the "demo" as ongoing free production.

Postgres-backed (see core.database.DiagnosticPreviewUse) rather than an
in-memory dict, so every test here runs against the isolated per-test
SQLite engine the `demo_db` fixture (tests/conftest.py) swaps in for
core.database.AsyncSessionLocal.
"""
from datetime import datetime, timedelta, timezone

import pytest

import core.diagnostic_preview_quota as quota

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("demo_db")]


async def _row_count(ip: str) -> int:
    from sqlalchemy import select
    from core.database import AsyncSessionLocal, DiagnosticPreviewUse

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DiagnosticPreviewUse).where(DiagnosticPreviewUse.ip == ip)
        )
        return len(result.scalars().all())


async def test_a_fresh_ip_has_quota():
    assert await quota.has_quota("1.2.3.4", "111111") is True


async def test_using_the_same_code_repeatedly_never_exhausts_quota():
    ip = "1.2.3.4"
    for _ in range(10):
        assert await quota.has_quota(ip, "111111") is True
        await quota.record_use(ip, "111111")


async def test_quota_is_exhausted_after_the_limit_of_distinct_codes():
    ip = "1.2.3.4"
    for i in range(quota.DIAGNOSTIC_PREVIEW_QUOTA):
        code = f"{i:06d}"
        assert await quota.has_quota(ip, code) is True
        await quota.record_use(ip, code)

    assert await quota.has_quota(ip, "999999") is False


async def test_a_previously_used_code_still_has_quota_even_after_exhaustion():
    """Free re-access to a code already counted, even once the IP's
    overall quota for NEW codes is used up — the cap is on how many
    distinct sessions get evaluated, not on repeat visits to one."""
    ip = "1.2.3.4"
    for i in range(quota.DIAGNOSTIC_PREVIEW_QUOTA):
        code = f"{i:06d}"
        await quota.record_use(ip, code)

    assert await quota.has_quota(ip, "000000") is True


async def test_different_ips_have_independent_quota():
    ip_a, ip_b = "1.2.3.4", "5.6.7.8"
    for i in range(quota.DIAGNOSTIC_PREVIEW_QUOTA):
        await quota.record_use(ip_a, f"{i:06d}")

    assert await quota.has_quota(ip_a, "999999") is False
    assert await quota.has_quota(ip_b, "999999") is True


async def test_record_use_is_idempotent_per_ip_and_code():
    ip = "1.2.3.4"
    for _ in range(5):
        await quota.record_use(ip, "111111")
    assert await _row_count(ip) == 1


async def test_entries_older_than_the_window_are_pruned_and_free_up_quota():
    from core.database import AsyncSessionLocal, DiagnosticPreviewUse

    ip = "1.2.3.4"
    stale_at = datetime.now(timezone.utc) - timedelta(seconds=quota._WINDOW_SECONDS + 1)
    async with AsyncSessionLocal() as db:
        for i in range(quota.DIAGNOSTIC_PREVIEW_QUOTA):
            db.add(DiagnosticPreviewUse(ip=ip, code=f"{i:06d}", used_at=stale_at))
        await db.commit()

    assert await quota.has_quota(ip, "999999") is True


async def test_recording_a_new_use_prunes_that_ips_stale_rows():
    """record_use() piggybacks its own lazy cleanup of the calling IP's
    stale rows (see the module docstring) — confirm the old row is
    actually gone afterward, not just ignored by the query filter."""
    from core.database import AsyncSessionLocal, DiagnosticPreviewUse

    ip = "1.2.3.4"
    stale_at = datetime.now(timezone.utc) - timedelta(seconds=quota._WINDOW_SECONDS + 1)
    async with AsyncSessionLocal() as db:
        db.add(DiagnosticPreviewUse(ip=ip, code="111111", used_at=stale_at))
        await db.commit()

    await quota.record_use(ip, "999999")

    assert await _row_count(ip) == 1
