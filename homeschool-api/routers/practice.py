"""Practice Coach routes (docs/PRACTICE_COACH.md).

Flow: read photos (or type the quiz in) -> parent confirms the reading ->
diagnose and draft practice -> parent approves, edits, or discards. Each
route has its own guard, pinned by
test_every_practice_route_uses_its_scoped_authorization_guard: parent routes
by default, `/practice/educator/*` for teachers (quiz drafting and teacher
quizzes with answer keys, local model only, nothing stored), `/practice/demo/*`
for the demo, and the child's delivery route only ever returns approved sets.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.deps import (
    require_demo_practice_preview,
    require_educator,
    require_family_data_write,
    require_learner_access,
    require_parent,
    require_real_user,
)
from core import consent
from models.practice import (
    MAX_QUIZ_QUESTIONS,
    GenerateQuizRequest,
    ApproveSetRequest,
    ConfirmAssessmentRequest,
    PracticeOutcomeRequest,
    PracticeSet,
    QuizSourceRequest,
    ExtractQuizRequest,
    FinalizeResultsRequest,
    ReadPhotosRequest,
    ScoreSubmissionRequest,
    TeacherQuizRequest,
    teacher_mark_count,
)
from services.practice import extract, generate, pipeline, progress, store, teacher_quiz
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


def _quiz_options() -> dict:
    return {
        "subjects": generate.quiz_subjects(),
        "grades": ["K", "1", "2", "3", "4", "5", "6", "7", "8"],
        "kinds": list(generate.KIND_GUIDANCE),
        "levels": list(generate.LEVEL_GUIDANCE),
        "max_questions": MAX_QUIZ_QUESTIONS,
        "route": extract.reading_route(),
    }


async def _draft_quiz(req: GenerateQuizRequest, local_only: bool = False, before_call=None,
                      auth: dict | None = None) -> dict:
    reporter = progress.reporter(progress.owner_of(auth or {}), req.progress_id) if auth else None
    try:
        quiz, report = await generate.generate(req, local_only=local_only, before_call=before_call, report=reporter)
    except generate.QuizRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except extract.ConsentRequired as exc:
        raise HTTPException(status_code=409, detail={
            "consent_required": True,
            "provider": exc.provider,
            "message": f"This would be sent to {exc.provider}. Tick the box to agree.",
        })
    except extract.PhotoRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except extract.ReadingUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (extract.ScannerUnavailable, extract.UploadBusy) as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except generate.QuizFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"quiz": quiz.model_dump(mode="json"), "report": report}


@router.get("/quiz-options")
async def get_quiz_options(auth: dict = Depends(require_parent)) -> dict:
    return _quiz_options()


async def _copy_source(req: QuizSourceRequest, local_only: bool = False, before_call=None, auth: dict | None = None) -> dict:
    """One part of a long quiz source, copied out as text. Nothing is stored."""
    report = progress.reporter(progress.owner_of(auth or {}), req.progress_id) if auth else None
    try:
        text, pages_read = await generate.transcribe_source(
            req, local_only=local_only, before_call=before_call, report=report)
    except generate.QuizRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except extract.ConsentRequired as exc:
        raise HTTPException(status_code=409, detail={
            "consent_required": True,
            "provider": exc.provider,
            "message": f"This would be sent to {exc.provider}. Tick the box to agree.",
        })
    except extract.PhotoRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except extract.ReadingUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (extract.ScannerUnavailable, extract.UploadBusy) as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except generate.QuizFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"text": text, "pages_read": pages_read}


@router.post("/{student_name}/quizzes/source")
async def copy_quiz_source(
    student_name: str,
    req: QuizSourceRequest,
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """A long quiz source is sent in parts; each part is copied out as text."""
    await consent.require_collection(db, student_name)
    return await _copy_source(req, auth=auth)


def _progress_view(auth: dict, progress_id: str) -> dict:
    if not progress.valid_id(progress_id):
        raise HTTPException(status_code=404, detail="Unknown progress")
    found = progress.read(progress.owner_of(auth), progress_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Unknown progress")
    return found


@router.get("/progress/{progress_id}")
async def get_progress(progress_id: str, auth: dict = Depends(require_parent)) -> dict:
    """How far a reading in progress has got: pages read of the total."""
    return _progress_view(auth, progress_id)


@router.get("/educator/progress/{progress_id}")
async def educator_progress(progress_id: str, auth: dict = Depends(require_educator)) -> dict:
    return _progress_view(auth, progress_id)


@router.post("/educator/quiz/source")
async def educator_copy_quiz_source(
    req: QuizSourceRequest,
    auth: dict = Depends(require_educator),
) -> dict:
    if req.route == "cloud":
        raise HTTPException(status_code=422, detail="Teacher quizzes are drafted on the school's own AI model.")
    return await _copy_source(req, local_only=True, auth=auth)


@router.post("/{student_name}/quizzes/generate")
async def generate_quiz(
    student_name: str,
    req: GenerateQuizRequest,
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Draft a quiz or exam for this student. Nothing is stored."""
    await consent.require_collection(db, student_name)
    return await _draft_quiz(req, auth=auth)


