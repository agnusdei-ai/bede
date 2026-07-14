"""
Real check for services/interaction_signals.py — the demo-only,
anonymized structural interaction-pattern recorder. Same db_session
fixture pattern as tests/diagnostic/test_facade_persisted.py (real
in-memory SQLite via aiosqlite, real AES-256-GCM encryption).
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, DemoInteractionSignal
from services.interaction_signals import (
    _session_token,
    purge_old_signals,
    record_signal,
)


# record_signal opens its own AsyncSessionLocal internally rather than taking
# a `db` param (matching core/audit.py's self-contained-session convention),
# so these tests patch core.database.AsyncSessionLocal to a throwaway
# in-memory SQLite engine's session factory instead.
@pytest_asyncio.fixture
async def patched_session_factory(monkeypatch):
    import core.database as database_module

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        from core.encryption import initialize_encryption
        await initialize_encryption(settings.master_secret, session)

    monkeypatch.setattr(database_module, "AsyncSessionLocal", factory)
    yield factory
    await engine.dispose()


def test_session_token_is_deterministic_and_not_the_raw_code():
    token_a = _session_token("123456")
    token_b = _session_token("123456")
    assert token_a == token_b
    assert "123456" not in token_a
    assert len(token_a) == 64  # hex SHA-256


def test_session_token_differs_for_different_codes():
    assert _session_token("111111") != _session_token("222222")


def test_session_token_is_domain_separated_from_ip_hashing():
    """Confirms the fixed 'interaction_signal:' prefix actually changes the
    hash versus hashing the bare code — i.e. this can never collide with
    core/diagnostic_preview_quota.py's _hash_ip tokens even though both key
    on the same settings.secret_key."""
    import hashlib
    import hmac as hmac_module

    bare_hash = hmac_module.new(
        settings.secret_key.encode("utf-8"), b"123456", hashlib.sha256
    ).hexdigest()
    assert _session_token("123456") != bare_hash


@pytest.mark.asyncio
async def test_record_signal_is_a_noop_without_a_demo_code(patched_session_factory):
    await record_signal(None, "turn", "mathematics")
    from sqlalchemy import select
    async with patched_session_factory() as db:
        rows = (await db.execute(select(DemoInteractionSignal))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_record_signal_respects_the_disabled_setting(patched_session_factory, monkeypatch):
    monkeypatch.setattr(settings, "interaction_signal_logging_enabled", False)
    await record_signal("123456", "turn", "mathematics")
    from sqlalchemy import select
    async with patched_session_factory() as db:
        rows = (await db.execute(select(DemoInteractionSignal))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_turn_and_tool_counts_accumulate_across_calls(patched_session_factory):
    from core.encryption import decrypt_json

    await record_signal("123456", "turn", "mathematics")
    await record_signal("123456", "offer_socratic_hint", "mathematics")
    await record_signal("123456", "offer_socratic_hint", "mathematics")
    await record_signal("123456", "turn", "mathematics")

    from sqlalchemy import select
    async with patched_session_factory() as db:
        row = (await db.execute(select(DemoInteractionSignal))).scalar_one()
    signals = decrypt_json(row.signals_enc)

    assert signals["turn_count"] == 2
    assert signals["tool_counts"]["offer_socratic_hint"] == 2
    assert signals["subjects_visited"] == ["mathematics"]


@pytest.mark.asyncio
async def test_subject_complete_is_tracked_once_per_subject(patched_session_factory):
    from core.encryption import decrypt_json

    await record_signal("123456", "subject_complete", "mathematics")
    await record_signal("123456", "subject_complete", "mathematics")  # duplicate
    await record_signal("123456", "subject_complete", "language_arts")

    from sqlalchemy import select
    async with patched_session_factory() as db:
        row = (await db.execute(select(DemoInteractionSignal))).scalar_one()
    signals = decrypt_json(row.signals_enc)

    assert sorted(signals["subjects_completed"]) == ["language_arts", "mathematics"]


@pytest.mark.asyncio
async def test_different_codes_are_fully_independent_sessions(patched_session_factory):
    from core.encryption import decrypt_json

    await record_signal("111111", "turn", "mathematics")
    await record_signal("111111", "turn", "mathematics")
    await record_signal("222222", "turn", "mathematics")

    from sqlalchemy import select
    async with patched_session_factory() as db:
        rows = (await db.execute(select(DemoInteractionSignal))).scalars().all()

    assert len(rows) == 2
    counts = sorted(decrypt_json(r.signals_enc)["turn_count"] for r in rows)
    assert counts == [1, 2]


@pytest.mark.asyncio
async def test_no_raw_content_ever_lands_in_the_stored_signal(patched_session_factory):
    """The whole point of this module: only structural signals, never
    conversation content. Confirms nothing resembling free text sneaks in
    via the event_type or subject_area params."""
    from core.encryption import decrypt_json

    await record_signal("123456", "offer_socratic_hint", "mathematics")

    from sqlalchemy import select
    async with patched_session_factory() as db:
        row = (await db.execute(select(DemoInteractionSignal))).scalar_one()
    signals = decrypt_json(row.signals_enc)

    assert set(signals.keys()) == {
        "tool_counts", "subjects_visited", "subjects_completed",
        "turn_count", "silence_continues_fired", "first_event_at", "last_event_at",
    }


@pytest.mark.asyncio
async def test_corrupted_row_degrades_to_a_fresh_start_instead_of_raising(patched_session_factory):
    async with patched_session_factory() as db:
        db.add(DemoInteractionSignal(
            session_token=_session_token("123456"),
            signals_enc=b"not a valid SAGE envelope",
        ))
        await db.commit()

    # Must not raise despite the corrupted existing row.
    await record_signal("123456", "turn", "mathematics")

    from core.encryption import decrypt_json
    from sqlalchemy import select
    async with patched_session_factory() as db:
        row = (await db.execute(select(DemoInteractionSignal))).scalar_one()
    signals = decrypt_json(row.signals_enc)
    assert signals["turn_count"] == 1


@pytest.mark.asyncio
async def test_purge_old_signals_removes_rows_past_retention(patched_session_factory):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    async with patched_session_factory() as db:
        db.add(DemoInteractionSignal(
            session_token="old-token",
            signals_enc=b"placeholder",
            created_at=datetime.now(timezone.utc) - timedelta(days=31),
        ))
        db.add(DemoInteractionSignal(
            session_token="new-token",
            signals_enc=b"placeholder",
            created_at=datetime.now(timezone.utc),
        ))
        await db.commit()

    purged = await purge_old_signals()
    assert purged == 1

    async with patched_session_factory() as db:
        remaining = (await db.execute(select(DemoInteractionSignal))).scalars().all()
    assert [r.session_token for r in remaining] == ["new-token"]
