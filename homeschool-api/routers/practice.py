"""Practice Coach routes (docs/PRACTICE_COACH.md). Parent-only, every one.

Flow: read photos (or type the quiz in) -> parent confirms the reading ->
diagnose and draft practice -> parent approves, edits, or discards. Nothing
here is reachable by a child, an educator, or a demo visitor, and the child's
delivery route (PR 3) will only ever return approved sets.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.deps import require_parent
from models.practice import (
    ApproveSetRequest,
    ConfirmAssessmentRequest,
    ReadPhotosRequest,
    teacher_mark_count,
)
from services.practice import extract, pipeline, store
from services.practice.packs import available_packs

router = APIRouter(prefix="/practice", tags=["practice"])

_NOT_FOUND = "Record not found"


def _view(record_id: int, status: str, assessment) -> dict:
    return {
        "id": record_id,
        "status": status,
        "assessment": assessment.model_dump(mode="json"),
        "ask_parent": assessment.needs_parent(),
        "teacher_mark_count": teacher_mark_count(assessment),
    }


@router.get("/packs")
async def list_packs(auth: dict = Depends(require_parent)) -> list[dict]:
    return available_packs()


@router.get("/reading-route")
async def get_reading_route(auth: dict = Depends(require_parent)) -> dict:
    """Where photos would be read, shown to the parent before any upload."""
    return extract.reading_route()


@router.post("/{student_name}/assessments/read", status_code=201)
async def read_assessment(
    student_name: str,
    req: ReadPhotosRequest,
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        assessment = await extract.read_pages(req)
    except extract.ConsentRequired as exc:
        raise HTTPException(status_code=409, detail={
            "consent_required": True,
            "provider": exc.provider,
            "message": f"These photos would be read by {exc.provider}. Confirm to send them for this upload only.",
        })
    except extract.PhotoRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except extract.ReadingUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except extract.ReadingFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    try:
        record_id = await store.save_assessment(db, student_name, assessment, "needs_review")
    except LookupError:
        raise HTTPException(status_code=404, detail="Student not found")
    return _view(record_id, "needs_review", assessment)


@router.post("/{student_name}/assessments", status_code=201)
async def enter_assessment(
    student_name: str,
    req: ConfirmAssessmentRequest,
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Type a quiz in by hand instead of photographing it."""
    if pipeline.get_pack(req.assessment.subject) is None:
        raise HTTPException(status_code=422, detail=f"No practice pack for {req.assessment.subject!r} yet.")
    status = "needs_review" if req.assessment.needs_parent() else "confirmed"
    try:
        record_id = await store.save_assessment(db, student_name, req.assessment, status)
    except LookupError:
        raise HTTPException(status_code=404, detail="Student not found")
    return _view(record_id, status, req.assessment)


@router.put("/{student_name}/assessments/{record_id}")
async def confirm_assessment(
    student_name: str,
    record_id: int,
    req: ConfirmAssessmentRequest,
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The parent's corrected reading. Confirming means every flagged field
    has been settled: an item still flagged keeps the record in review."""
    found = await store.load_assessment(db, student_name, record_id)
    if found is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    row, _ = found
    status = "needs_review" if req.assessment.needs_parent() else "confirmed"
    await store.replace_assessment(db, row, req.assessment, status)
    return _view(record_id, status, req.assessment)


@router.post("/{student_name}/assessments/{record_id}/plan", status_code=201)
async def plan_practice(
    student_name: str,
    record_id: int,
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    found = await store.load_assessment(db, student_name, record_id)
    if found is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    row, assessment = found
    if row.status != "confirmed":
        raise HTTPException(status_code=409, detail="Confirm the reading before planning practice.")
    diagnosis = pipeline.diagnose(assessment)
    practice = pipeline.plan(diagnosis, assessment)
    summary = pipeline.parent_summary(assessment, diagnosis, practice)
    result = {
        "summary": summary,
        "diagnosis": diagnosis.model_dump(mode="json"),
        "practice_set": practice.model_dump(mode="json") if practice else None,
        "set_id": None,
        "status": None,
    }
    if practice is not None:
        result["set_id"] = await store.save_set(db, student_name, record_id, practice, summary)
        result["status"] = "draft"
    return result


@router.get("/{student_name}/sets")
async def get_sets(
    student_name: str,
    status: str | None = Query(default=None, pattern="^(draft|approved|discarded)$"),
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await store.list_sets(db, student_name, status)


async def _draft(db, student_name: str, set_id: int):
    found = await store.load_set(db, student_name, set_id)
    if found is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    row, detail = found
    if row.status != "draft":
        raise HTTPException(status_code=409, detail=f"This practice set is already {row.status}.")
    return row, detail


@router.post("/{student_name}/sets/{set_id}/approve")
async def approve_set(
    student_name: str,
    set_id: int,
    req: ApproveSetRequest,
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row, detail = await _draft(db, student_name, set_id)
    await store.decide_set(db, row, "approved", req.practice_set, detail.get("summary", ""))
    return {"id": set_id, "status": "approved"}


@router.post("/{student_name}/sets/{set_id}/discard")
async def discard_set(
    student_name: str,
    set_id: int,
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row, _ = await _draft(db, student_name, set_id)
    await store.decide_set(db, row, "discarded")
    return {"id": set_id, "status": "discarded"}