@router.get("/educator/quiz-options")
async def educator_quiz_options(auth: dict = Depends(require_educator)) -> dict:
    options = _quiz_options()
    # Teachers draft on the school's own model only, so no cloud consent is offered.
    options["route"] = {
        "local_available": options["route"]["local_available"],
        "cloud_provider": None,
        "draft_provider": None,
    }
    return options


@router.post("/educator/quiz/generate")
async def educator_generate_quiz(
    req: GenerateQuizRequest,
    auth: dict = Depends(require_educator),
) -> dict:
    """A teacher drafts a quiz or exam for a class. Local model only, because
    a teacher's upload can hold students' work; nothing is stored, and no
    learner record is read or written."""
    if req.route == "cloud":
        raise HTTPException(status_code=422, detail="Teacher quizzes are drafted on the school's own AI model.")
    return await _draft_quiz(req, local_only=True, auth=auth)


# ── Teacher quizzes with reviewable answer keys (services/practice/teacher_quiz.py)
#
# Local model only, nothing stored, no learner named. A teacher keeps the
# quiz as a file they export; a student's completed work is read, scored
# against the approved key in code, and handed back for the teacher to
# approve or correct. Results are for the teacher's own printout.

def _teacher_quiz_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, teacher_quiz.QuizNotApproved):
        return HTTPException(status_code=422, detail={
            "problems": exc.problems,
            "message": "Settle every question marked for review before using this quiz.",
        })
    if isinstance(exc, teacher_quiz.UploadConsentRequired):
        return HTTPException(status_code=409, detail={
            "consent_required": True,
            "provider": teacher_quiz.LOCAL_PROVIDER,
            "message": "These pages are read on the school's own AI model and not stored. Tick the box to agree for this upload.",
        })
    if isinstance(exc, teacher_quiz.ResultsNotSettled):
        return HTTPException(status_code=409, detail={
            "unsettled": exc.numbers,
            "message": "Some results still need your review before they count.",
        })
    if isinstance(exc, (generate.QuizRefused, extract.PhotoRejected)):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, extract.ReadingUnavailable):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, (extract.ScannerUnavailable, extract.UploadBusy)):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, extract.ReadingFailed):
        return HTTPException(status_code=502, detail=str(exc))
    raise exc


_TEACHER_QUIZ_ERRORS = (
    teacher_quiz.QuizNotApproved, teacher_quiz.UploadConsentRequired, teacher_quiz.ResultsNotSettled,
    generate.QuizRefused, extract.PhotoRejected, extract.ReadingUnavailable, extract.ScannerUnavailable,
    extract.UploadBusy, extract.ReadingFailed,
)


@router.post("/educator/teacher-quiz/review")
async def review_teacher_quiz(req: TeacherQuizRequest, auth: dict = Depends(require_educator)) -> dict:
    """What still needs the teacher before this quiz can be approved. Used
    for a quiz written on screen and for one imported from a file."""
    return {"quiz": req.quiz.model_dump(mode="json"), "problems": teacher_quiz.approval_problems(req.quiz)}


@router.post("/educator/teacher-quiz/approve")
async def approve_teacher_quiz(req: TeacherQuizRequest, auth: dict = Depends(require_educator)) -> dict:
    try:
        quiz = teacher_quiz.approve(req.quiz)
    except _TEACHER_QUIZ_ERRORS as exc:
        raise _teacher_quiz_errors(exc)
    return {"quiz": quiz.model_dump(mode="json"), "problems": []}


@router.post("/educator/teacher-quiz/extract")
async def extract_teacher_quiz(req: ExtractQuizRequest, auth: dict = Depends(require_educator)) -> dict:
    """Read a quiz the teacher already has. Nothing in the result is approved."""
    try:
        quiz = await teacher_quiz.extract_quiz(req)
    except _TEACHER_QUIZ_ERRORS as exc:
        raise _teacher_quiz_errors(exc)
    return {"quiz": quiz.model_dump(mode="json"), "problems": teacher_quiz.approval_problems(quiz)}


