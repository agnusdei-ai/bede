"""
Composition mastery engine — services/diagnostic/composition.py. Mirrors
tests/diagnostic/test_mastery.py + test_facade_persisted.py's structure for
the math engine, but against the much simpler rubric-blend update rule (no
CDM/KST — see composition.py's own docstring for why).
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, MasteryProfile
from core.encryption import decrypt_json, student_aad
from services.diagnostic.composition import (
    CALIBRATION_THRESHOLD,
    DOMAINS,
    apply_assessment,
    build_summary_view,
    get_composition_summary,
    new_vector,
    process_assessment,
)


# ── Pure in-memory unit tests (no DB) ────────────────────────────────────────

def test_new_vector_is_flat_half_across_all_domains():
    vector = new_vector()
    assert set(vector) == set(DOMAINS)
    assert all(p == 0.5 for p in vector.values())


def test_apply_assessment_moves_a_high_score_up_and_a_low_score_down():
    vector = new_vector()
    updated, updates = apply_assessment(
        vector,
        {"completeness": 5, "sequence": 1, "detail": 3, "language_quality": 4, "synthesis": 2},
    )
    assert updated["completeness"] > 0.5
    assert updated["sequence"] < 0.5
    assert updated["detail"] == pytest.approx(0.5)  # (3-1)/4 == 0.5, exactly the prior — no movement
    assert len(updates) == 5


def test_apply_assessment_ignores_unrelated_or_missing_fields():
    """assess_narration's tool_input carries other keys too (term_topic,
    concepts_demonstrated, adaptive_signal, ...) — passing the whole dict
    through must only ever touch the five known domains."""
    vector = new_vector()
    updated, updates = apply_assessment(
        vector,
        {
            "completeness": 4,
            "term_topic": "the water cycle",
            "adaptive_signal": "advance",
            "concepts_demonstrated": ["evaporation"],
        },
    )
    assert len(updates) == 1
    assert updates[0].domain == "completeness"
    assert updated["sequence"] == 0.5  # untouched


def test_apply_assessment_clamps_calibration_push_to_zero_one():
    vector = {"completeness": 0.95}
    updated, _ = apply_assessment(vector, {"completeness": 5}, calibration_weight=2.0)
    assert updated["completeness"] <= 1.0


def test_build_summary_view_flags_calibration_below_threshold():
    vector = new_vector()
    summary = build_summary_view(vector, "Ada", evidence_count=1, updated_at="2026-01-01T00:00:00+00:00")
    assert summary["calibration"] is True
    assert summary["subject_area"] == "composition"
    assert len(summary["domains"]) == 5

    settled = build_summary_view(vector, "Ada", evidence_count=CALIBRATION_THRESHOLD, updated_at="2026-01-01T00:00:00+00:00")
    assert settled["calibration"] is False


def test_build_summary_view_flat_half_vector_has_no_gaps_and_no_secure_domains():
    """0.5 sits in the 'developing' band (>=0.4, <0.8) for every domain at
    cold start — nothing should read as a 'gap' just from having no
    evidence yet, and nothing should read as 'secure' either."""
    summary = build_summary_view(new_vector(), "Ada", evidence_count=0, updated_at="2026-01-01T00:00:00+00:00")
    assert summary["gaps"] == []
    assert len(summary["next_steps"]) == 3  # capped, all domains equally "not secure"


# ── DB-backed round trip (real AES-256-GCM via aiosqlite, no live Postgres) ──

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


_SCORES = {"completeness": 4, "sequence": 4, "detail": 3, "language_quality": 5, "synthesis": 3}


@pytest.mark.asyncio
async def test_first_assessment_cold_starts_and_persists_a_composition_row(db_session):
    from sqlalchemy import select

    await process_assessment(db_session, "Emma", _SCORES)

    row = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Emma")
    )).scalar_one_or_none()

    assert row is not None
    assert row.subject_area == "composition"
    assert row.evidence_count == 1


@pytest.mark.asyncio
async def test_second_assessment_updates_the_existing_row_not_a_new_one(db_session):
    from sqlalchemy import select

    await process_assessment(db_session, "Noah", _SCORES)
    await process_assessment(db_session, "Noah", _SCORES)

    rows = (await db_session.execute(
        select(MasteryProfile).where(
            MasteryProfile.student_name == "Noah", MasteryProfile.subject_area == "composition",
        )
    )).scalars().all()

    assert len(rows) == 1
    assert rows[0].evidence_count == 2


@pytest.mark.asyncio
async def test_composition_and_math_rows_are_independent_for_the_same_student(db_session):
    from sqlalchemy import select
    from services.diagnostic import process_evidence

    await process_assessment(db_session, "Ethan", _SCORES)
    await process_evidence(db_session, "Ethan", "probe.cc.rote_count_20", "correct", 1.0, "K-2")

    rows = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Ethan")
    )).scalars().all()

    assert {row.subject_area for row in rows} == {"composition", "mathematics"}


@pytest.mark.asyncio
async def test_a_tool_call_with_no_recognizable_scores_is_a_true_no_op(db_session):
    from sqlalchemy import select

    result = await process_assessment(db_session, "Ava", {"term_topic": "photosynthesis"})

    row = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Ava")
    )).scalar_one_or_none()

    assert row is None
    assert result is None


@pytest.mark.asyncio
async def test_corrupted_existing_row_degrades_to_cold_start_instead_of_raising(db_session):
    from sqlalchemy import select

    db_session.add(MasteryProfile(
        student_name="Zoe", subject_area="composition",
        evidence_count=3, profile_enc=b"not a valid SAGE envelope",
    ))
    await db_session.commit()

    result_vector = await process_assessment(db_session, "Zoe", _SCORES)
    assert result_vector is not None
    assert result_vector["language_quality"] > 0.5  # ran on a fresh cold-start vector, not a decrypt crash

    rows = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Zoe")
    )).scalars().all()
    assert len(rows) == 1  # updated in place, not a duplicate PK row
    assert decrypt_json(rows[0].profile_enc, student_aad("mastery_profiles", "profile_enc", rows[0].student_name, "composition")) == result_vector


@pytest.mark.asyncio
async def test_get_composition_summary_returns_none_with_no_evidence_yet(db_session):
    assert await get_composition_summary(db_session, "Nobody") is None


@pytest.mark.asyncio
async def test_get_composition_summary_matches_the_persisted_vector(db_session):
    await process_assessment(db_session, "Grace", _SCORES)

    summary = await get_composition_summary(db_session, "Grace")

    assert summary["student_name"] == "Grace"
    assert summary["subject_area"] == "composition"
    assert summary["evidence_count"] == 1
    assert summary["calibration"] is True  # 1 < CALIBRATION_THRESHOLD (2)
    assert len(summary["domains"]) == 5
