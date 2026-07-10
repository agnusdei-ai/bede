import hmac

from fastapi import APIRouter, Depends, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from core.config import settings
from core.deps import require_parent
from models.schemas import SandboxChatRequest
from services.ai_service import stream_sandbox_response

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
