import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit import AuditEvent, audit_from_request, log_event
from core.config import settings
from core.database import get_db
from core.demo_code_session import (
    claim_email_send as demo_code_claim_email_send,
    get_personalization as get_demo_personalization,
    record_message as demo_code_record_message,
)
from core.deps import require_auth, require_parent
from core.sse_utils import STREAM_STALL_TIMEOUT_SECONDS, with_stall_timeout
from models.schemas import (
    EmailSummaryRequest,
    grade_to_stage,
    GradeStage,
    NarrationUploadRequest,
    SessionConfig,
    SessionSummaryRequest,
    Subject,
    SpeakRequest,
    TutorRequest,
)
from services.ai_service import (
    _sanitize_parent_field,
    check_safeguarding,
    generate_session_summary,
    SAFEGUARDING_RESPONSE,
    stream_tutor_response,
)
from services.document_extraction import extract_narration_text, UnsupportedNarrationFileError
from services.email_service import build_summary_email_html, send_distress_alert, send_email
from services.voice_synthesis import synthesis_configured, synthesize_speech

log = logging.getLogger(__name__)

router = APIRouter(prefix="/tutor", tags=["tutor"])


async def _demo_session_config(code: str | None = None) -> SessionConfig:
    """
    Server-defined session config for the public demo's demo_code role —
    never built from live client input on /tutor/chat itself. The one
    exception is student_name/grade, which a visitor can optionally set
    once, up front, at POST /auth/demo-code (see routers/auth.py) —
    sanitized and validated there, then looked up here by the code baked
    into their JWT. Everything else (all subjects included, voice off)
    stays fixed so a demo visitor can browse the full curriculum breadth
    without configuring anything else.
    """
    student_name, grade = (None, None)
    if code:
        student_name, grade = await get_demo_personalization(code)
    return SessionConfig(
        student_name=student_name or settings.demo_student_name,
        grade=grade or settings.demo_grade,
        grade_stage=grade_to_stage(grade) if grade else GradeStage(settings.demo_grade_stage),
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
    Accessible to parent, child, and the scoped public-demo "demo_code"
    role. Passes db so Bede can persist narration assessments server-side
    mid-stream (skipped for the demo role — see below).
    """
    role = auth.get("role")
    is_demo_code = role == "demo_code"
    if is_demo_code:
        # Never trust client-supplied session_config for the demo role —
        # only the subject choice (browsing the curriculum) and the
        # name/grade they set once at /auth/demo-code are theirs to make.
        req.session_config = await _demo_session_config(auth.get("code"))
        db = None

    if is_demo_code:
        # Usage bookkeeping only — no cap enforced (see core/demo_code_session.py).
        await demo_code_record_message(auth.get("code", ""))

    # Fire-and-forget — log_event() runs in its own independent DB session
    # and already swallows its own failures (see core/audit.py), so there's
    # no reason to make every single chat message pay for a full encrypt +
    # INSERT + COMMIT round-trip before Bede's response even starts
    # streaming. This was the single biggest per-message latency cost once
    # the demo started routing every message through this backend instead
    # of straight to Anthropic.
    asyncio.create_task(log_event(
        AuditEvent.TUTOR_CHAT,
        role=auth.get("role"),
        student_name=req.session_config.student_name,
        success=True,
        **audit_from_request(request),
    ))

    async def event_generator():
        # Deterministic safeguarding check — bypasses LLM entirely for crisis signals
        if check_safeguarding(req.child_message):
            trigger_excerpt = req.child_message[:80]
            await log_event(
                AuditEvent.SAFEGUARDING,
                role=auth.get("role"),
                student_name=req.session_config.student_name,
                success=True,
                detail=f"trigger:{trigger_excerpt}",
                **audit_from_request(request),
            )
            # Fire-and-forget — the child's safety response below must not
            # wait on a network round-trip to Resend. The audit log entry
            # above is the durable record regardless of whether this send
            # succeeds; distress_alert_configured() short-circuits instantly
            # when PARENT_EMAIL/Resend aren't set up.
            asyncio.create_task(send_distress_alert(
                req.session_config.student_name,
                datetime.now(timezone.utc).isoformat(),
                trigger_excerpt,
            ))
            yield json.dumps({'type': 'text', 'content': SAFEGUARDING_RESPONSE})
            yield json.dumps({'type': 'done'})
            return

        # Wrapped in with_stall_timeout + try/except so this generator is
        # GUARANTEED to terminate with a real {"type": "done"} the child's
        # own reader.read() loop can see — without this, an upstream stall
        # (or any other mid-stream exception) left the SSE connection open
        # with nothing more ever coming, and neither side had a timeout of
        # its own: the child's send button just spun forever with no way to
        # recover short of reloading the page.
        try:
            async for chunk in with_stall_timeout(
                stream_tutor_response(
                    config=req.session_config,
                    subject=req.current_subject,
                    history=req.conversation_history,
                    child_message=req.child_message,
                    db=db,
                    drawing_image=req.drawing_image,
                    demo_code=auth.get("code") if is_demo_code else None,
                    time_of_day=req.local_time_of_day,
                ),
                timeout_seconds=STREAM_STALL_TIMEOUT_SECONDS,
            ):
                yield chunk
        except asyncio.TimeoutError:
            log.warning(
                "Tutor stream stalled past %.0fs for %s — closing with a recoverable error",
                STREAM_STALL_TIMEOUT_SECONDS, req.session_config.student_name,
            )
            yield json.dumps({
                'type': 'text',
                'content': "Sorry, that took too long to come through. Could you try sending that again?",
            })
            yield json.dumps({'type': 'done'})
        except Exception:
            log.exception("Tutor stream failed mid-turn for %s", req.session_config.student_name)
            yield json.dumps({
                'type': 'text',
                'content': "Something went wrong on my end. Could you try sending that again?",
            })
            yield json.dumps({'type': 'done'})

    return EventSourceResponse(event_generator(), media_type="text/event-stream")


@router.get("/demo-config", response_model=SessionConfig)
async def get_demo_config(auth: dict = Depends(require_auth)) -> SessionConfig:
    """
    Server-defined session config for the public demo — the demo frontend
    fetches this after login instead of running its own setup screen.
    Reflects the name/grade the visitor optionally set at /auth/demo-code
    (see _demo_session_config); nothing else is configurable.
    """
    return await _demo_session_config(auth.get("code"))


@router.post("/extract-narration")
async def extract_narration(req: NarrationUploadRequest, auth: dict = Depends(require_auth)):
    """
    Pulls plain text out of a narration file the child already has — exported
    from a smart pen/notebook app like inq (https://inq.shop), whose own AI
    already transcribed their handwriting — so it can be reviewed and sent
    into the normal chat turn exactly like anything typed or spoken, reusing
    the whole existing pipeline (streaming, tool calls, assess_narration)
    with no separate multimodal path. See services/document_extraction.py.
    Available to parent, child, and the scoped demo role, same as /speak.
    """
    try:
        text = extract_narration_text(req.filename, req.content_base64)
    except UnsupportedNarrationFileError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"text": _sanitize_parent_field(text, max_len=2000) or ""}


@router.post("/speak")
async def speak(req: SpeakRequest, auth: dict = Depends(require_auth)):
    """
    Synthesize Bede's spoken voice — OpenAI TTS if configured, else nothing
    (see services/voice_synthesis.py). Returns 204 with no body when
    synthesis fails or nothing is configured.

    The X-TTS-Configured header tells the frontend whether SOME backend TTS
    is set up at all, so it can tell "nothing configured — the browser's own
    speech is a reasonable zero-config default" apart from "configured but
    this call failed — stay silent rather than degrading to a different,
    lower-quality voice mid-conversation" (see useTextToSpeech's speak()).

    Uses require_auth (not require_real_user) so the scoped demo role can
    reach this too — unlike catalog/pod/narration/transcripts/voice, this
    endpoint reads no student data and writes nothing; it's the same
    ephemeral speak-this-line trade the demo already makes for /chat.
    """
    audio = await synthesize_speech(req.text)
    headers = {"X-TTS-Configured": str(synthesis_configured())}
    if audio is None:
        return Response(status_code=204, headers=headers)
    return Response(content=audio, media_type="audio/wav", headers=headers)


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


@router.post("/email-summary")
async def email_summary(
    req: EmailSummaryRequest,
    request: Request,
    auth: dict = Depends(require_auth),
):
    """
    Generate the same end-of-session summary as /summary, then email it once
    to a parent-supplied address via Resend — never shown to the child, never
    written anywhere (see services/email_service.py). Available to the parent
    role and the scoped public demo role; child and parent_pending are not
    parents, so they're rejected here the same way /summary rejects them by
    only depending on require_parent.

    The demo role is additionally capped to exactly one send per session
    (core/demo_code_session.claim_email_send) — the public demo shouldn't
    let one visitor spam an address or run up the operator's Resend usage.
    """
    role = auth.get("role")
    if role not in ("parent", "demo_code"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this action")

    if role == "demo_code":
        # Never trust client-supplied session_config for the demo role —
        # only the transcript/subjects it already streamed are real; mirrors /chat.
        code = auth.get("code", "")
        req.session_config = await _demo_session_config(code)
        if not await demo_code_claim_email_send(code):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="This session has already sent its one diagnostic email",
            )

    summary = await generate_session_summary(req)
    html_body = build_summary_email_html(req.session_config.student_name, summary)
    sent = await send_email(
        to_address=req.email,
        subject=f"Bede's notes from {req.session_config.student_name}'s session",
        html_body=html_body,
    )

    # Never log req.email — the recipient address is exactly the one thing
    # this feature promises never to persist, audit log included.
    await log_event(
        AuditEvent.SUMMARY_EMAILED,
        role=role,
        student_name=req.session_config.student_name,
        success=sent,
        **audit_from_request(request),
    )

    if not sent:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send the email right now — please try again later",
        )
    return {"sent": True}
