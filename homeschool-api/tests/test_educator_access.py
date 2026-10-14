"""Real SQLite educator/MFA, roster isolation and DIBELS longitudinal evidence.

No external authenticator, cloud account, child data or test booklets.
"""
from datetime import datetime, timedelta, timezone

import pyotp
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.database import Base
from core.encryption import initialize_encryption
from core.policy import Subject as PolicySubject, decide
from models.schemas import SessionConfig, GradeStage, Subject
from routers.educators import (
    my_class_roster, my_periodic_dibels, my_student_config,
    my_assessments, periodic_dibels_series,
)
from services.assessment_interop import EducatorAssessmentSubmission, record_assessment
from services.educator_access import (
    assign_class_roster, authenticate_educator,
    disable_educator, live_educator, locuto_pod_plan, provision_educator,
    require_assignment, roster_configs,
)

PASSWORD = "educator-tests-only-strong-passphrase"


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await initialize_encryption(settings.master_secret, session)
        yield session
    await engine.dispose()


def student(name, grade="4"):
    return SessionConfig(
        student_name=name, grade=grade, grade_stage=GradeStage.core_mastery,
        subjects=[Subject.mathematics, Subject.living_books],
        current_unit="Fractions",
    )


@pytest.mark.asyncio
async def test_authenticated_teacher_cannot_grant_self_learner_or_administer_system(db):
    issued = await provision_educator(db, "instructor.one", PASSWORD)
    code = pyotp.TOTP(issued["totp_secret"]).now()
    token = await authenticate_educator(db, "INSTRUCTOR.ONE", PASSWORD, code)
    assert token["role"] == "educator"
    assert (await live_educator(db, token)).username == "instructor.one"
    assert not decide(PolicySubject.from_token(token), "admin.manage").allowed
    assert not decide(PolicySubject.from_token(token), "admin.privileged").allowed
    assert not decide(PolicySubject.from_token(token), "family.data.read").allowed
    assert decide(PolicySubject.from_token(token), "educator.roster").allowed
    # One-time TOTP cannot be replayed even inside its otherwise-valid window.
    assert await authenticate_educator(db, "instructor.one", PASSWORD, code) is None
    with pytest.raises(HTTPException) as exc:
        await require_assignment(db, token, "Unknown")
    assert exc.value.status_code == 404
    await disable_educator(db, issued["id"])
    with pytest.raises(HTTPException) as exc:
        await live_educator(db, token)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_teacher_scope_and_existing_parent_config_untouched(db):
    a = await provision_educator(db, "teacher.a", PASSWORD)
    b = await provision_educator(db, "teacher.b", PASSWORD)
    first = student("Alice")
    second = student("Bob")
    out = await assign_class_roster(db, a["id"], [first])
    assert out["learner_count"] == 1
    assert out["new_learner_count"] == 1
    await assign_class_roster(db, b["id"], [second])
    token_a = {"role": "educator", "sub": a["id"], "ev": 1}
    token_b = {"role": "educator", "sub": b["id"], "ev": 1}
    assert [c.student_name for c in await roster_configs(db, token_a)] == ["Alice"]
    assert [c.student_name for c in await roster_configs(db, token_b)] == ["Bob"]
    assert (await my_student_config("Alice", auth=token_a, db=db)).current_unit == "Fractions"
    with pytest.raises(HTTPException) as exc:
        await my_student_config("Bob", auth=token_a, db=db)
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException):
        await my_assessments("Bob", auth=token_a, db=db)
    # Parent repeats import with a different curriculum: an import can
    # assign an existing learner, but never overwrite their authorized plan.
    fake_change = first.model_copy(update={"current_unit": "UNAPPROVED CHANGE"})
    await assign_class_roster(db, a["id"], [fake_change])
    assert (await my_student_config("Alice", auth=token_a, db=db)).current_unit == "Fractions"


