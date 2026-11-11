"""A confirmed quiz counts toward the mastery estimate and the work record
(services/practice/evidence.py, owner ruling 2026-11-11).

Driven through the real route functions against a real (SQLite) database,
so what is asserted is what a parent's confirmation actually writes: the
encrypted MasteryProfile rows the Progress page reads, and the encrypted
SkillActivityLog rows the work record reads.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core import student_keys
from core.config import settings
from core.database import (
    Base,
    MasteryProfile,
    PracticeEvidenceMark,
    SkillActivityLog,
    StudentConfig,
)
from core.encryption import decrypt_json, encrypt_json, student_aad
from models.practice import ConfirmAssessmentRequest, GradedAssessment
from models.schemas import GradeStage, SessionConfig, Subject
from routers import practice as practice_router
from routers.pod import _config_aad
from services.practice import evidence
from services.practice.packs.math import skill_for

PARENT = {"role": "parent"}


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        from core.encryption import initialize_encryption
        await initialize_encryption(settings.master_secret, session)
        for name, grade, stage in (("Ada", "4", GradeStage.core_mastery), ("Kit", "1", GradeStage.foundations)):
            key = await student_keys.get_or_create(session, name)
            config = SessionConfig(student_name=name, grade=grade, grade_stage=stage,
                                   subjects=[Subject.mathematics, Subject.language_arts])
            session.add(StudentConfig(
                student_name=name, config_enc=encrypt_json(config.model_dump(), _config_aad(name), key),
            ))
        await session.commit()
        yield session
    await engine.dispose()


def quiz(subject: str, items: list[dict]) -> GradedAssessment:
    return GradedAssessment.model_validate({
        "subject": subject,
        "sections": [{"label": "Quiz", "items": [
            {"number": n, **item} for n, item in enumerate(items, start=1)
        ]}],
    })


MATH = quiz("math", [
    {"prompt": "7 × 8 =", "student_response": "56", "teacher_mark": "correct"},
    {"prompt": "27 + 15 =", "student_response": "32", "teacher_mark": "incorrect", "teacher_correction": "42"},
    {"prompt": "3/4 - 1/8 =", "student_response": "5/8", "teacher_mark": "correct"},
    {"prompt": "6 × 7 =", "student_response": "42?", "teacher_mark": "partial"},
    {"prompt": "Sam has 3 apples and buys 4 more. How many now?", "student_response": "7",
     "teacher_mark": "correct"},  # a word problem: no skill can be read off it
    {"prompt": "12 ÷ 4 =", "student_response": "3", "teacher_mark": "unmarked"},  # no teacher mark
    {"prompt": "9 - 4 =", "student_response": "5", "teacher_mark": "correct", "excluded": True},
])


async def confirm(db, student: str, assessment: GradedAssessment) -> dict:
    created = await practice_router.enter_assessment(
        student, ConfirmAssessmentRequest(assessment=assessment), auth=PARENT, db=db)
    return created


async def mastery(db, student: str, area: str) -> dict:
    row = (await db.execute(select(MasteryProfile).where(
        MasteryProfile.student_name == student, MasteryProfile.subject_area == area,
    ))).scalar_one_or_none()
    if row is None:
        return {}
    key = await student_keys.get_existing(db, student)
    return {"count": row.evidence_count, "vector": decrypt_json(
        row.profile_enc, student_aad("mastery_profiles", "profile_enc", student, area), key)}


async def ledger(db, student: str) -> list[dict]:
    key = await student_keys.get_existing(db, student)
    out = []
    for row in (await db.execute(select(SkillActivityLog).where(SkillActivityLog.student_name == student))).scalars():
        out.append(decrypt_json(row.detail_enc, student_aad(
            "skill_activity_log", "detail_enc", student, row.subject_area, row.skill_id), key))
    return out


# ── Which skill a problem exercises ──────────────────────────────────────────

@pytest.mark.parametrize("prompt, skill", [
    ("7 × 8 =", "oa.multiplication_facts"),
    ("23 × 14 =", "nbt.standard_multiplication"),
    ("8 + 9 =", "oa.add_within_20"),
    ("27 + 15 =", "nbt.add_within_100"),
    ("52 − 27 =", "nbt.subtract_within_100"),
    ("56 ÷ 7 =", "oa.division_facts"),
    ("156 ÷ 12 =", "nbt.long_division"),
    ("1/2 + 1/3 =", "fr.add_subtract_fractions"),
    ("1/2 ÷ 1/4 =", "fr.divide_fractions"),
    ("2/3 × 3/4 =", "fr.multiply_fractions"),
    ("4.5 + 2.25 =", "nbt.decimal_operations"),
    ("2 + 3 × 4 =", "oa.order_of_operations"),
    ("-4 + 7 =", "ns.integers"),
    ("Sam has 3 apples and buys 4 more. How many now?", None),
    ("x + 4 = 9", None),
    ("327 + 485 =", None),  # no tracked skill for this size; better silent than wrong
])
def test_a_problem_maps_to_one_skill_only_when_the_skill_is_clear(prompt, skill):
    item = quiz("math", [{"prompt": prompt, "teacher_mark": "correct"}]).sections[0].items[0]
    assert skill_for(item) == skill


def test_every_skill_the_mapping_names_exists_in_the_skill_map():
    import inspect
    import re

    from services.diagnostic.skill_map import SKILL_MAP
    from services.practice.packs import math

    named = set(re.findall(r'"((?:oa|nbt|fr|md|geo|cc|ns)\.[a-z_0-9]+)"', inspect.getsource(math)))
    assert named and named <= set(SKILL_MAP)


def test_only_teacher_marked_included_questions_with_a_clear_skill_count():
    found = evidence.evidence_from(MATH, "3-5")
    assert [(e.skill_id, e.outcome) for e in found] == [
        ("oa.multiplication_facts", "correct"),
        ("nbt.add_within_100", "incorrect"),
        ("fr.add_subtract_fractions", "correct"),
        ("oa.multiplication_facts", "partial"),
    ]


def test_spelling_and_reading_count_only_for_grades_three_to_eight():
    spelling = quiz("spelling", [{"prompt": "Spell: because", "student_response": "because", "teacher_mark": "correct"}])
    reading = quiz("reading", [
        {"prompt": "What does 'ravenous' mean?", "student_response": "very hungry", "teacher_mark": "correct"},
        {"prompt": "Why did the fox leave?", "student_response": "it was scared", "teacher_mark": "partial"},
        {"prompt": "Where did the hen live?", "student_response": "on a farm", "teacher_mark": "correct"},
    ])
    assert [(e.subject_area, e.skill_id) for e in evidence.evidence_from(spelling, "6-8")] == [
        ("literacy", "spelling_patterns")]
    assert [e.skill_id for e in evidence.evidence_from(reading, "3-5")] == [
        "vocabulary", "inference", "literal_comprehension"]
    assert evidence.evidence_from(spelling, "K-2") == []
    assert evidence.evidence_from(reading, "K-2") == []


def test_subjects_with_no_engine_record_nothing():
    for subject in ("recall", "latin"):
        q = quiz(subject, [{"prompt": "What is the capital of France?", "student_response": "Paris",
                            "teacher_mark": "correct"}])
        assert evidence.evidence_from(q, "6-8") == []


# ── What a confirmation writes ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_confirming_a_quiz_moves_the_estimate_and_adds_completed_work(db):
    view = await confirm(db, "Ada", MATH)
    assert view["status"] == "confirmed" and view["counted"] == 4

    est = await mastery(db, "Ada", "mathematics")
    assert est["count"] == 4
    rows = await ledger(db, "Ada")
    # Only completed (correct) work is recorded, and it says where it was seen.
    # A partly right answer is not completed work, and recording it would
    # also call it "after a nudge", which is not what happened on paper.
    assert sorted(r["skill_id"] for r in rows) == ["fr.add_subtract_fractions", "oa.multiplication_facts"]
    assert all(r["source"] == "marked_quiz" and r["assistance"] == "unaided" for r in rows)
    assert all(r["label"] != r["skill_id"] for r in rows)  # named in the parent's language


@pytest.mark.asyncio
async def test_a_quiz_counts_once_however_often_it_is_confirmed(db):
    view = await confirm(db, "Ada", MATH)
    again = await practice_router.confirm_assessment(
        "Ada", view["id"], ConfirmAssessmentRequest(assessment=MATH), auth=PARENT, db=db)
    assert again["counted"] == 0
    assert (await mastery(db, "Ada", "mathematics"))["count"] == 4
    assert len(await ledger(db, "Ada")) == 2
    marks = (await db.execute(select(PracticeEvidenceMark))).scalars().all()
    assert [(m.assessment_id, m.student_name) for m in marks] == [(view["id"], "Ada")]


@pytest.mark.asyncio
async def test_a_reading_still_in_review_counts_nothing(db):
    flagged = quiz("math", [{"prompt": "7 × 8 =", "student_response": "56", "teacher_mark": "correct",
                             "ask_parent": "Is that a 6 or a 0?"}])
    view = await confirm(db, "Ada", flagged)
    assert view["status"] == "needs_review" and view["counted"] == 0
    assert await mastery(db, "Ada", "mathematics") == {}
    assert await ledger(db, "Ada") == []


@pytest.mark.asyncio
async def test_a_marked_quiz_moves_the_estimate_less_than_live_work(db):
    from services.diagnostic import process_evidence

    await confirm(db, "Ada", quiz("math", [{"prompt": "7 × 8 =", "student_response": "56",
                                            "teacher_mark": "correct"}]))
    from_quiz = (await mastery(db, "Ada", "mathematics"))["vector"]["oa.multiplication_facts"]

    await process_evidence(db, "Kit", "probe.oa.multiplication_facts", "correct", 1.0, "3-5")
    live = (await mastery(db, "Kit", "mathematics"))["vector"]["oa.multiplication_facts"]
    from services.diagnostic.mastery import new_vector
    prior = new_vector("3-5")["oa.multiplication_facts"]
    assert prior < from_quiz < live


async def _settled_literacy(db, student: str) -> None:
    """A student past calibration, every domain at 0.5: the one state in
    which a single observation does not saturate the estimate, so the
    weight's effect is visible. During calibration (fewer than five
    observations) the engine pushes so hard that a first observation reaches
    0 or 1 whatever its weight; that is the engine's own cold-start rule,
    and it applies to live work too."""
    from services.diagnostic import literacy
    key = await student_keys.get_or_create(db, student)
    db.add(MasteryProfile(
        student_name=student, subject_area="literacy", evidence_count=literacy.CALIBRATION_THRESHOLD,
        profile_enc=encrypt_json(literacy.new_vector(),
                                 student_aad("mastery_profiles", "profile_enc", student, "literacy"), key),
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_literacy_evidence_uses_the_reduced_weight(db):
    from services.diagnostic import literacy

    await _settled_literacy(db, "Ada")
    await _settled_literacy(db, "Kit")
    await confirm(db, "Ada", quiz("spelling", [
        {"prompt": "Spell: because", "student_response": "because", "teacher_mark": "correct"}]))
    from_quiz = (await mastery(db, "Ada", "literacy"))["vector"]["spelling_patterns"]
    await literacy.process_evidence(db, "Kit", "spelling_patterns", "correct")
    live = (await mastery(db, "Kit", "literacy"))["vector"]["spelling_patterns"]
    assert from_quiz == pytest.approx(0.75) and live == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_a_malformed_literacy_weight_records_nothing(db):
    from services.diagnostic import literacy

    for bad in (0, 1.5, -1, True, float("nan")):
        assert await literacy.process_evidence(db, "Ada", "spelling_patterns", "correct", weight=bad) is None
    assert await mastery(db, "Ada", "literacy") == {}


@pytest.mark.asyncio
async def test_a_k2_reading_quiz_writes_nothing(db):
    view = await confirm(db, "Kit", quiz("reading", [
        {"prompt": "Where did the hen live?", "student_response": "on a farm", "teacher_mark": "correct"}]))
    assert view["counted"] == 0
    assert await mastery(db, "Kit", "literacy") == {}
    assert await ledger(db, "Kit") == []


@pytest.mark.asyncio
async def test_with_mastery_profiles_off_only_the_work_record_is_written(db, monkeypatch):
    monkeypatch.setattr(settings, "retain_mastery_profiles", False)
    await confirm(db, "Ada", MATH)
    assert await mastery(db, "Ada", "mathematics") == {}
    assert len(await ledger(db, "Ada")) == 2


@pytest.mark.asyncio
async def test_deleting_the_student_removes_the_counted_mark(db):
    from services.student_deletion import delete_all_student_data

    await confirm(db, "Ada", MATH)
    counts = await delete_all_student_data(db, "Ada")
    assert counts["practice_evidence_marks"] == 1
    assert (await db.execute(select(PracticeEvidenceMark))).scalars().all() == []


def test_weight_is_below_a_live_observation():
    assert 0 < evidence.QUIZ_EVIDENCE_WEIGHT < 1