@router.post("/educator/teacher-quiz/score")
async def score_teacher_quiz(req: ScoreSubmissionRequest, auth: dict = Depends(require_educator)) -> dict:
    """Propose readings and scores for one student's completed quiz. Nothing
    counts until the teacher settles it, and nothing is stored."""
    try:
        results = await teacher_quiz.score_submission(req.quiz, req.pages, req.responses, req.upload_consent)
    except _TEACHER_QUIZ_ERRORS as exc:
        raise _teacher_quiz_errors(exc)
    return {
        "results": [r.model_dump(mode="json") for r in results],
        "possible": sum(q.points for q in req.quiz.questions),
        "read_by": teacher_quiz.LOCAL_PROVIDER if req.pages else None,
    }


@router.post("/educator/teacher-quiz/finalize")
async def finalize_teacher_quiz(req: FinalizeResultsRequest, auth: dict = Depends(require_educator)) -> dict:
    try:
        return teacher_quiz.finalize(req)
    except _TEACHER_QUIZ_ERRORS as exc:
        raise _teacher_quiz_errors(exc)


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
    await consent.require_collection(db, student_name)
    if req.continues is not None:
        raise HTTPException(status_code=422, detail="Continue an upload by its saved record, not by sending its reading.")
    earlier = None
    if req.continues_record is not None:
        earlier = await store.load_assessment(db, student_name, req.continues_record)
        if earlier is None or earlier[0].status != "needs_review" or earlier[1].subject != req.subject:
            raise HTTPException(status_code=404, detail="Assessment not found")
    try:
        assessment, pages_read = await extract.read_pages_counted(
            req, continues=earlier[1] if earlier else None,
            report=progress.reporter(progress.owner_of(auth), req.progress_id))
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
    except (extract.ScannerUnavailable, extract.UploadBusy) as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except extract.ReadingFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    if earlier is not None:
        # A later part of the same upload: the saved reading grows; it is still
        # reviewed as one worksheet.
        await store.replace_assessment(db, earlier[0], assessment, "needs_review")
        return {**_view(earlier[0].id, "needs_review", assessment), "pages_read": pages_read}
    try:
        record_id = await store.save_assessment(db, student_name, assessment, "needs_review")
    except LookupError:
        raise HTTPException(status_code=404, detail="Student not found")
    return {**_view(record_id, "needs_review", assessment), "pages_read": pages_read}


