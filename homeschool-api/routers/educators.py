"""Classical educator desk: only assigned learner data, no system administration.

Separate from /diagnostic's parent-only endpoints; no change to the
parent's existing protections. Instructor actions are checked per student
in SQL, even if a browser supplies an arbitrary path parameter.
"""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.config import settings
from core.deps import require_educator, require_elevated_parent, require_parent
from models.schemas import SessionConfig
from services.assessment_interop import EducatorAssessmentSubmission
from services.educator_access import (
    assign_class_roster, authenticate_educator, disable_educator,
    live_educator, locuto_pod_plan, provision_educator,
    require_assignment, roster_configs,
)

router = APIRouter(prefix="/educators", tags=["educators"])


class EducatorProvisionRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=14, max_length=256)


class ClassRosterRequest(BaseModel):
    # Technical size bound only, not a licensing or school-class maximum.
    # The negotiated institution/child limit is enforced from the signed
    # Bede entitlement when roster assignments are committed.
    configs: list[SessionConfig] = Field(min_length=1, max_length=1000)


@router.get("/accounts")
async def list_authorized_instructors(
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    from sqlalchemy import func, select
    from core.database import ClassicalEducator, EducatorRosterAssignment
    counts = (await db.execute(
        select(EducatorRosterAssignment.educator_id,
               func.count(EducatorRosterAssignment.student_name))
        .group_by(EducatorRosterAssignment.educator_id)
    )).all()
    count_map = dict(counts)
    instructors = (await db.execute(
        select(ClassicalEducator).order_by(ClassicalEducator.username)
    )).scalars().all()
    return [{"id": e.id, "username": e.username, "enabled": e.enabled,
             "learner_count": count_map.get(e.id, 0)} for e in instructors]


@router.get("/me/assessment-frameworks")
async def my_frameworks(auth: dict = Depends(require_educator)) -> list[dict]:
    from services.assessment_interop import frameworks_catalog
    return frameworks_catalog()


@router.post("/accounts", status_code=201)
async def add_educator(
    payload: EducatorProvisionRequest,
    response: Response,
    auth: dict = Depends(require_elevated_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Elevated parent provisions password+TOTP once; no mail or shared secret logs."""
    if not settings.educator_pilot_enabled:
        raise HTTPException(status_code=409, detail="Enable the educator pilot on this instance first")
    try:
        result = await provision_educator(db, payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    response.headers["Cache-Control"] = "no-store"
    return result


@router.put("/accounts/{educator_id}/roster")
async def set_class_roster(
    educator_id: str,
    payload: ClassRosterRequest,
    auth: dict = Depends(require_elevated_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Only elevated parent/operator grants assignments or creates a pupil."""
    if not settings.educator_pilot_enabled:
        raise HTTPException(status_code=409, detail="Enable the educator pilot on this instance first")
    try:
        return await assign_class_roster(db, educator_id, payload.configs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/accounts/{educator_id}/disable", status_code=204)
async def revoke_educator(
    educator_id: str,
    auth: dict = Depends(require_elevated_parent),
    db: AsyncSession = Depends(get_db),
) -> None:
    await disable_educator(db, educator_id)


@router.get("/me/roster", response_model=list[SessionConfig])
async def my_class_roster(
    auth: dict = Depends(require_educator),
    db: AsyncSession = Depends(get_db),
) -> list[SessionConfig]:
    return await roster_configs(db, auth)


@router.get("/me/locuto-capacity")
async def my_locuto_capacity(
    auth: dict = Depends(require_educator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    configs = await roster_configs(db, auth)
    return locuto_pod_plan([cfg.student_name for cfg in configs])


@router.get("/me/students/{student_name}/config", response_model=SessionConfig)
async def my_student_config(
    student_name: str,
    auth: dict = Depends(require_educator),
    db: AsyncSession = Depends(get_db),
) -> SessionConfig:
    from core.database import StudentConfig
    from core.encryption import decrypt_json
    from core import student_keys
    from services.educator_access import _config_aad
    await require_assignment(db, auth, student_name)
    row = await db.get(StudentConfig, student_name)
    if row is None:
        raise HTTPException(status_code=404, detail="Learner not assigned")
    return SessionConfig(**decrypt_json(
        row.config_enc, _config_aad(student_name),
        await student_keys.get_existing(db, student_name),
    ))


@router.get("/me/students/{student_name}/assessments")
async def my_assessments(
    student_name: str,
    limit: int = Query(default=100, ge=1, le=100),
    auth: dict = Depends(require_educator),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    from services.assessment_interop import list_assessments
    await require_assignment(db, auth, student_name)
    return await list_assessments(db, student_name, limit=limit)


@router.post("/me/students/{student_name}/assessments", status_code=201)
async def submit_independently_administered_result(
    student_name: str,
    payload: EducatorAssessmentSubmission,
    auth: dict = Depends(require_educator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Only transcribe external DIBELS results; Bede does not administer tests."""
    from services.assessment_interop import record_assessment
    await require_assignment(db, auth, student_name)
    try:
        return await record_assessment(db, student_name, payload)
    except LookupError:
        raise HTTPException(status_code=404, detail="Learner not assigned")


@router.get("/me/students/{student_name}/activity")
async def my_student_work(
    student_name: str,
    since_days: int = Query(default=90, ge=1, le=365),
    auth: dict = Depends(require_educator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from services.diagnostic.activity import summarize
    await require_assignment(db, auth, student_name)
    return await summarize(db, student_name, since_days)


@router.get("/me/students/{student_name}/diagnostic")
async def my_student_diagnostic(
    student_name: str,
    subject_area: str = "mathematics",
    auth: dict = Depends(require_educator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from routers.diagnostic import _SUMMARY_BUILDERS
    await require_assignment(db, auth, student_name)
    builder = _SUMMARY_BUILDERS.get(subject_area)
    if builder is None:
        raise HTTPException(status_code=404, detail="No academic evidence for this subject")
    data = await builder(db, student_name)
    if data is None:
        raise HTTPException(status_code=404, detail="No academic evidence for this subject")
    return {"source": "bede_inferred_mastery_not_dibels", "data": data}


def periodic_dibels_series(records: list[dict]) -> dict:
    """Trend *reporting*; NEVER attribute improvement to Bede tutoring.

    A result with unreviewed historical provenance is visible but explicitly
    excluded from numeric comparison. Compare only same measure + grade +
    score unit; an academic year change is not a valid direct score delta.
    """
    entries = [r for r in records if r["framework"] == "dibels8"]
    entries.sort(key=lambda r: (r["assessed_on"], r["id"]))
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for item in entries:
        grade = item.get("assessed_grade")
        unit = item.get("score_unit")
        if not grade or item.get("quality_flags"):
            continue
        groups[(item["measure"], grade, unit)].append(item)
    trends = []
    for (measure, grade, unit), observations in sorted(groups.items()):
        previous = None
        points = []
        for item in observations:
            score = item["score"]
            points.append({
                "date": item["assessed_on"],
                "assessment_window": item.get("assessment_window"),
                "score_as_reported": score,
                "unit": unit,
                "risk_category_as_reported": item.get("reported_band"),
                "difference_from_previous_same_grade_measure": (
                    round(score - previous, 3) if previous is not None else None
                ),
                "source": item["source_name"],
                "record_id": item["id"],
            })
            previous = score
        trends.append({
            "measure": measure, "assessed_grade": grade, "unit": unit,
            "points": points,
            "same_instrument_same_grade_only": True,
        })
    return {
        "source": "independently_administered_educator_entered_dibels8",
        "data_quality": "unverified_reports_review_source_before_interpretation",
        "cannot_establish_causal_learning_efficacy": True,
        "automatic_benchmark_scoring": False,
        "total_dibels_records": len(entries),
        "records_excluded_from_comparison": len(entries) - sum(
            len(series["points"]) for series in trends
        ),
        "series": trends,
    }


@router.get("/me/students/{student_name}/dibels-progress")
async def my_periodic_dibels(
    student_name: str,
    auth: dict = Depends(require_educator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from services.assessment_interop import list_assessments
    await require_assignment(db, auth, student_name)
    return periodic_dibels_series(await list_assessments(db, student_name, limit=100))
