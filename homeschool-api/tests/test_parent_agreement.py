"""
Tests for the parent-agreement gate — the platform-scope disclaimer/waiver
in core/parent_agreement.py that blocks ParentSetup and the rest of the
parent-only UI until accepted (see routers/parent_agreement.py). Router
functions are called directly (same pattern as test_diagnostic_router.py)
rather than through a full TestClient, since require_auth's JWT/fingerprint
plumbing isn't what's under test here. The ORM round trip uses a real
in-memory SQLite engine via aiosqlite (same pattern as
tests/diagnostic/test_facade_persisted.py) — genuine, not mocked.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from core.database import Base, ParentAgreement
from core.parent_agreement import CURRENT_VERSION, SECTIONS
from routers.parent_agreement import accept, get_status


def _fake_request() -> Request:
    scope = {
        "type": "http",
        "client": ("127.0.0.1", 12345),
        "headers": [(b"user-agent", b"pytest")],
    }
    return Request(scope)


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
        yield session

    await engine.dispose()


# ── Content module ────────────────────────────────────────────────────────

def test_current_version_is_a_non_empty_string():
    assert isinstance(CURRENT_VERSION, str) and CURRENT_VERSION.strip()


def test_sections_cover_scope_no_diagnosis_responsibility_and_acknowledgment():
    headings = {s.heading for s in SECTIONS}
    assert headings == {
        "Platform Scope", "No Diagnosis, No Screening", "Your Responsibility", "Acknowledgment",
    }
    assert all(s.body.strip() for s in SECTIONS)


def test_no_diagnosis_section_names_adhd_and_autism_explicitly():
    """The whole point of this gate is that Bede does not diagnose or screen
    for these conditions — the disclaimer has to say so plainly, not just
    gesture at "conditions" in the abstract."""
    section = next(s for s in SECTIONS if s.heading == "No Diagnosis, No Screening")
    assert "ADHD" in section.body
    assert "autism" in section.body.lower()
    assert "diagnosis" in section.body.lower()


# ── Router: GET /parent-agreement/status ─────────────────────────────────

@pytest.mark.asyncio
async def test_status_not_accepted_when_no_row_exists(db_session):
    status = await get_status(auth={"role": "parent"}, db=db_session)
    assert status.accepted is False
    assert status.accepted_at is None
    assert status.version == CURRENT_VERSION
    assert len(status.sections) == len(SECTIONS)


@pytest.mark.asyncio
async def test_status_accepted_after_row_matches_current_version(db_session):
    db_session.add(ParentAgreement(key="agreement", accepted_version=CURRENT_VERSION))
    await db_session.commit()

    status = await get_status(auth={"role": "parent"}, db=db_session)
    assert status.accepted is True
    assert status.accepted_at is not None


@pytest.mark.asyncio
async def test_status_not_accepted_when_row_is_a_stale_version(db_session):
    """A parent who accepted an older wording must not be treated as having
    accepted the current one — this is what forces re-consent after the
    text changes materially."""
    db_session.add(ParentAgreement(key="agreement", accepted_version="2020-01-01-old"))
    await db_session.commit()

    status = await get_status(auth={"role": "parent"}, db=db_session)
    assert status.accepted is False
    assert status.accepted_at is None


# ── Router: POST /parent-agreement/accept ────────────────────────────────

@pytest.mark.asyncio
async def test_accept_creates_a_row_when_none_exists(db_session):
    result = await accept(_fake_request(), auth={"role": "parent"}, db=db_session)
    assert result.accepted is True
    assert result.version == CURRENT_VERSION

    status = await get_status(auth={"role": "parent"}, db=db_session)
    assert status.accepted is True


@pytest.mark.asyncio
async def test_accept_upgrades_an_existing_stale_row(db_session):
    db_session.add(ParentAgreement(key="agreement", accepted_version="2020-01-01-old"))
    await db_session.commit()

    await accept(_fake_request(), auth={"role": "parent"}, db=db_session)

    status = await get_status(auth={"role": "parent"}, db=db_session)
    assert status.accepted is True
