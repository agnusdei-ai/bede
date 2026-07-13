import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse

from core.audit import AuditEvent, audit_from_request, log_event
from core.demo_code_session import get_personalization
from core.deps import require_auth
from core.diagnostic_preview_quota import has_quota, record_use
from models.schemas import DiagnosticChatRequest, MasteryProfileSummary
from services.diagnostic_demo import get_mastery_summary_demo

router = APIRouter(prefix="/diagnostic", tags=["diagnostic"])

CONTACT_CTA = "reach out at info@agnusdei.ai"


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
                "You've used up this demo's diagnostic preview for now — it's meant to give you "
                "a taste, not replace a full account. We'd love to show you the full-featured "
                f"version and our monthly/annual plans — {CONTACT_CTA}."
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
    "Chat" for the diagnostic preview — deliberately templated from the
    already-computed mastery summary, NOT a live model call. The demo/free
    tier must never consume real API usage: get_diagnostic_summary above
    was already free (pure data rendering), and this used to be the one
    exception (a full stream_sandbox_response conversation per message).
    Ignores req.message's actual content by design — there's no live
    understanding to answer with at this tier; a real conversational
    advisor is exactly the upsell _templated_diagnostic_reply below steers
    toward. Still streamed as SSE (one text chunk + done) so the frontend
    can reuse the exact same consumer it already had for the old live-chat
    version — req.conversation_history is accepted for API-shape
    compatibility but unused, same reason.

    Quota is only spent when there's real evidence to discuss — same rule
    as get_diagnostic_summary above, so asking before any math tutoring
    has happened (a generic, no-evidence answer) doesn't burn a use.
    """
    code = auth.get("code", "")
    student_name, _grade = get_personalization(code)
    summary = get_mastery_summary_demo(code, student_name or "Guest")
    if summary:
        record_use(audit_from_request(request)["ip"], code)
    reply = _templated_diagnostic_reply(summary)

    async def event_generator():
        yield json.dumps({"type": "text", "content": reply})
        yield json.dumps({"type": "done"})

    return EventSourceResponse(event_generator(), media_type="text/event-stream")


def _templated_diagnostic_reply(summary: dict | None) -> str:
    """Zero-API-cost stand-in for a real conversational answer — built
    entirely from summary's already-computed fields, same shape as the
    old _render_mastery_context but written as a direct answer to the
    parent rather than instructions to a model."""
    if not summary:
        return (
            "No math evidence has been recorded in this demo session yet — try working through "
            "a question or two in the Mathematics subject, then come back and check again.\n\n"
            f"This preview shows a snapshot only. Want a real conversation about your child's "
            f"progress, plus full-featured tutoring? We'd love to talk — {CONTACT_CTA}."
        )

    lines = [
        f"Here's where {summary['student_name']} stands in {summary['subject_area']} so far "
        f"({summary['evidence_count']} observation{'' if summary['evidence_count'] == 1 else 's'}"
        + (", still getting calibrated" if summary["calibration"] else "") + "):",
        "",
    ]
    for domain in summary["domains"]:
        lines.append(f"• {domain['domain']}: {domain['level']} ({domain['average_probability']:.0%})")
    if summary["gaps"]:
        lines.append("")
        lines.append("Gaps to focus on: " + ", ".join(s["label"] for s in summary["gaps"]))
    if summary["next_steps"]:
        lines.append("Suggested next steps: " + ", ".join(s["label"] for s in summary["next_steps"]))
    lines.append("")
    lines.append(
        f"This preview shows a snapshot only. Want a real conversation about {summary['student_name']}'s "
        f"progress, plus full-featured tutoring? We'd love to talk about our monthly/annual plans — {CONTACT_CTA}."
    )
    return "\n".join(lines)