@pytest.mark.asyncio
async def test_educator_mfa_login_locks_out_and_does_not_issue_without_second_factor(db):
    account = await provision_educator(db, "teacher.lock", PASSWORD)
    for _ in range(5):
        assert await authenticate_educator(
            db, "teacher.lock", "incorrect", "000000"
        ) is None
    code = pyotp.TOTP(account["totp_secret"]).now()
    assert await authenticate_educator(db, "teacher.lock", PASSWORD, code) is None
    assert await authenticate_educator(db, "unlisted", PASSWORD, code) is None


def test_locuto_roster_capacity_not_a_messaging_connector():
    for count in [1, 2, 9, 10, 11, 24, 90, 120, 250]:
        data = locuto_pod_plan([f"student-{i}" for i in range(count)])
        assert data["roster_or_student_data_transferred"] is False
        assert data["active_group_messages_enabled"] is False
        assert data["integration_status"] == "planning_only_not_connected"
        if count == 1:
            assert not data["groups"]
        else:
            assert sum(g["learner_count"] for g in data["groups"]) == count
            assert all(3 <= g["member_count_including_educator"] <= 10
                       for g in data["groups"])


def test_periodic_dibels_comparison_is_within_grade_measure_unit_only():
    def point(id, day, score, measure="ORF_WC", grade="4", flags=()):
        return {
            "id": id, "framework": "dibels8",
            "assessed_on": day, "score": score,
            "measure": measure, "score_unit": "correct_per_minute",
            "assessed_grade": grade, "assessment_window": "middle_of_year",
            "reported_band": "not_reported",
            "source_name": "Independent educator report",
            "quality_flags": list(flags),
        }
    series = periodic_dibels_series([
        point(1, "2026-01-01", 80),
        point(2, "2026-03-01", 94),
        point(3, "2026-05-01", 104, grade="5"),
        point(4, "2026-06-01", 62, measure="PSF"),
        point(5, "2025-10-01", 70, flags=["legacy_benchmark_label"]),
        {"framework": "classical", "id": 100},
    ])
    assert series["total_dibels_records"] == 5
    assert series["records_excluded_from_comparison"] == 1
    assert series["cannot_establish_causal_learning_efficacy"] is True
    fourth_grade_orf = next(s for s in series["series"] if
                            s["measure"] == "ORF_WC" and s["assessed_grade"] == "4")
    assert len(fourth_grade_orf["points"]) == 2
    assert fourth_grade_orf["points"][0]["difference_from_previous_same_grade_measure"] is None
    assert fourth_grade_orf["points"][1]["difference_from_previous_same_grade_measure"] == 14
    fifth_grade_orf = next(s for s in series["series"] if
                           s["measure"] == "ORF_WC" and s["assessed_grade"] == "5")
    assert fifth_grade_orf["points"][0]["difference_from_previous_same_grade_measure"] is None


@pytest.mark.asyncio
async def test_periodic_dibels_read_guard_and_real_encrypted_reports(db):
    teacher = await provision_educator(db, "teacher.dibels", PASSWORD)
    await assign_class_roster(db, teacher["id"], [student("Alice")])
    token = {"role": "educator", "sub": teacher["id"], "ev": 1}
    for day, score in [("2026-01-10", 70), ("2026-10-10", 95)]:
        await record_assessment(db, "Alice", EducatorAssessmentSubmission(
            framework="dibels8", measure="ORF_WC", assessed_on=day,
            source_name="Synthetic independent report", score=score,
            score_unit="correct_per_minute", assessed_grade="4",
            assessment_window="middle_of_year", reported_band="not_reported",
        ))
    report = await my_periodic_dibels("Alice", auth=token, db=db)
    assert report["total_dibels_records"] == 2
    assert report["series"][0]["points"][1]["difference_from_previous_same_grade_measure"] == 25
    with pytest.raises(HTTPException) as exc:
        await my_periodic_dibels("Bob", auth=token, db=db)
    assert exc.value.status_code == 404
