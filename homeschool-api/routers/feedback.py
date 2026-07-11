from fastapi import APIRouter, Depends, HTTPException, Request, status

from core.audit import AuditEvent, audit_from_request, log_event
from core.config import settings
from core.deps import require_auth
from models.schemas import FeedbackRequest
from services.email_service import feedback_configured, send_feedback

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("")
async def submit_feedback(
    req: FeedbackRequest,
    request: Request,
    auth: dict = Depends(require_auth),
):
    """
    Beta CX/UX/content-quality feedback, routed to the operator's own inbox
    (FEEDBACK_EMAIL) — never persisted server-side beyond that one outbound
    email. Open to any authenticated role (parent, child, or a scoped public
    demo visitor) since feedback is exactly as welcome from a beta family as
    from a demo visitor. 404s when FEEDBACK_EMAIL isn't configured, matching
    the same "feature doesn't exist on this deployment" pattern as
    /auth/demo-code, rather than accepting feedback that silently goes nowhere.
    """
    if not settings.feedback_email:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback isn't enabled on this deployment")

    role = auth.get("role", "unknown")
    sent = await send_feedback(
        category=req.category,
        message=req.message,
        role=role,
        rating=req.rating,
        contact_email=req.contact_email,
    )

    # Never log message or contact_email — same rule as /tutor/email-summary.
    await log_event(
        AuditEvent.FEEDBACK_SUBMITTED,
        role=role,
        success=sent,
        detail=f"category={req.category}",
        **audit_from_request(request),
    )

    if not sent:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send feedback right now — please try again later",
        )
    return {"sent": True}


@router.get("/enabled")
async def feedback_enabled():
    """Public, unauthenticated check so a frontend can hide the feedback
    button entirely on a deployment where it isn't configured, rather than
    showing it and only failing on submit."""
    return {"enabled": feedback_configured()}
