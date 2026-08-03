"""
The work ledger (services/diagnostic/activity.py) — evidence of what a
student has DONE, as distinct from what Bede infers they can do.

Why this is a separate instrument rather than another number on the mastery
vector: MasteryProfile answers "how likely is it this child has mastered
X", which is a claim about the child. The ledger answers "what has this
child actually finished, and how much help did it take", which is a record
of events. Only the second can honestly support a parent arranging one of
their students to help another — that is peer teaching grounded in
demonstrated work rather than in a measured trait.

These tests exist mostly to hold the line on what the ledger REFUSES to
produce. It would be very easy for a work record to drift back into a
score, and every guard against that is asserted here rather than trusted.
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, SkillActivityLog
from services.diagnostic.activity import (
    ASSISTANCE_LEVELS,
    assistance_for_outcome,
    pod_activity,
    record_activity,
    summarize,
)


@pytest_asyncio.fixture
async def db_session():
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


# ── What counts as completed work ────────────────────────────────────────

@pytest.mark.parametrize("outcome,assistance", [
    ("correct", "unaided"),
    ("partial", "with_a_hint"),
    ("hint_dependent", "with_help"),
])
def test_outcomes_map_to_factual_assistance_levels(outcome, assistance):
    assert assistance_for_outcome(outcome) == assistance
    assert assistance in ASSISTANCE_LEVELS


def test_an_incorrect_attempt_is_not_completed_work():
    """
    Deliberate. A task attempted and missed is not a completed activity,
    and logging it here would turn a work ledger into a record of failures
    — precisely what this table exists to avoid being. The mastery engine
    already captures that a child struggled; the ledger is for what they
    finished.
    """
    assert assistance_for_outcome("incorrect") is None


@pytest.mark.asyncio
async def test_an_incorrect_outcome_writes_no_row(db_session):
    wrote = await record_activity(
        db_session, "Wren", "mathematics", "oa.division_facts", "Knows division facts", "incorrect",
    )
    assert wrote is False
    rows = (await db_session.execute(select(SkillActivityLog))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_a_completed_activity_persists_and_is_encrypted(db_session):
    assert await record_activity(
        db_session, "Wren", "mathematics", "fr.unit_fractions", "Understands unit fractions", "correct",
    )
    row = (await db_session.execute(select(SkillActivityLog))).scalar_one()
    assert row.student_name == "Wren"
    assert row.skill_id == "fr.unit_fractions"
    # The label and assistance live only inside the encrypted blob — the
    # same derived-not-raw privacy class as NarrationAssessment.
    assert b"Understands unit fractions" not in row.detail_enc
    assert b"unaided" not in row.detail_enc


# ── What the summary reports, and what it refuses to ─────────────────────

@pytest.mark.asyncio
async def test_summary_counts_work_without_scoring_the_child(db_session):
    for outcome in ("correct", "correct", "partial", "hint_dependent"):
        await record_activity(
            db_session, "Wren", "mathematics", "fr.equivalent_fractions",
            "Finds equivalent fractions", outcome,
        )
    summary = await summarize(db_session, "Wren")

    entry = summary["skills"][0]
    assert entry["completed"] == 4
    assert entry["unaided"] == 2
    assert entry["with_a_hint"] == 1
    assert entry["with_help"] == 1
    assert entry["last_worked"] is not None

    # The guard that matters: no score, level, average, or percentage
    # anywhere in the payload. Each of those would collapse a record of
    # work back into a judgment of the person.
    forbidden = {"probability", "level", "score", "average", "percent",
                 "mastery", "rank", "grade_band", "calibration"}
    assert not (forbidden & set(entry))
    assert not (forbidden & set(summary))


@pytest.mark.asyncio
async def test_summary_is_empty_rather_than_erroring_for_an_unknown_student(db_session):
    summary = await summarize(db_session, "Nobody")
    assert summary["total"] == 0
    assert summary["skills"] == []


@pytest.mark.asyncio
async def test_summary_can_be_scoped_to_one_subject_area(db_session):
    await record_activity(db_session, "Wren", "mathematics", "oa.division_facts", "Division facts", "correct")
    await record_activity(db_session, "Wren", "literacy", "morphology", "Word roots", "correct")

    assert (await summarize(db_session, "Wren"))["total"] == 2
    only_literacy = await summarize(db_session, "Wren", subject_area="literacy")
    assert only_literacy["total"] == 1
    assert only_literacy["skills"][0]["skill_id"] == "morphology"


@pytest.mark.asyncio
async def test_work_outside_the_window_is_excluded(db_session):
    await record_activity(db_session, "Wren", "mathematics", "oa.division_facts", "Division facts", "correct")
    row = (await db_session.execute(select(SkillActivityLog))).scalar_one()
    row.completed_at = datetime.now(timezone.utc) - timedelta(days=200)
    await db_session.commit()

    assert (await summarize(db_session, "Wren", since_days=30))["total"] == 0
    assert (await summarize(db_session, "Wren", since_days=365))["total"] == 1


# ── The pod view: a roster of who has done what, never a ranking ─────────

@pytest.mark.asyncio
async def test_pod_view_names_who_has_done_the_work(db_session):
    for _ in range(3):
        await record_activity(db_session, "Ada", "mathematics", "nbt.long_division", "Long division", "correct")
    await record_activity(
        db_session, "Wren", "mathematics", "nbt.long_division", "Long division", "hint_dependent",
    )

    pod = await pod_activity(db_session, ["Ada", "Wren"])
    skill = next(s for s in pod["skills"] if s["skill_id"] == "nbt.long_division")
    by_name = {w["student_name"]: w for w in skill["worked_by"]}

    assert by_name["Ada"]["completed"] == 3
    assert by_name["Ada"]["unaided"] == 3
    assert by_name["Wren"]["completed"] == 1
    assert by_name["Wren"]["unaided"] == 0


@pytest.mark.asyncio
async def test_pod_view_emits_no_ranking_of_students(db_session):
    """
    The line this whole design turns on. A roster of who has done a piece
    of work supports a parent asking one child to show another. A ranking
    of children is a different object, and this project does not build one
    — so the payload carries no per-student total, no ordering by any
    measure, and no comparative field at all.
    """
    for _ in range(5):
        await record_activity(db_session, "Ada", "mathematics", "fr.multiply_fractions", "Multiplies fractions", "correct")
    await record_activity(db_session, "Wren", "mathematics", "fr.multiply_fractions", "Multiplies fractions", "correct")

    pod = await pod_activity(db_session, ["Wren", "Ada"])

    # No top-level per-student aggregate.
    assert set(pod) == {"since_days", "skills"}
    # Students are ordered by NAME, never by how much they've done — the
    # order must not change when the amounts do.
    names = [w["student_name"] for w in pod["skills"][0]["worked_by"]]
    assert names == sorted(names)

    forbidden = {"rank", "leader", "ahead", "best", "top", "score", "level", "total"}
    for skill in pod["skills"]:
        for worked in skill["worked_by"]:
            assert not (forbidden & set(worked))


@pytest.mark.asyncio
async def test_pod_view_skips_a_student_with_no_work_rather_than_listing_them_as_zero(db_session):
    """
    A child who hasn't done a piece of work yet simply isn't on that
    skill's roster. Listing them at zero alongside a sibling's count is a
    comparison wearing a roster's clothes.
    """
    await record_activity(db_session, "Ada", "mathematics", "geo.pythagorean", "Pythagorean theorem", "correct")
    pod = await pod_activity(db_session, ["Ada", "Wren"])
    skill = next(s for s in pod["skills"] if s["skill_id"] == "geo.pythagorean")
    assert [w["student_name"] for w in skill["worked_by"]] == ["Ada"]


# ── Wiring ───────────────────────────────────────────────────────────────

def test_the_ledger_is_wired_into_every_evidence_path():
    """
    A skill area that writes mastery but not activity would be invisible in
    the ledger — the same silent-omission class as the skill-map backfill.
    """
    import inspect

    from services import ai_service

    source = inspect.getsource(ai_service)
    assert source.count("_record_work_done(") >= 5  # helper + 4 call sites


def test_deletion_cascade_includes_the_ledger():
    """Every per-student table must be reachable by student deletion —
    see docs/DATA_RETENTION.md."""
    import inspect

    from services import student_deletion

    assert "SkillActivityLog" in inspect.getsource(student_deletion)


def test_the_pod_route_is_declared_before_the_parameterized_one():
    """
    FastAPI matches in declaration order, so /diagnostic/{student_name}/activity
    would otherwise swallow /diagnostic/pod/activity as student_name="pod".
    """
    from routers.diagnostic import router

    paths = [r.path for r in router.routes]
    assert paths.index("/diagnostic/pod/activity") < paths.index("/diagnostic/{student_name}/activity")
