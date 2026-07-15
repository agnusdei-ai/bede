"""
Tests for core/audit.py's log_event()/read_audit_log() round trip. Before
this file, AuditEvent/log_event only appeared in conftest.py as a stub —
no test confirmed an event written by log_event() is actually persisted,
correctly encrypted, and readable back through read_audit_log(). Given
every security-relevant action in this app (auth, voice enrollment,
consent, rate limiting) is only as trustworthy as this write path, that
was a real gap.

Uses a genuine (throwaway, in-memory) SQLite database via aiosqlite and
real AES-256-GCM encryption via core.encryption.initialize_encryption() —
same pattern as tests/diagnostic/test_facade_persisted.py — not mocked.
core.database.AsyncSessionLocal is monkeypatched to this test engine's
session factory so log_event()'s internal `async with AsyncSessionLocal()`
(it imports the name fresh from core.database on every call, so patching
the module attribute is enough — no need to touch core.audit itself)
writes to the in-memory DB instead of the unreachable Postgres the rest of
the suite's env vars point at.
"""
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.audit import AuditEvent, log_event, read_audit_log
from core.config import settings
from core.database import Base


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        from core.encryption import initialize_encryption
        await initialize_encryption(settings.master_secret, session)

        with patch("core.database.AsyncSessionLocal", session_factory):
            yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_logged_event_round_trips_through_read_audit_log(db_session):
    await log_event(
        AuditEvent.AUTH_SUCCESS,
        ip="10.0.0.5",
        user_agent="pytest-agent",
        role="parent",
        student_name="Emma",
        detail="password login",
    )

    entries = await read_audit_log(db_session)

    assert len(entries) == 1
    entry = entries[0]
    assert entry["event"] == AuditEvent.AUTH_SUCCESS
    assert entry["ip"] == "10.0.0.5"
    assert entry["ua"] == "pytest-agent"
    assert entry["role"] == "parent"
    assert entry["student"] == "Emma"
    assert entry["detail"] == "password login"
    assert entry["success"] is True


@pytest.mark.asyncio
async def test_the_stored_row_is_actually_encrypted_bytea_not_plaintext(db_session):
    from sqlalchemy import select
    from core.database import AuditLog

    await log_event(AuditEvent.VOICE_ENROLL, student_name="Emma", detail="enrolled")

    row = (await db_session.execute(select(AuditLog))).scalars().one()
    assert isinstance(row.event_enc, bytes)
    assert b"Emma" not in row.event_enc
    assert b"voice.enroll" not in row.event_enc


@pytest.mark.asyncio
async def test_failure_events_and_field_are_preserved(db_session):
    await log_event(AuditEvent.AUTH_FAILURE, success=False, detail="bad password")

    entries = await read_audit_log(db_session)
    assert entries[0]["success"] is False
    assert entries[0]["detail"] == "bad password"


@pytest.mark.asyncio
async def test_user_agent_is_truncated_to_200_chars(db_session):
    await log_event(AuditEvent.AUTH_SUCCESS, user_agent="x" * 500)

    entries = await read_audit_log(db_session)
    assert len(entries[0]["ua"]) == 200


@pytest.mark.asyncio
async def test_detail_is_truncated_to_500_chars(db_session):
    await log_event(AuditEvent.SUSPICIOUS_REQUEST, detail="y" * 900)

    entries = await read_audit_log(db_session)
    assert len(entries[0]["detail"]) == 500


@pytest.mark.asyncio
async def test_multiple_events_are_returned_most_recent_first(db_session):
    await log_event(AuditEvent.AUTH_SUCCESS, detail="first")
    await log_event(AuditEvent.AUTH_SUCCESS, detail="second")
    await log_event(AuditEvent.AUTH_SUCCESS, detail="third")

    entries = await read_audit_log(db_session, limit=10)
    assert [e["detail"] for e in entries] == ["third", "second", "first"]


@pytest.mark.asyncio
async def test_a_corrupted_row_reads_back_as_corrupt_instead_of_raising(db_session):
    from core.database import AuditLog

    db_session.add(AuditLog(event_enc=b"not a real encrypted blob"))
    await db_session.commit()

    entries = await read_audit_log(db_session)
    assert entries == [{"_corrupt": True}]


@pytest.mark.asyncio
async def test_log_event_never_raises_when_the_write_itself_fails():
    """'Audit failure must never crash the request' (core/audit.py's own
    module docstring) — simulate encrypt() blowing up and confirm log_event
    swallows it rather than propagating into the caller's request handler."""
    with patch("core.encryption.encrypt", side_effect=RuntimeError("encryption not initialised")):
        await log_event(AuditEvent.AUTH_SUCCESS, detail="should not raise")
    # no assertion beyond "didn't raise" — that's the entire contract here
