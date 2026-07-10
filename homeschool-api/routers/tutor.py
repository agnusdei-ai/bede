import json

from fastapi import APIRouter, Depends, Request, Response
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit import AuditEvent, audit_from_request, log_event
from core.config import settings
from core.database import get_db
from core.deps import require_auth, require_parent
from models.schemas import GradeStage, SessionConfig, SessionSummaryRequest, Subject, SpeakRequest, TutorRequest
from services.ai_service import (
    check_safeguarding,
    generate_session_summary,
    SAFEGUARDING_RESPONSE,
    stream_tutor_response,
)
from services.voice_synthesis import synthesize_speech

router = APIRouter(prefix="/tutor", tags=["tutor"])


def _demo_session_config() -> SessionConfig:
    """
    Fixed, server-defined session config for the public demo role — never
    built from client input. All subjects are included so a demo visitor can
    browse the full curriculum breadth; nothing else about it is configurable.
    """
    return SessionConfig(
        student_name=settings.demo_student_name,
        grade=settings.demo_grade,
        grade_stage=GradeStage(settings.demo_grade_stage),
        subjects=list(Subject),
        voice_required=False,
    )


@router.post("/chat")
async def chat(
    req: TutorRequest,
    request: Request,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Stream Socratic tutor responses via Server-Sent Events.
    Accessible to parent, child, and the scoped demo role. Passes db so Bede
    can persist narration assessments server-side mid-stream (skipped for
    demo — see below).
    """
    is_demo = auth.get("role") == "demo"
    if is_demo:
        # Never trust client-supplied session_config for the demo role — only
        # the subject choice (browsing the curriculum) is theirs to make.
        req.session_config = _demo_session_config()
        db = None

    await log_event(
        AuditEvent.TUTOR_CHAT,
        role=auth.get("role"),
        student_name=req.session_config.student_name,
        success=True,
        **audit_from_request(request),
    )

    async def event_generator():
        # Deterministic safeguarding check — bypasses LLM entirely for crisis signals
        if check_safeguarding(req.child_message):
            await log_event(
                AuditEvent.SAFEGUARDING,
                role=auth.get("role"),
                student_name=req.session_config.student_name,
                success=True,
                detail=f"trigger:{req.child_message[:80]}",
                **audit_from_request(request),
            )
            yield f"data: {json.dumps({'type': 'text', 'content': SAFEGUARDING_RESPONSE})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        async for chunk in stream_tutor_response(
            config=req.session_config,
            subject=req.current_subject,
            history=req.conversation_history,
            child_message=req.child_message,
            db=db,
            drawing_image=req.drawing_image,
        ):
            yield chunk

    return EventSourceResponse(event_generator(), media_type="text/event-stream")


@router.get("/demo-config", response_model=SessionConfig)
async def get_demo_config(_: dict = Depends(require_auth)) -> SessionConfig:
    """
    Fixed, server-defined session config for the public demo — the demo
    frontend fetches this after login instead of running its own setup
    screen. Not configurable by the demo role itself.
    """
    return _demo_session_config()


@router.post("/speak")
async def speak(req: SpeakRequest, auth: dict = Depends(require_auth)):
    """
    Synthesize Bede's spoken voice via the self-hosted Kokoro model (see
    services/voice_synthesis.py). Returns 204 with no body when unconfigured
    or on failure — the frontend falls back to the browser's own
    speechSynthesis in that case, so a TTS hiccup never breaks the session.

    Uses require_auth (not require_real_user) so the scoped demo role can
    reach this too — unlike catalog/pod/narration/transcripts/voice, this
    endpoint reads no student data and writes nothing; it's the same
    ephemeral speak-this-line trade the demo already makes for /chat.
    """
    audio = await synthesize_speech(req.text)
    if audio is None:
        return Response(status_code=204)
    return Response(content=audio, media_type="audio/wav")


@router.post("/summary")
async def session_summary(
    req: SessionSummaryRequest,
    request: Request,
    auth: dict = Depends(require_parent),   # parent only
):
    """Generate end-of-session parent report. Parent role required."""
    await log_event(
        AuditEvent.SESSION_END,
        role="parent",
        student_name=req.session_config.student_name,
        detail=f"duration={req.duration_minutes}min",
        **audit_from_request(request),
    )
    summary = await generate_session_summary(req)
    return {"summary": summary}
