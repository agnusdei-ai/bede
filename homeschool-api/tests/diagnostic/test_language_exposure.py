"""
Language-exposure mastery engine — services/diagnostic/language_exposure.py.
Mirrors tests/diagnostic/test_phonics.py's structure, adapted for this
engine's key differences: next_steps sorts by probability (composition's
approach) rather than a fixed developmental order (there is no "correct
sequence" of languages), and evidence isolation now needs to hold across
FOUR subject areas on the same student, not three.
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base, MasteryProfile
from core.encryption import decrypt_json
from services.diagnostic.language_exposure import (
    CALIBRATION_THRESHOLD,
    LANGUAGES,
    apply_evidence,
    build_summary_view,
    get_language_summary,
    new_vector,
    process_evidence,
)


# ── Pure in-memory unit tests (no DB) ────────────────────────────────────────

def test_new_vector_is_flat_half_across_all_languages():
    vector = new_vector()
    assert set(vector) == set(LANGUAGES)
    assert all(p == 0.5 for p in vector.values())


def test_apply_evidence_moves_a_correct_answer_up():
    vector = new_vector()
    updated, updates = apply_evidence(vector, "latin", "correct")
    assert updated["latin"] > 0.5
    assert len(updates) == 1
    assert updates[0].language == "latin"


def test_apply_evidence_moves_an_incorrect_answer_down():
    vector = new_vector()
    updated, _ = apply_evidence(vector, "french", "incorrect")
    assert updated["french"] < 0.5


def test_apply_evidence_only_touches_the_one_language_evidenced():
    vector = new_vector()
    updated, _ = apply_evidence(vector, "spanish", "correct")
    for language in LANGUAGES:
        if language != "spanish":
            assert updated[language] == 0.5


def test_apply_evidence_is_a_true_no_op_for_an_unrecognized_language():
    vector = new_vector()
    updated, updates = apply_evidence(vector, "not_a_real_language", "correct")
    assert updates == []
    assert updated == vector


def test_apply_evidence_is_a_true_no_op_for_an_unrecognized_outcome():
    vector = new_vector()
    updated, updates = apply_evidence(vector, "latin", "not_a_real_outcome")
    assert updates == []
    assert updated == vector


def test_apply_evidence_clamps_calibration_push_to_zero_one():
    vector = {"latin": 0.95}
    updated, _ = apply_evidence(vector, "latin", "correct", calibration_weight=2.0)
    assert updated["latin"] <= 1.0


def test_build_summary_view_flags_calibration_below_threshold():
    vector = new_vector()
    summary = build_summary_view(vector, "Wren", evidence_count=1, updated_at="2026-01-01T00:00:00+00:00")
    assert summary["calibration"] is True
    assert summary["subject_area"] == "language_exposure"
    assert len(summary["domains"]) == 6

    settled = build_summary_view(vector, "Wren", evidence_count=CALIBRATION_THRESHOLD, updated_at="2026-01-01T00:00:00+00:00")
    assert settled["calibration"] is False


def test_next_steps_sorts_by_probability_not_a_fixed_order():
    """Unlike phonics (a real developmental sequence), languages have no
    prerequisite order — next_steps should surface the least-confident
    language first, regardless of where it falls in the LANGUAGES tuple.
    The other domains are pinned "secure" so both latin and spanish
    actually make it into the capped 3-item next_steps list."""
    vector = new_vector()
    vector["greek"] = 0.9      # secure — excluded from next_steps
    vector["french"] = 0.9     # secure — excluded
    vector["italian"] = 0.9    # secure — excluded
    vector["german"] = 0.9     # secure — excluded
    vector["spanish"] = 0.45   # earlier in LANGUAGES, less confident
    vector["latin"] = 0.6      # first in LANGUAGES, more confident
    summary = build_summary_view(vector, "Wren", evidence_count=5, updated_at="2026-01-01T00:00:00+00:00")
    next_step_ids = [s["skill_id"] for s in summary["next_steps"]]
    assert next_step_ids == ["language_exposure.spanish", "language_exposure.latin"]


def test_next_steps_caps_at_three():
    vector = new_vector()  # all six start at 0.5 ("developing")
    summary = build_summary_view(vector, "Wren", evidence_count=5, updated_at="2026-01-01T00:00:00+00:00")
    assert len(summary["next_steps"]) == 3


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


@pytest.mark.asyncio
async def test_first_evidence_cold_starts_and_persists_a_language_row(db_session):
    from sqlalchemy import select

    await process_evidence(db_session, "Wren", "latin", "correct")

    row = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Wren")
    )).scalar_one_or_none()

    assert row is not None
    assert row.subject_area == "language_exposure"
    assert row.evidence_count == 1


@pytest.mark.asyncio
async def test_second_evidence_updates_the_existing_row_not_a_new_one(db_session):
    from sqlalchemy import select

    await process_evidence(db_session, "Noah", "french", "correct")
    await process_evidence(db_session, "Noah", "latin", "partial")

    rows = (await db_session.execute(
        select(MasteryProfile).where(
            MasteryProfile.student_name == "Noah", MasteryProfile.subject_area == "language_exposure",
        )
    )).scalars().all()

    assert len(rows) == 1
    assert rows[0].evidence_count == 2


@pytest.mark.asyncio
async def test_language_math_composition_and_phonics_rows_are_independent_for_the_same_student(db_session):
    from sqlalchemy import select
    from services.diagnostic import process_evidence as process_math_evidence
    from services.diagnostic.composition import process_assessment
    from services.diagnostic.phonics import process_evidence as process_phonics_evidence

    await process_evidence(db_session, "Ethan", "latin", "correct")
    await process_math_evidence(db_session, "Ethan", "probe.cc.rote_count_20", "correct", 1.0, "K-2")
    await process_assessment(db_session, "Ethan", {
        "completeness": 4, "sequence": 3, "detail": 4, "language_quality": 5, "synthesis": 3,
    })
    await process_phonics_evidence(db_session, "Ethan", "letter_sound", "correct")

    rows = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Ethan")
    )).scalars().all()

    assert {row.subject_area for row in rows} == {
        "language_exposure", "mathematics", "composition", "phonics",
    }


@pytest.mark.asyncio
async def test_an_unrecognized_language_is_a_true_no_op(db_session):
    from sqlalchemy import select

    result = await process_evidence(db_session, "Ava", "not_a_real_language", "correct")

    row = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Ava")
    )).scalar_one_or_none()

    assert row is None
    assert result is None


@pytest.mark.asyncio
async def test_corrupted_existing_row_degrades_to_cold_start_instead_of_raising(db_session):
    from sqlalchemy import select

    db_session.add(MasteryProfile(
        student_name="Zoe", subject_area="language_exposure",
        evidence_count=3, profile_enc=b"not a valid SAGE envelope",
    ))
    await db_session.commit()

    result_vector = await process_evidence(db_session, "Zoe", "latin", "correct")
    assert result_vector is not None
    assert result_vector["latin"] > 0.5  # ran on a fresh cold-start vector, not a decrypt crash

    rows = (await db_session.execute(
        select(MasteryProfile).where(MasteryProfile.student_name == "Zoe")
    )).scalars().all()
    assert len(rows) == 1  # updated in place, not a duplicate PK row
    assert decrypt_json(rows[0].profile_enc) == result_vector


@pytest.mark.asyncio
async def test_get_language_summary_returns_none_with_no_evidence_yet(db_session):
    assert await get_language_summary(db_session, "Nobody") is None


@pytest.mark.asyncio
async def test_get_language_summary_matches_the_persisted_vector(db_session):
    await process_evidence(db_session, "Grace", "italian", "correct")

    summary = await get_language_summary(db_session, "Grace")

    assert summary["student_name"] == "Grace"
    assert summary["subject_area"] == "language_exposure"
    assert summary["evidence_count"] == 1
    assert summary["calibration"] is True  # 1 < CALIBRATION_THRESHOLD (3)
    assert len(summary["domains"]) == 6
