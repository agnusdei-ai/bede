"""
Real check for services.diagnostic.get_session_growth — the read-back half
of the diagnostic engine's write-only DiagnosticEvidenceLog, added so
generate_session_summary (services/ai_service.py) can report a real
before/after "Math Skill Growth" for the session instead of only ever
showing a current-state snapshot (see docs/diagnostic/DIAGNOSTIC_ENGINE_DESIGN.md
§5.3's update note, and CLAUDE.md's Architecture section).

Same real (throwaway, in-memory) SQLite + real AES-256-GCM fixture as
tests/diagnostic/test_facade_persisted.py, which this file's db_session
fixture is copied from — process_evidence() is used to seed genuine
DiagnosticEvidenceLog rows (real prior->posterior deltas from a real
bayesian_update), not hand-built fixture data, so this exercises the
actual encrypt/decrypt round trip get_session_growth depends on.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base
from services.diagnostic import get_session_growth, process_evidence


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
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_no_evidence_yet_returns_empty_list(db_session):
    growth = await get_session_growth(
        db_session, "Emma", "mathematics", datetime.now(timezone.utc) - timedelta(hours=1),
    )
    assert growth == []


@pytest.mark.asyncio
async def test_evidence_in_window_reports_before_and_after(db_session):
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    await process_evidence(db_session, "Emma", "probe.cc.rote_count_20", "correct", 1.0, "K-2")

    growth = await get_session_growth(db_session, "Emma", "mathematics", since)

    assert growth != []
    entry = growth[0]
    assert entry["after"] > entry["before"]  # a correct answer should move the posterior up
    assert "skill_id" in entry and "label" in entry and "domain" in entry
    assert entry["before_level"] in ("secure", "developing", "gap")
    assert entry["after_level"] in ("secure", "developing", "gap")


@pytest.mark.asyncio
async def test_evidence_before_the_window_is_excluded(db_session):
    await process_evidence(db_session, "Emma", "probe.cc.rote_count_20", "correct", 1.0, "K-2")

    since = datetime.now(timezone.utc) + timedelta(seconds=5)  # strictly after the evidence just written
    growth = await get_session_growth(db_session, "Emma", "mathematics", since)

    assert growth == []


@pytest.mark.asyncio
async def test_repeated_probing_reports_earliest_prior_and_latest_posterior(db_session):
    """A skill probed twice in the same window must report one honest
    start-to-end movement (first prior seen -> last posterior seen), not
    just the most recent single delta — see the function's own docstring."""
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    await process_evidence(db_session, "Emma", "probe.cc.rote_count_20", "correct", 1.0, "K-2")
    await process_evidence(db_session, "Emma", "probe.cc.rote_count_20", "correct", 1.0, "K-2")

    growth = await get_session_growth(db_session, "Emma", "mathematics", since)

    matching = [g for g in growth if g["skill_id"] == growth[0]["skill_id"]]
    assert len(matching) == 1  # one row per skill, not one per evidence event

    # The two-call posterior must be at least as far from 0.5 (cold-start
    # prior) as a single call's would be — proving both updates were folded
    # in, not just the second one alone.
    single_call_growth_before = 0.5
    assert matching[0]["after"] >= single_call_growth_before


@pytest.mark.asyncio
async def test_wrong_subject_area_is_excluded(db_session):
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    await process_evidence(db_session, "Emma", "probe.cc.rote_count_20", "correct", 1.0, "K-2")

    growth = await get_session_growth(db_session, "Emma", "reading", since)
    assert growth == []


@pytest.mark.asyncio
async def test_disabled_evidence_log_means_nothing_to_read_back(db_session, monkeypatch):
    """diagnostic_evidence_log_enabled off (a deployment that opted back
    out) means process_evidence never writes a DiagnosticEvidenceLog row —
    get_session_growth must degrade to an empty list, not raise."""
    monkeypatch.setattr(settings, "diagnostic_evidence_log_enabled", False)
    since = datetime.now(timezone.utc) - timedelta(hours=1)

    await process_evidence(db_session, "Emma", "probe.cc.rote_count_20", "correct", 1.0, "K-2")
    growth = await get_session_growth(db_session, "Emma", "mathematics", since)

    assert growth == []
