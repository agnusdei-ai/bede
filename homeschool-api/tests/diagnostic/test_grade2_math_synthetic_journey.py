"""Grade 2 mathematics: real diagnostic persistence and cross-session recheck.

This is deliberately a *bounded* synthetic qualification slice, not a claim
that Bede's complete adult-approved tutoring or delayed-retention journey is
integrated. The story (27 + 15, regrouping) supplies the human-readable
scenario; observations enter through Bede's actual 1:1 Q-matrix, Bayesian
mastery estimator, encrypted SQLite persistence, and parent summary service.
No model-generated answer is trusted or substituted for evidence.

Still separately required for the full journey: authenticated institutional
learner scope, durable teacher approval and lesson delivery, real tutor
interaction, and scheduled delayed-retention assessment. See #685 and #773.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, DiagnosticEvidenceLog, MasteryProfile
from core.encryption import decrypt_json, initialize_encryption, student_aad
from core import student_keys
from services.diagnostic import get_mastery_summary, process_evidence
from services.diagnostic.skill_map import prerequisites_of

GRADE_BAND = "K-2"
LEARNER = "SYNTHETIC_GRADE2_MATH_001"
OTHER_LEARNER = "SYNTHETIC_GRADE2_MATH_002"
PLACE_VALUE = "nbt.place_value_tens"
ADDITION = "nbt.add_within_100"


@pytest_asyncio.fixture
async def db_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        await initialize_encryption(settings.master_secret, db)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_grade2_regrouping_gap_to_independent_recheck_persists_across_sessions(
    db_factory, monkeypatch,
):
    """Incorrect tens/ones + hint-assisted 27+15 cannot count as mastery.

    Later independent observations on tens/ones and addition are submitted
    in a new DB session. This verifies persistence and the existing mastery
    engine's response to evidence, NOT real tutor delivery or elapsed-time
    retention. The words 'independent' and 'hint' describe synthetic
    observations; no LLM is asked to judge an answer in this test.
    """
    monkeypatch.setattr(settings, "diagnostic_evidence_log_enabled", True)
    assert {PLACE_VALUE, "oa.add_within_20"} <= set(prerequisites_of(ADDITION))

    async with db_factory() as db:
        assert await get_mastery_summary(db, LEARNER) is None
        assert await get_mastery_summary(db, OTHER_LEARNER) is None

        first = await process_evidence(
            db, LEARNER, f"probe.{PLACE_VALUE}", "incorrect", 1.0, GRADE_BAND,
        )
        assert first[PLACE_VALUE] < 0.4

        assisted = await process_evidence(
            db, LEARNER, f"probe.{ADDITION}", "hint_dependent", 1.0, GRADE_BAND,
        )
        assert assisted[ADDITION] < 0.8
        summary = await get_mastery_summary(db, LEARNER)
        assert summary["evidence_count"] == 2
        assert summary["calibration"] is True
        assert PLACE_VALUE in {item["skill_id"] for item in summary["gaps"]}
        assert await get_mastery_summary(db, OTHER_LEARNER) is None

    # Reopen the real database session: no in-memory learner vector is
    # carried forward. Persisted encrypted mastery is loaded on each call.
    async with db_factory() as db:
        before = await get_mastery_summary(db, LEARNER)
        assert before["evidence_count"] == 2
        for _ in range(4):
            await process_evidence(
                db, LEARNER, f"probe.{PLACE_VALUE}", "correct", 1.0, GRADE_BAND,
            )
        for _ in range(5):
            await process_evidence(
                db, LEARNER, f"probe.{ADDITION}", "correct", 1.0, GRADE_BAND,
            )

        after = await get_mastery_summary(db, LEARNER)
        assert after["evidence_count"] == 11
        assert after["calibration"] is False
        skill_views = {
            item["skill_id"]: item
            for domain in after["domains"] for item in domain["skills"]
        }
        assert skill_views[PLACE_VALUE]["probability"] >= 0.8
        assert skill_views[ADDITION]["probability"] >= 0.8
        assert ADDITION not in {item["skill_id"] for item in after["gaps"]}
        assert await get_mastery_summary(db, OTHER_LEARNER) is None

        row = (await db.execute(select(MasteryProfile).where(
            MasteryProfile.student_name == LEARNER,
            MasteryProfile.subject_area == "mathematics",
        ))).scalar_one()
        decrypted = decrypt_json(
            row.profile_enc,
            student_aad("mastery_profiles", "profile_enc", LEARNER, "mathematics"),
            await student_keys.get_existing(db, LEARNER),
        )
        assert decrypted[ADDITION] == skill_views[ADDITION]["probability"]

        logs = (await db.execute(select(DiagnosticEvidenceLog).where(
            DiagnosticEvidenceLog.student_name == LEARNER,
        ))).scalars().all()
        assert len(logs) == 11
        for log in logs:
            deltas = decrypt_json(
                log.delta_enc,
                student_aad("diagnostic_evidence_log", "delta_enc", LEARNER),
                await student_keys.get_existing(db, LEARNER),
            )
            assert deltas
            assert all(set(delta) == {
                "skill_id", "prior", "posterior", "probe_id", "model_used",
            } for delta in deltas)


@pytest.mark.asyncio
async def test_grade2_unknown_probe_cannot_forge_a_mastery_profile(db_factory):
    async with db_factory() as db:
        await process_evidence(
            db, LEARNER, "probe.synthetic_invented_grade2_skill",
            "correct", 1.0, GRADE_BAND,
        )
        assert await get_mastery_summary(db, LEARNER) is None
        assert (await db.execute(select(MasteryProfile).where(
            MasteryProfile.student_name == LEARNER,
        ))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_grade2_unknown_probe_preserves_unrelated_pending_transaction(db_factory):
    """An invented probe must not undo a different learner's pending write.

    The synthetic evidence_count increment is a transaction sentinel, not a
    mastery claim. The real process_evidence path previously called
    db.rollback() on an unknown probe, silently discarding this write.
    """
    async with db_factory() as db:
        await process_evidence(
            db, OTHER_LEARNER, f"probe.{PLACE_VALUE}", "correct", 1.0, GRADE_BAND,
        )
        row = (await db.execute(select(MasteryProfile).where(
            MasteryProfile.student_name == OTHER_LEARNER,
            MasteryProfile.subject_area == "mathematics",
        ))).scalar_one()
        row.evidence_count += 1
        await db.flush()
        await process_evidence(
            db, LEARNER, "probe.synthetic_invented_grade2_skill",
            "correct", 1.0, GRADE_BAND,
        )
        await db.commit()

    async with db_factory() as db:
        persisted = (await db.execute(select(MasteryProfile).where(
            MasteryProfile.student_name == OTHER_LEARNER,
            MasteryProfile.subject_area == "mathematics",
        ))).scalar_one()
        assert persisted.evidence_count == 2
        assert await get_mastery_summary(db, LEARNER) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "confidence"),
    [
        ("invented_model_success", 1.0),
        ("correct", float("nan")),
        ("correct", float("inf")),
        ("correct", -float("inf")),
        ("correct", "high"),
        ("correct", -0.1),
        ("correct", 1.01),
        ("correct", True),
        ("correct", 0.0),
    ],
)
async def test_grade2_untrusted_evidence_cannot_change_mastery(
    db_factory, outcome, confidence,
):
    """Invalid model-supplied evidence must neither invent nor revise mastery.

    Exercise the actual encrypted SQLite persistence path, not a mocked
    Bayesian function. A valid baseline is retained across the invalid
    observation; no derived evidence-log row may be added.
    """
    async with db_factory() as db:
        await process_evidence(
            db, LEARNER, f"probe.{PLACE_VALUE}", "incorrect", 1.0, GRADE_BAND,
        )
        before = await get_mastery_summary(db, LEARNER)
        assert before is not None
        await process_evidence(
            db, LEARNER, f"probe.{ADDITION}", outcome, confidence, GRADE_BAND,
        )
        after = await get_mastery_summary(db, LEARNER)
        assert after == before
        assert after["evidence_count"] == 1
        logs = (await db.execute(select(DiagnosticEvidenceLog).where(
            DiagnosticEvidenceLog.student_name == LEARNER,
        ))).scalars().all()
        # Logging may be disabled in the shared environment; either way
        # the invalid observation cannot create a second delta.
        assert len(logs) <= 1


@pytest.mark.asyncio
async def test_grade2_zero_confidence_cannot_cold_start_mastery(db_factory):
    """Uninformative evidence must not create a false learner calibration."""
    async with db_factory() as db:
        await process_evidence(
            db, LEARNER, f"probe.{PLACE_VALUE}", "correct", 0.0, GRADE_BAND,
        )
        assert await get_mastery_summary(db, LEARNER) is None
        assert (await db.execute(select(MasteryProfile).where(
            MasteryProfile.student_name == LEARNER,
        ))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_grade2_contradictory_evidence_stays_revisable_and_never_secure(db_factory):
    """Alternating right and wrong answers must not certify mastery.

    Before POSTERIOR_FLOOR/POSTERIOR_CEILING, calibration mode's 2x step
    clamped a new learner's first correct answer to exactly 1.0, and four
    wrong answers after it left the skill reported secure: a probability of
    1.0 cannot move under Bayes' rule. The same happened at 0.0 for a first
    wrong answer.
    """
    from services.diagnostic.mastery import POSTERIOR_CEILING, POSTERIOR_FLOOR

    async with db_factory() as db:
        previous = None
        for outcome in ["correct", "incorrect"] * 4:
            vector = await process_evidence(
                db, LEARNER, f"probe.{ADDITION}", outcome, 1.0, GRADE_BAND,
            )
            value = vector[ADDITION]
            assert POSTERIOR_FLOOR <= value <= POSTERIOR_CEILING
            if previous is not None:
                # Every answer moves the estimate in its own direction.
                assert (value > previous) if outcome == "correct" else (value < previous)
            previous = value
        summary = await get_mastery_summary(db, LEARNER)
        views = {
            item["skill_id"]: item
            for domain in summary["domains"] for item in domain["skills"]
        }
        assert views[ADDITION]["probability"] < 0.8

        # A first wrong answer on a fresh skill must stay liftable too.
        low = await process_evidence(
            db, OTHER_LEARNER, f"probe.{PLACE_VALUE}", "incorrect", 1.0, GRADE_BAND,
        )
        lifted = await process_evidence(
            db, OTHER_LEARNER, f"probe.{PLACE_VALUE}", "correct", 1.0, GRADE_BAND,
        )
        assert lifted[PLACE_VALUE] > low[PLACE_VALUE] >= POSTERIOR_FLOOR
