import json

from fastapi import APIRouter, Depends, Request, Response
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit import AuditEvent, audit_from_request, log_event
from core.database import get_db
from core.deps import require_auth, require_parent
from models.schemas import SessionSummaryRequest, SpeakRequest, TutorRequest
from services.ai_service import (
    check_safeguarding,
    generate_session_summary,
    SAFEGUARDING_RESPONSE,
    stream_tutor_response,
)
from services.voice_synthesis import synthesize_speech

router = APIRouter(prefix="/tutor", tags=["tutor"])


@router.post("/chat")
async def chat(
    req: TutorRequest,
    request: Request,
    auth: dict = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Stream Socratic tutor responses via Server-Sent Events.
    Accessible to both parent and child tokens. Passes db so Bede can
    persist narration assessments server-side mid-stream.
    """
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


@router.post("/speak")
async def speak(req: SpeakRequest, auth: dict = Depends(require_auth)):
    """
    Synthesize Bede's spoken voice via the configured cloud TTS (see
    services/voice_synthesis.py). Returns 204 with no body when unconfigured
    or on failure — the frontend falls back to the browser's own
    speechSynthesis in that case, so a TTS hiccup never breaks the session.
    """
    audio = await synthesize_speech(req.text)
    if audio is None:
        return Response(status_code=204)
    return Response(content=audio, media_type="audio/mpeg")


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
