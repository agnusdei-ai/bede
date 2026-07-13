from fastapi import APIRouter, Depends, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse

from core.audit import AuditEvent, audit_from_request, log_event
from core.demo_code_session import get_personalization
from core.deps import require_auth
from core.diagnostic_preview_quota import has_quota, record_use
from models.schemas import DiagnosticChatRequest, MasteryProfileSummary
from services.ai_service import stream_sandbox_response
from services.diagnostic_demo import get_mastery_summary_demo

router = APIRouter(prefix="/diagnostic", tags=["diagnostic"])


def _require_demo_code(auth: dict = Depends(require_auth)) -> dict:
    """
    No separate login — reachable with the exact same demo_code token the
    child's own session already has (like the "Ask Bede" sandbox preview),
    since this is single-session, non-sensitive preview data, not a real
    family's data. Still not reachable by parent/child (production) — see
    homeschool-tutor isolation note on get_diagnostic_summary below.
    """
    if auth.get("role") != "demo_code":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This preview is only available through the public demo login",
        )
    return auth


def _require_diagnostic_quota(request: Request, auth: dict = Depends(_require_demo_code)) -> dict:
    """
    Blocks entry once core/diagnostic_preview_quota.py's per-IP cap is
    exhausted — see that module's docstring for why the diagnostic
    preview specifically (not the base demo chat) is capped by IP across
    a rolling 30-day window, not per demo code. 429, matching the
    existing per-code email cap's status code (routers/tutor.py's
    /email-summary) — this is a quota, not a permissions rejection.

    Deliberately does NOT call record_use itself — that only happens once
    an endpoint actually delivers real diagnostic content (see
    get_diagnostic_summary/diagnostic_chat below), so a summary request
    that 404s for having no evidence yet doesn't silently burn one of the
    visitor's 3 uses for nothing to show.
    """
    ip = audit_from_request(request)["ip"]
    code = auth.get("code", "")
    if not has_quota(ip, code):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "You've reached the diagnostic preview limit for this demo. "
                "It's meant for a quick evaluation, not ongoing tutoring — "
                "set up your own deployment for real, unlimited use."
            ),
        )
    return auth


@router.get("/summary", response_model=MasteryProfileSummary)
async def get_diagnostic_summary(
    request: Request,
    auth: dict = Depends(_require_diagnostic_quota),
) -> MasteryProfileSummary:
    """
    Render-only mastery summary for the current demo session — built
    entirely from that code's in-memory state (services/diagnostic_demo.py),
    never a database. 404 until the session has actually produced some
    real math evidence. demo_code-only, so this never reaches
    homeschool-tutor/production data.

    Quota (core/diagnostic_preview_quota.py) is only actually spent below,
    once real evidence exists to show — a 404 (nothing to evaluate yet)
    doesn't burn one of the visitor's uses for nothing.
    """
    code = auth.get("code", "")
    student_name, _grade = get_personalization(code)
    summary = get_mastery_summary_demo(code, student_name or "Guest")
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No mastery data yet — this builds up once some math tutoring happens in this demo session",
        )
    record_use(audit_from_request(request)["ip"], code)
    await log_event(
        AuditEvent.DIAGNOSTIC_VIEW,
        role="demo_code",
        student_name=student_name,
        success=True,
        **audit_from_request(request),
    )
    return MasteryProfileSummary(**summary)


@router.post("/chat")
async def diagnostic_chat(
    req: DiagnosticChatRequest,
    request: Request,
    auth: dict = Depends(_require_diagnostic_quota),
):
    """
    Direct-answer chat for the diagnostic preview — same relaxed,
    non-Socratic persona as the SANDBOX_PIN sandbox (routers/sandbox.py),
    reused via stream_sandbox_response, with the current mastery summary
    (if any) woven in as context so whoever's viewing the preview can ask
    about the actual gaps/next-steps, not just generic homeschooling
    questions. Nothing here is persisted — same as the sandbox it's
    modeled on.

    Quota is only spent when there's real evidence to discuss — same rule
    as get_diagnostic_summary above, so asking before any math tutoring
    has happened (a generic, no-evidence answer) doesn't burn a use.
    """
    code = auth.get("code", "")
    student_name, _grade = get_personalization(code)
    summary = get_mastery_summary_demo(code, student_name or "Guest")
    if summary:
        record_use(audit_from_request(request)["ip"], code)
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
