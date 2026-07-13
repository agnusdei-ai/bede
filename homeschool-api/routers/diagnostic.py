from fastapi import APIRouter, Depends, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse

from core.audit import AuditEvent, audit_from_request, log_event
from core.demo_code_session import get_personalization
from core.deps import require_auth
from models.schemas import DiagnosticChatRequest, MasteryProfileSummary
from services.ai_service import stream_sandbox_response
from services.diagnostic_demo import get_mastery_summary_demo

router = APIRouter(prefix="/diagnostic", tags=["diagnostic"])


def _require_diagnostic_parent(auth: dict = Depends(require_auth)) -> dict:
    if auth.get("role") != "diagnostic_parent":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This preview is only available through the diagnostic login",
        )
    return auth


@router.get("/summary", response_model=MasteryProfileSummary)
async def get_diagnostic_summary(
    request: Request,
    auth: dict = Depends(_require_diagnostic_parent),
) -> MasteryProfileSummary:
    """
    Render-only mastery summary for the demo code this diagnostic_parent
    token is tied to — built entirely from that code's in-memory session
    state (services/diagnostic_demo.py), never a database. 404 until the
    child's demo session has actually produced some real math evidence.
    """
    code = auth.get("code", "")
    student_name, _grade = get_personalization(code)
    summary = get_mastery_summary_demo(code, student_name or "Guest")
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No mastery data yet — this builds up once some math tutoring happens in this demo session",
        )
    await log_event(
        AuditEvent.DIAGNOSTIC_VIEW,
        role="diagnostic_parent",
        student_name=student_name,
        success=True,
        **audit_from_request(request),
    )
    return MasteryProfileSummary(**summary)


@router.post("/chat")
async def diagnostic_chat(
    req: DiagnosticChatRequest,
    auth: dict = Depends(_require_diagnostic_parent),
):
    """
    Direct-answer chat for the diagnostic preview — same relaxed,
    non-Socratic persona as the SANDBOX_PIN sandbox (routers/sandbox.py),
    reused via stream_sandbox_response, with the current mastery summary
    (if any) woven in as context so the parent can ask about their child's
    actual gaps/next-steps, not just generic homeschooling questions.
    Nothing here is persisted — same as the sandbox it's modeled on.
    """
    code = auth.get("code", "")
    student_name, _grade = get_personalization(code)
    summary = get_mastery_summary_demo(code, student_name or "Guest")
    context = _render_mastery_context(summary) if summary else (
        "No math evidence has been recorded in this demo session yet — "
        "answer generally about homeschooling and how this diagnostic preview works."
    )

    async def event_generator():
        async for chunk in stream_sandbox_response(
            conversation_history=req.conversation_history,
            message=req.message,
            custom_instructions=context,
        ):
            yield chunk

    return EventSourceResponse(event_generator(), media_type="text/event-stream")


def _render_mastery_context(summary: dict) -> str:
    lines = [
        f"Here is {summary['student_name']}'s current mastery snapshot for {summary['subject_area']} "
        f"in this demo session ({summary['evidence_count']} pieces of evidence recorded so far"
        + (", still calibrating" if summary["calibration"] else "") + "):",
    ]
    for domain in summary["domains"]:
        lines.append(f"- {domain['domain']}: {domain['level']} ({domain['average_probability']:.0%})")
    if summary["gaps"]:
        lines.append("Gaps: " + ", ".join(s["label"] for s in summary["gaps"]))
    if summary["next_steps"]:
        lines.append("Suggested next steps: " + ", ".join(s["label"] for s in summary["next_steps"]))
    lines.append(
        "Use this to answer the parent's questions about their child's math understanding "
        "and general homeschooling guidance — direct answers, not Socratic questions."
    )
    return "\n".join(lines)
