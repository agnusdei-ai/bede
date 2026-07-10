import hmac
import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse

from core.audit import AuditEvent, audit_from_request, log_event
from core.config import settings
from core.demo_code_session import record_message as demo_code_record_message
from core.deps import require_auth, require_parent
from models.schemas import SandboxChatRequest, SandboxDemoChatRequest
from services.ai_service import check_safeguarding, SAFEGUARDING_RESPONSE, stream_sandbox_response

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


@router.post("/chat")
async def chat(
    req: SandboxChatRequest,
    _: dict = Depends(require_parent),
):
    """
    Direct-answer chat for testing/exploring Bede's behavior. Requires an
    already-authenticated parent session (require_parent) *plus* the correct
    SANDBOX_PIN on every request — there's no separate sandbox login/token,
    this rides entirely on the parent's existing auth. Disabled outright
    (404) when SANDBOX_PIN isn't configured, same "empty = disabled" pattern
    as DEMO_PIN. Nothing here touches the database — no session, no
    narration assessment, no audit-logged content — see services/ai_service.py's
    stream_sandbox_response.
    """
    if not settings.sandbox_pin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sandbox mode is not enabled on this deployment.",
        )
    if not hmac.compare_digest(req.sandbox_pin, settings.sandbox_pin):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect sandbox PIN")

    async def event_generator():
        async for chunk in stream_sandbox_response(
            conversation_history=req.conversation_history,
            message=req.message,
            custom_instructions=req.custom_instructions,
        ):
            yield chunk

    return EventSourceResponse(event_generator(), media_type="text/event-stream")


@router.post("/demo-chat")
async def demo_chat(
    req: SandboxDemoChatRequest,
    request: Request,
    auth: dict = Depends(require_auth),
):
    """
    Public-demo preview of the sandbox above — same direct-answer, relaxed
    persona, reachable via either public-demo login (shared DEMO_PIN, or the
    self-service demo_code) instead of a real parent session + SANDBOX_PIN.
    require_auth already enforces the "demo" role's single-active-session and
    5-minute-inactivity timeout (see core/deps.py, core/demo_session.py), and
    the "demo_code" role's message cap is enforced explicitly below (each
    sandbox message spends the same shared quota as the regular /tutor/chat,
    same as /tutor/chat itself). Unlike the private /chat above, this keeps
    the deterministic safeguarding check as a defensive baseline, since
    anyone who knows the public DEMO_PIN can reach this, not just the
    deployment's trusted operator.
    """
    role = auth.get("role")
    if role not in ("demo", "demo_code"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This preview is only available through the public demo login",
        )
    if role == "demo_code" and not demo_code_record_message(auth.get("code", "")):
        quota_message = "You've used all your free messages for this code — generate a new one on the landing page to keep exploring."

        async def quota_exhausted():
            yield f"data: {json.dumps({'type': 'text', 'content': quota_message})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return EventSourceResponse(quota_exhausted(), media_type="text/event-stream")

    async def event_generator():
        if check_safeguarding(req.message):
            await log_event(
                AuditEvent.SAFEGUARDING,
                role="demo",
                success=True,
                detail=f"trigger:{req.message[:80]} (sandbox demo preview)",
                **audit_from_request(request),
            )
            yield f"data: {json.dumps({'type': 'text', 'content': SAFEGUARDING_RESPONSE})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        async for chunk in stream_sandbox_response(
            conversation_history=req.conversation_history,
            message=req.message,
            custom_instructions=req.custom_instructions,
        ):
            yield chunk

    return EventSourceResponse(event_generator(), media_type="text/event-stream")
