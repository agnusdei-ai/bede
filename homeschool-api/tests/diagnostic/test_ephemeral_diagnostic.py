"""
The no-retention diagnostic path (settings.retain_mastery_profiles=False).

Every test here asserts a REFUSAL, because the failure mode is silent
persistence rather than a visible error. A bug that writes the estimate
anyway produces no exception, no log line, and no wrong answer on screen:
the only symptom is a file on a family's disk that they were told did not
exist. So the tests check empty tables against a real database rather than
trusting a mock.

Numbering follows Appendix B of docs/diagnostic/EPHEMERAL_DIAGNOSTIC_SPEC.md.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, DiagnosticEvidenceLog, MasteryProfile, SkillActivityLog
from models.schemas import GradeStage, SessionConfig, Subject
from services import diagnostic_session
from services.ai_service import _record_skill_evidence


@pytest_asyncio.fixture
async def db_session():
    """Same in-memory engine the sibling ledger tests use. A REAL database,
    deliberately: the whole point is to prove nothing lands in it."""
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
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _clean_estimates():
    diagnostic_session._reset_for_tests()
    yield
    diagnostic_session._reset_for_tests()


@pytest.fixture
def no_retention(monkeypatch):
    monkeypatch.setattr(settings, "retain_mastery_profiles", False)
    return settings


def _config(name="Ada") -> SessionConfig:
    return SessionConfig(
        student_name=name, grade="4", grade_stage=GradeStage.core_mastery,
        subjects=[Subject.mathematics],
    )


def _evidence(probe="probe.oa.multiplication_facts", outcome="correct"):
    return {"probe_id": probe, "outcome": outcome, "confidence": 1.0}


async def _run_session(db, session_id, n=6, name="Ada", outcome="correct"):
    for i in range(n):
        await _record_skill_evidence(
            db, None, _config(name), Subject.mathematics,
            _evidence(outcome=outcome), session_id,
        )


# ── 1 & 2: nothing describing the child reaches the database ──────────────

@pytest.mark.asyncio
async def test_a_full_session_leaves_mastery_profiles_empty(db_session, no_retention):
    """The central claim. A real database is present and configured; the
    point is that the estimate never reaches it anyway."""
    await _run_session(db_session, "sess-a", n=8)
    await db_session.commit()

    rows = (await db_session.execute(select(MasteryProfile))).scalars().all()
    assert rows == [], "an estimate was persisted despite retention being off"


@pytest.mark.asyncio
async def test_a_full_session_leaves_the_evidence_log_empty(db_session, no_retention):
    await _run_session(db_session, "sess-b", n=8)
    await db_session.commit()

    rows = (await db_session.execute(select(DiagnosticEvidenceLog))).scalars().all()
    assert rows == [], "evidence deltas were persisted despite retention being off"


# ── 3: the work ledger is deliberately unaffected ─────────────────────────

@pytest.mark.asyncio
async def test_the_work_ledger_still_records_events(db_session, no_retention):
    """The ledger holds events ("this task was completed"), not claims about
    the child, so it is explicitly OUT of scope for this setting. If this
    test ever fails, the privacy change has taken the family's record of
    what their child actually did along with it."""
    await _run_session(db_session, "sess-c", n=4)
    await db_session.commit()

    rows = (await db_session.execute(select(SkillActivityLog))).scalars().all()
    assert len(rows) == 4


# ── 4: sessions cannot see each other ─────────────────────────────────────

@pytest.mark.asyncio
async def test_two_sessions_for_the_same_child_do_not_share_an_estimate(db_session, no_retention):
    """The reason the key is the session and not the student. If these
    leaked into each other, the module would be accumulating a profile
    across sittings, which is the thing being removed."""
    await _run_session(db_session, "sess-morning", n=5, name="Ada")
    await _run_session(db_session, "sess-afternoon", n=1, name="Ada")

    morning = await diagnostic_session.summary("sess-morning", "Ada")
    afternoon = await diagnostic_session.summary("sess-afternoon", "Ada")

    assert morning["evidence_count"] == 5
    assert afternoon["evidence_count"] == 1, "a later session inherited an earlier one's evidence"


@pytest.mark.asyncio
async def test_an_unknown_session_has_no_estimate(no_retention):
    assert await diagnostic_session.summary("never-seen", "Ada") is None


# ── 5: accumulation within a session actually works ───────────────────────

@pytest.mark.asyncio
async def test_evidence_accumulates_across_a_whole_session(db_session, no_retention):
    """The efficacy claim, and the reason this is session-scoped rather
    than turn-scoped: a two-hour sitting has to build ONE estimate, or the
    diagnostic is worthless as well as private."""
    await _run_session(db_session, "sess-long", n=1)
    first = await diagnostic_session.summary("sess-long", "Ada")

    await _run_session(db_session, "sess-long", n=9)
    later = await diagnostic_session.summary("sess-long", "Ada")

    assert first["evidence_count"] == 1
    assert later["evidence_count"] == 10, "evidence later in the session did not reach the estimate"


@pytest.mark.asyncio
async def test_the_estimate_actually_moves_on_evidence(db_session, no_retention):
    """Guards against a hollow pass: an accumulator that counted evidence
    but never updated the vector would satisfy every other test here."""
    await _run_session(db_session, "sess-move", n=6, outcome="correct")
    correct = await diagnostic_session.summary("sess-move", "Ada")

    diagnostic_session._reset_for_tests()
    await _run_session(db_session, "sess-move", n=6, outcome="incorrect")
    incorrect = await diagnostic_session.summary("sess-move", "Ada")

    assert correct["domains"] != incorrect["domains"], (
        "the estimate is identical whether the child answered correctly or not"
    )


# ── 6: an estimate does not outlive its session ───────────────────────────

@pytest.mark.asyncio
async def test_discarding_a_session_frees_its_estimate(db_session, no_retention):
    await _run_session(db_session, "sess-end", n=3)
    assert diagnostic_session.active_session_count() == 1

    assert diagnostic_session.discard("sess-end") == 1
    assert diagnostic_session.active_session_count() == 0
    assert await diagnostic_session.summary("sess-end", "Ada") is None


@pytest.mark.asyncio
async def test_abandoned_sessions_are_swept(db_session, no_retention, monkeypatch):
    await _run_session(db_session, "sess-abandoned", n=2)
    assert diagnostic_session.active_session_count() == 1

    monkeypatch.setattr(diagnostic_session, "_TTL_SECONDS", -1)
    assert diagnostic_session.active_session_count() == 0


# ── 7: with the setting on, behaviour is exactly as before ────────────────

@pytest.mark.asyncio
async def test_the_persistent_path_is_untouched_when_retention_is_on(db_session):
    """The default must be byte-for-byte today's behaviour: a deployment
    that never sets this flag should not be able to tell it exists."""
    assert settings.retain_mastery_profiles is True

    await _run_session(db_session, "sess-normal", n=3)
    await db_session.commit()

    rows = (await db_session.execute(select(MasteryProfile))).scalars().all()
    assert len(rows) == 1, "the persistent path stopped writing the profile"
    assert diagnostic_session.active_session_count() == 0, (
        "the session accumulator ran even though retention is on"
    )


@pytest.mark.asyncio
async def test_no_session_id_records_nothing_rather_than_falling_back(db_session, no_retention):
    """An older client sends no session_id. That must mean "nothing to
    accumulate into", never "fall back to the database" — the fallback
    would silently reinstate exactly what the setting turns off."""
    await _record_skill_evidence(
        db_session, None, _config(), Subject.mathematics, _evidence(), None,
    )
    await db_session.commit()

    rows = (await db_session.execute(select(MasteryProfile))).scalars().all()
    assert rows == []
    assert diagnostic_session.active_session_count() == 0


# ── The read paths: an estimate nobody can read is not a feature ──────────

@pytest.mark.asyncio
async def test_the_live_estimate_reaches_the_prompt_within_the_session(db_session, no_retention):
    """The first version of this feature wired the WRITE path only, so
    evidence accumulated in memory and nothing ever read it back. Bede's
    questioning would not have adapted at all within the sitting, which is
    the entire reason for accumulating across a session rather than a turn.
    """
    empty_vector, empty_count = diagnostic_session.live_vector("sess-read")
    assert empty_vector is None and empty_count == 0

    await _run_session(db_session, "sess-read", n=4)

    vector, count = diagnostic_session.live_vector("sess-read")
    assert count == 4
    assert vector, "the accumulated estimate was not readable for prompt injection"


@pytest.mark.asyncio
async def test_live_vector_matches_the_shape_the_prompt_path_expects(db_session, no_retention):
    """live_vector stands in for _load_mastery_vector_readonly at the same
    call site, so it has to return the same (vector-or-None, count) shape."""
    await _run_session(db_session, "sess-shape", n=2)
    vector, count = diagnostic_session.live_vector("sess-shape")

    assert isinstance(vector, dict) and isinstance(count, int)
    assert all(isinstance(v, float) for v in vector.values())


@pytest.mark.asyncio
async def test_reading_the_live_estimate_does_not_consume_it(db_session, no_retention):
    """The prompt reads it on every turn; a read that emptied it would make
    the second turn of a session behave like the first."""
    await _run_session(db_session, "sess-reread", n=3)

    first = diagnostic_session.live_vector("sess-reread")
    second = diagnostic_session.live_vector("sess-reread")
    assert first[1] == second[1] == 3


@pytest.mark.asyncio
async def test_the_estimate_is_released_once_the_summary_reports_it(db_session, no_retention):
    """The summary is the last moment the estimate is needed. Holding it for
    the full TTL afterwards would mean a finished session's estimate sat in
    memory for six hours for no reason."""
    await _run_session(db_session, "sess-summarised", n=3)
    assert diagnostic_session.active_session_count() == 1

    snapshot = await diagnostic_session.summary("sess-summarised", "Ada")
    assert snapshot["evidence_count"] == 3

    diagnostic_session.discard("sess-summarised")
    assert diagnostic_session.active_session_count() == 0
