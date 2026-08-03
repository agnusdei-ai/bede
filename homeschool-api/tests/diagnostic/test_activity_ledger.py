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


def test_the_pod_route_takes_students_as_a_repeated_parameter_not_a_joined_string():
    """
    student_name is free text a parent types with no character restriction,
    so a comma-joined `students` value split a name like "Ada, Jr." into
    two students who don't exist — and the parent silently got a roster
    with that child missing rather than an error. One repeated parameter
    per name is the only form that can't do that.
    """
    import inspect

    from routers.diagnostic import get_pod_activity

    signature = inspect.signature(get_pod_activity)
    annotation = signature.parameters["students"].annotation
    assert annotation in (list[str], "list[str]"), annotation
    assert 'split(","' not in inspect.getsource(get_pod_activity)


# ── Scoring the work: quality, distinction, speed ────────────────────────
#
# The distinction that makes this safe: Bede scores the WORK PRODUCT, which
# is ordinary assessment, and never the child, which would be a claim it has
# no standing to make. Every scale's floor is a real outcome — there is no
# "poor" quality and no "slow" pace.

@pytest.mark.asyncio
async def test_scores_are_recorded_and_reported_as_distributions(db_session):
    for quality, distinction, speed in [
        ("exemplary", "original", "brisk"),
        ("proficient", "expected", "steady"),
        ("exemplary", "noteworthy", "deliberate"),
    ]:
        await record_activity(
            db_session, "Ada", "mathematics", "ee.factor_expressions", "Factors expressions",
            "correct", quality=quality, distinction=distinction, speed=speed,
        )
    entry = (await summarize(db_session, "Ada"))["skills"][0]

    assert entry["scored"] == 3
    assert entry["quality"] == {"adequate": 0, "proficient": 1, "exemplary": 2}
    assert entry["distinction"] == {"expected": 1, "noteworthy": 1, "original": 1}
    assert entry["speed"] == {"deliberate": 1, "steady": 1, "brisk": 1}


@pytest.mark.asyncio
async def test_scores_are_optional_and_absence_is_distinguishable(db_session):
    """
    A missing score must never read as a low one. Bede omits a dimension it
    didn't genuinely observe, and that has to stay visible as 'not judged'
    rather than collapsing into 'adequate'.
    """
    await record_activity(db_session, "Ada", "mathematics", "ns.integers", "Integers", "correct")
    entry = (await summarize(db_session, "Ada"))["skills"][0]

    assert entry["completed"] == 1
    assert entry["scored"] == 0
    assert sum(entry["quality"].values()) == 0


@pytest.mark.asyncio
async def test_an_invalid_score_is_dropped_not_coerced(db_session):
    """A hallucinated level must not silently become a real one."""
    await record_activity(
        db_session, "Ada", "mathematics", "ns.integers", "Integers", "correct",
        quality="brilliant", distinction="amazing", speed="lightning",
    )
    entry = (await summarize(db_session, "Ada"))["skills"][0]
    assert entry["scored"] == 0
    assert sum(entry["quality"].values()) == 0


@pytest.mark.asyncio
async def test_summary_still_reports_no_average_or_grade(db_session):
    """
    Scoring the work must not reintroduce a score for the CHILD. The
    payload gains distributions, never a mean, a letter, or a level — a
    mean over an ordinal scale would invent precision the scale doesn't
    carry and read as a grade.
    """
    await record_activity(
        db_session, "Ada", "mathematics", "ns.integers", "Integers", "correct",
        quality="exemplary", distinction="original", speed="brisk",
    )
    summary = await summarize(db_session, "Ada")
    entry = summary["skills"][0]
    forbidden = {"average", "mean", "score", "grade", "level", "rank", "percentile"}
    assert not (forbidden & set(entry))
    assert not (forbidden & set(summary))


# ── The learning-entrepreneur read ───────────────────────────────────────

@pytest.mark.asyncio
async def test_initiative_signal_counts_work_beyond_the_task(db_session):
    from services.diagnostic.activity import initiative_signal

    await record_activity(db_session, "Ada", "mathematics", "fn.slope", "Slope", "correct",
                          quality="exemplary", distinction="original", speed="brisk")
    await record_activity(db_session, "Ada", "mathematics", "fn.slope", "Slope", "correct",
                          quality="proficient", distinction="noteworthy", speed="steady")
    await record_activity(db_session, "Ada", "mathematics", "ns.integers", "Integers", "correct",
                          quality="adequate", distinction="expected", speed="deliberate")

    signal = initiative_signal(await summarize(db_session, "Ada"))
    assert signal["exemplary"] == 1
    assert signal["beyond_the_task"] == 2      # original + noteworthy
    assert signal["brisk"] == 1
    assert signal["standout_skills"][0]["skill_id"] == "fn.slope"


@pytest.mark.asyncio
async def test_initiative_signal_assigns_no_verdict_or_label(db_session):
    """
    The guard that keeps this from becoming a character rating. A learning
    entrepreneur is not a category Bede is competent to place a child in —
    it reports counts of work and lets the parent read them.
    """
    from services.diagnostic.activity import initiative_signal

    await record_activity(db_session, "Ada", "mathematics", "fn.slope", "Slope", "correct",
                          quality="exemplary", distinction="original", speed="brisk")
    signal = initiative_signal(await summarize(db_session, "Ada"))

    forbidden = {"is_entrepreneur", "entrepreneur", "verdict", "label", "rating",
                 "score", "type", "percentile", "threshold"}
    assert not (forbidden & set(signal))
    assert set(signal) == {
        "student_name", "scored_activities", "exemplary", "beyond_the_task",
        "brisk", "standout_skills",
    }


def test_the_prompt_scores_the_work_and_forbids_hurrying():
    """
    Two rules that matter more than the scores themselves: Bede judges the
    work rather than the child, and pace is something it notices, never
    something it asks for. A child who feels raced produces worse work.
    """
    from services.ai_service import _WORK_SCORING_NOTE

    note = " ".join(_WORK_SCORING_NOTE.split()).lower()
    assert "you are scoring the work, never the child" in note
    assert "never hurry a child" in note
    assert "omit any dimension you did not genuinely observe" in note
    # `original` must stay rare, or the signal stops meaning anything.
    assert "reserve it for a child bringing a genuine idea" in note


def test_every_recording_tool_accepts_the_three_dimensions_as_optional():
    from services.ai_service import TUTOR_TOOLS

    need = {"quality", "distinction", "speed"}
    for tool in TUTOR_TOOLS:
        if not tool["name"].startswith("record_"):
            continue
        schema = tool["input_schema"]
        assert need <= set(schema["properties"]), f"{tool['name']} is missing scoring fields"
        # Optional, never required — a missing score has to stay honest.
        assert not (need & set(schema.get("required", []))), f"{tool['name']} made a score mandatory"
        # And they must live INSIDE properties, not as stray sibling keys.
        assert not (need & set(schema)), f"{tool['name']} has scoring keys outside properties"