@router.post("/{student_name}/assessments", status_code=201)
async def enter_assessment(
    student_name: str,
    req: ConfirmAssessmentRequest,
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Type a quiz in by hand instead of photographing it."""
    await consent.require_collection(db, student_name)
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
    await consent.require_collection(db, student_name)
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
    await consent.require_collection(db, student_name)
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


@router.get("/{student_name}/delivery")
async def get_delivery_sets(
    student_name: str,
    auth: dict = Depends(require_real_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return only approved practice prompts, never answer keys or diagnosis."""
    await require_learner_access(auth, student_name, db)
    await consent.require_collection(db, student_name)
    approved = await store.list_sets(db, student_name, "approved")
    out = []
    for saved in approved:
        try:
            practice = PracticeSet.model_validate(saved["practice_set"])
        except Exception:
            continue
        out.append({
            "id": saved["id"],
            "items": [
                {"index": index, "prompt": item.prompt, "hint": item.hint,
                 "diagram": item.diagram.model_dump(mode="json") if item.diagram else None}
                for index, item in enumerate(practice.items)
            ],
            "completed_indices": sorted(
                int(index) for index in saved.get("observed_outcomes", {})
                if str(index).isdigit() and 0 <= int(index) < len(practice.items)
            ),
        })
    return out


@router.post("/{student_name}/sets/{set_id}/outcomes")
async def record_practice_outcome(
    student_name: str,
    set_id: int,
    req: PracticeOutcomeRequest,
    auth: dict = Depends(require_family_data_write),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await require_learner_access(auth, student_name, db)
    await consent.require_collection(db, student_name)
    result = await store.record_outcome(db, student_name, set_id, req.item_index, req.response)
    if result == "not_found":
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if result == "not_approved":
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if result == "conflict":
        raise HTTPException(status_code=409, detail="A response is already recorded for this item.")
    return {"recorded": True, "already_recorded": result == "already_recorded"}


@router.get("/demo/packs")
async def demo_list_packs(auth: dict = Depends(require_demo_practice_preview)) -> list[dict]:
    return available_packs()


@router.get("/demo/reading-route")
async def demo_reading_route(auth: dict = Depends(require_demo_practice_preview)) -> dict:
    return extract.reading_route()


@router.get("/demo/quiz-options")
async def demo_quiz_options(auth: dict = Depends(require_demo_practice_preview)) -> dict:
    return _quiz_options()


@router.post("/demo/quiz/generate")
async def demo_generate_quiz(
    req: GenerateQuizRequest,
    auth: dict = Depends(require_demo_practice_preview),
) -> dict:
    """Draft a quiz in the demo. Counts against the demo's message quota,
    since each draft is a model call; nothing is stored."""
    from core.demo_code_session import has_message_quota, record_message

    code = auth.get("code") or ""
    if not await has_message_quota(code):
        raise HTTPException(status_code=429, detail="This demo has reached its limit. Start a new demo to keep going.")
    # A draft is two model calls: writing the quiz, then checking its answers.
    await record_message(code)
    await record_message(code)

    async def charge() -> None:
        # A long source is copied out a group of pages at a time; each is a call.
        if not await has_message_quota(code):
            raise HTTPException(status_code=429, detail="This demo has reached its limit. Start a new demo to keep going.")
        await record_message(code)

    return await _draft_quiz(req, before_call=charge, auth=auth)


@router.post("/demo/quiz/source")
async def demo_copy_quiz_source(
    req: QuizSourceRequest,
    auth: dict = Depends(require_demo_practice_preview),
) -> dict:
    """One part of a long demo quiz source; each group of pages is one message."""
    from core.demo_code_session import has_message_quota, record_message

    code = auth.get("code") or ""

    async def charge() -> None:
        if not await has_message_quota(code):
            raise HTTPException(status_code=429, detail="This demo has reached its limit. Start a new demo to keep going.")
        await record_message(code)

    return await _copy_source(req, before_call=charge, auth=auth)


@router.get("/demo/progress/{progress_id}")
async def demo_progress(progress_id: str, auth: dict = Depends(require_demo_practice_preview)) -> dict:
    return _progress_view(auth, progress_id)


@router.post("/demo/read")
async def demo_read_assessment(
    req: ReadPhotosRequest,
    auth: dict = Depends(require_demo_practice_preview),
) -> dict:
    """Read demo uploads without persisting the image or assessment.

    Each group of pages is one model call and counts as one demo message, so
    a long upload uses the visitor's allowance as it really runs."""
    from core.demo_code_session import has_message_quota, record_message

    if req.continues_record is not None:
        raise HTTPException(status_code=422, detail="The demo stores nothing, so there is no saved record to continue.")
    code = auth.get("code") or ""

    async def charge() -> None:
        if not await has_message_quota(code):
            raise HTTPException(status_code=429, detail="This demo has reached its limit. Start a new demo to keep going.")
        await record_message(code)

    try:
        assessment, pages_read = await extract.read_pages_counted(
            req, before_call=charge, continues=req.continues,
            report=progress.reporter(progress.owner_of(auth), req.progress_id))
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
    except (extract.ScannerUnavailable, extract.UploadBusy) as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except extract.ReadingFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {**_view(0, "needs_review" if assessment.needs_parent() else "confirmed", assessment),
            "pages_read": pages_read}


@router.post("/demo/plan")
async def demo_plan_practice(
    req: ConfirmAssessmentRequest,
    auth: dict = Depends(require_demo_practice_preview),
) -> dict:
    if pipeline.get_pack(req.assessment.subject) is None:
        raise HTTPException(status_code=422, detail=f"No practice pack for {req.assessment.subject!r} yet.")
    if req.assessment.needs_parent():
        raise HTTPException(status_code=409, detail="Settle every flagged reading before planning practice.")
    diagnosis = pipeline.diagnose(req.assessment)
    practice = pipeline.plan(diagnosis, req.assessment)
    return {
        "summary": pipeline.parent_summary(req.assessment, diagnosis, practice),
        "diagnosis": diagnosis.model_dump(mode="json"),
        "practice_set": practice.model_dump(mode="json") if practice else None,
    }


@router.post("/demo/approve")
async def demo_approve_practice(
    req: ApproveSetRequest,
    auth: dict = Depends(require_demo_practice_preview),
) -> dict:
    """A visitor's explicit approval unlocks prompt-only, session-only delivery."""
    if req.practice_set is None or not req.practice_set.items:
        raise HTTPException(status_code=422, detail="Choose at least one practice item.")
    return {
        "approved": True,
        "items": [
            {"index": index, "prompt": item.prompt, "hint": item.hint,
                 "diagram": item.diagram.model_dump(mode="json") if item.diagram else None}
            for index, item in enumerate(req.practice_set.items)
        ],
    }


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
    await consent.require_collection(db, student_name)
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
