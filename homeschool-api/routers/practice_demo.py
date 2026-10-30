"""The public demo's Practice Coach (docs/PRACTICE_COACH.md, "On the public demo").

Same reading, diagnosis and planning code as the real /practice routes
(services/practice/*, unchanged), with three differences that are the whole
point of this file:

* **Demo-code auth only** (`require_demo_practice`, policy action
  `demo.practice`). A family session cannot reach these routes and a demo
  code cannot reach /practice.
* **Nothing is written to the database.** The reading, the plan and the draft
  set are held by `services/practice/demo_store.py` in memory, per code, and
  go with the session. Photos are never held at all.
* **Always read by the demo's configured cloud provider, with a per-upload
  consent tick, and capped.** There is no local-model route. The upload
  quota is checked BEFORE any model call; consent is checked before the
  files are even decoded.

The prefix is `/practice-demo`, not `/practice/demo`: the real routes are
`/practice/{student_name}/...`, so a family whose child is named "Demo" would
otherwise be shadowed by these routes and refused.
"""
from fastapi import APIRouter, Depends, HTTPException, Request

from core.audit import AuditEvent, audit_from_request, log_event
from core.deps import require_demo_practice
from models.practice import (
    ApproveSetRequest,
    ConfirmAssessmentRequest,
    DemoReadPhotosRequest,
    ReadPhotosRequest,
)
from routers.practice import _view
from services.practice import demo_store, extract, pipeline
from services.practice.packs import available_packs

router = APIRouter(prefix="/practice-demo", tags=["practice-demo"])

_NOT_FOUND = "Record not found"


def _code(auth: dict) -> str:
    code = auth.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="This demo session has no code")
    return code


@router.get("/packs")
async def list_packs(auth: dict = Depends(require_demo_practice)) -> list[dict]:
    return available_packs()


@router.get("/reading-route")
async def get_reading_route(auth: dict = Depends(require_demo_practice)) -> dict:
    """Which provider would read an upload, and what is left of this code's
    allowance. Never mentions a local model: the demo does not use one."""
    return {
        "cloud_provider": extract.reading_route()["cloud_provider"],
        "uploads_remaining": demo_store.uploads_remaining(_code(auth)),
        "max_uploads": demo_store.MAX_UPLOADS_PER_CODE,
        "max_pages": demo_store.MAX_PAGES_PER_UPLOAD,
    }


async def _refuse_quota(request: Request, auth: dict, why: str) -> HTTPException:
    await log_event(
        AuditEvent.RATE_LIMITED,
        role=auth.get("role"),
        success=False,
        detail="demo_practice_quota" if why == "code" else "demo_practice_quota_global",
        **audit_from_request(request),
    )
    if why == "code":
        return HTTPException(status_code=429, detail={
            "demo_practice_quota": True,
            "message": "This demo reads up to "
                       f"{demo_store.MAX_UPLOADS_PER_CODE} quizzes per session, and you have used them.",
        })
    return HTTPException(status_code=429, detail={
        "demo_practice_quota": True,
        "message": "The demo is busy reading other quizzes right now. Please try again in a little while.",
    })


@router.post("/assessments/read", status_code=201)
async def read_assessment(
    req: DemoReadPhotosRequest,
    request: Request,
    auth: dict = Depends(require_demo_practice),
) -> dict:
    code = _code(auth)
    provider = extract.reading_route()["cloud_provider"]
    if provider is None:
        raise HTTPException(status_code=409, detail="This demo has no AI provider set up to read pages.")
    # Consent first: refused before anything is parsed, before an upload is
    # counted, and before any model is called.
    if not req.cloud_consent:
        raise HTTPException(status_code=409, detail={
            "consent_required": True,
            "provider": provider,
            "message": f"This page would be read by {provider}. Confirm to send it for this upload only.",
        })
    # Quota next, and still before the model: an over-quota upload costs a dict lookup.
    refused = demo_store.reserve_upload(code)
    if refused:
        raise await _refuse_quota(request, auth, refused)

    model_called = True
    try:
        assessment = await extract.read_pages(
            ReadPhotosRequest(subject=req.subject, pages=req.pages, route="cloud", cloud_consent=True),
            max_pages=demo_store.MAX_PAGES_PER_UPLOAD,
        )
    except extract.ConsentRequired as exc:  # unreachable here (consent is settled above), kept honest
        model_called = False
        raise HTTPException(status_code=409, detail={"consent_required": True, "provider": exc.provider})
    except extract.PhotoRejected as exc:
        model_called = False
        raise HTTPException(status_code=422, detail=str(exc))
    except extract.ReadingUnavailable as exc:
        model_called = False
        raise HTTPException(status_code=409, detail=str(exc))
    except (extract.ScannerUnavailable, extract.UploadBusy) as exc:
        model_called = False
        raise HTTPException(status_code=503, detail=str(exc))
    except extract.ReadingFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    finally:
        if not model_called:
            demo_store.release_upload(code)

    reading_id = demo_store.save_reading(code, assessment, "needs_review")
    view = _view(reading_id, "needs_review", assessment)
    view["uploads_remaining"] = demo_store.uploads_remaining(code)
    return view


@router.put("/assessments/{reading_id}")
async def confirm_assessment(
    reading_id: int,
    req: ConfirmAssessmentRequest,
    auth: dict = Depends(require_demo_practice),
) -> dict:
    code = _code(auth)
    if demo_store.load_reading(code, reading_id) is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if pipeline.get_pack(req.assessment.subject) is None:
        raise HTTPException(status_code=422, detail=f"No practice pack for {req.assessment.subject!r} yet.")
    status = "needs_review" if req.assessment.needs_parent() else "confirmed"
    demo_store.replace_reading(code, reading_id, req.assessment, status)
    return _view(reading_id, status, req.assessment)


@router.post("/assessments/{reading_id}/plan", status_code=201)
async def plan_practice(reading_id: int, auth: dict = Depends(require_demo_practice)) -> dict:
    code = _code(auth)
    found = demo_store.load_reading(code, reading_id)
    if found is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if found.status != "confirmed":
        raise HTTPException(status_code=409, detail="Confirm the reading before planning practice.")
    diagnosis = pipeline.diagnose(found.assessment)
    practice = pipeline.plan(diagnosis, found.assessment)
    summary = pipeline.parent_summary(found.assessment, diagnosis, practice)
    result = {
        "summary": summary,
        "diagnosis": diagnosis.model_dump(mode="json"),
        "practice_set": practice.model_dump(mode="json") if practice else None,
        "set_id": None,
        "status": None,
    }
    if practice is not None:
        try:
            result["set_id"] = demo_store.save_set(code, practice, summary)
        except demo_store.LimitReached as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        result["status"] = "draft"
    return result


def _draft(code: str, set_id: int):
    found = demo_store.load_set(code, set_id)
    if found is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if found.status != "draft":
        raise HTTPException(status_code=409, detail=f"This practice set is already {found.status}.")
    return found


@router.post("/sets/{set_id}/approve")
async def approve_set(
    set_id: int,
    req: ApproveSetRequest,
    auth: dict = Depends(require_demo_practice),
) -> dict:
    code = _code(auth)
    _draft(code, set_id)
    demo_store.decide_set(code, set_id, "approved", req.practice_set)
    return {"id": set_id, "status": "approved"}


@router.post("/sets/{set_id}/discard")
async def discard_set(set_id: int, auth: dict = Depends(require_demo_practice)) -> dict:
    code = _code(auth)
    _draft(code, set_id)
    demo_store.decide_set(code, set_id, "discarded")
    return {"id": set_id, "status": "discarded"}
