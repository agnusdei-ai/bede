import asyncio
import hmac
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse

from core.audit import AuditEvent, audit_from_request, log_event, log_event_nowait
from core.config import settings
from core.demo_code_session import (
    has_message_quota as demo_code_has_message_quota,
    record_message as demo_code_record_message,
)
from core.deps import require_demo_preview, require_parent
from core.sse_utils import STREAM_STALL_TIMEOUT_SECONDS, with_stall_timeout
from models.schemas import SandboxChatRequest, SandboxDemoChatRequest
from services import mcp_client
from services.ai_service import (
    check_safeguarding,
    demo_quota_response,
    SAFEGUARDING_RESPONSE,
    stream_sandbox_response,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/sandbox", tags=["sandbox"])

_STALL_MESSAGE = "Sorry, that took too long to come through. Could you try sending that again?"
_ERROR_MESSAGE = "Something went wrong on my end. Could you try sending that again?"


@router.post("/chat")
async def chat(
    req: SandboxChatRequest,
    request: Request,
    auth: dict = Depends(require_parent),
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
        # External MCP tools (services/mcp_client.py) are reachable HERE and
        # only here: a real parent session that has also presented
        # SANDBOX_PIN. The demo preview below shares stream_sandbox_response
        # but must never share this — see that function's docstring and
        # tests/test_mcp_sandbox_boundary.py.
        external_tools, external_clients = [], {}
        if mcp_client.is_configured(settings):
            try:
                external_tools, external_clients = await mcp_client.load_external_tools(settings)
            except Exception:
                # An unreachable or misconfigured MCP server must not cost the
                # parent their answer — the sandbox works without it.
                log.warning("Could not load external MCP tools", exc_info=True)
        try:
            async for chunk in with_stall_timeout(stream_sandbox_response(
                conversation_history=req.conversation_history,
                message=req.message,
                custom_instructions=req.custom_instructions,
                external_tools=external_tools,
                external_clients=external_clients,
                audit_context=audit_from_request(request),
                locale=auth.get("locale", "en"),
            )):
                yield chunk
        except asyncio.TimeoutError:
            log.warning("Sandbox stream stalled past %.0fs", STREAM_STALL_TIMEOUT_SECONDS)
            # See core/audit.py's AI_BACKEND_FAILURE — pooled across every
            # tutor/sandbox stream failure regardless of which one hit it,
            # so a parent testing config in the sandbox still contributes
            # to (and benefits from) the same backend-health signal.
            log_event_nowait(
                AuditEvent.AI_BACKEND_FAILURE, role="parent", success=False,
                detail="cause=stall subject=sandbox", **audit_from_request(request),
            )
            yield json.dumps({'type': 'text', 'content': _STALL_MESSAGE})
            yield json.dumps({'type': 'done'})
        except Exception as exc:
            log.exception("Sandbox stream failed mid-turn")
            log_event_nowait(
                AuditEvent.AI_BACKEND_FAILURE, role="parent", success=False,
                detail=f"cause=exception subject=sandbox error={type(exc).__name__}",
                **audit_from_request(request),
            )
            yield json.dumps({'type': 'text', 'content': _ERROR_MESSAGE})
            yield json.dumps({'type': 'done'})
        finally:
            for server_client in external_clients.values():
                try:
                    await server_client.aclose()
                except Exception:
                    log.debug("Closing an MCP client failed", exc_info=True)

    return EventSourceResponse(event_generator(), media_type="text/event-stream")


@router.post("/demo-chat")
async def demo_chat(
    req: SandboxDemoChatRequest,
    request: Request,
    auth: dict = Depends(require_demo_preview),
):
    """
    Public-demo preview of the sandbox above — same direct-answer, relaxed
    persona, reachable via the self-service demo_code login instead of a
    real parent session + SANDBOX_PIN. Unlike the private /chat above, this
    keeps the deterministic safeguarding check as a defensive baseline,
    since anyone who generates a demo_code can reach this, not just the
    deployment's trusted operator.

    The demo-domain restriction was an inline `role != "demo_code"` check in
    this body; it's now the "sandbox.demo_preview" action in
    core/policy.py's table, enforced by require_demo_preview.
    """
    demo_code = auth.get("code", "")
    # The actual LLM10 enforcement point (see core/demo_code_session.py's
    # _MAX_MESSAGES_PER_CODE) — checked BEFORE record_message increments, so
    # an over-quota turn is never double-counted and never reaches
    # stream_sandbox_response below.
    demo_quota_exceeded = not await demo_code_has_message_quota(demo_code)
    if not demo_quota_exceeded:
        await demo_code_record_message(demo_code)

    async def event_generator():
        if demo_quota_exceeded:
            await log_event(
                AuditEvent.RATE_LIMITED,
                role="demo_code",
                success=False,
                detail="demo_message_quota (sandbox demo preview)",
                **audit_from_request(request),
            )
            yield json.dumps({'type': 'text', 'content': demo_quota_response("en")})
            yield json.dumps({'type': 'done'})
            return

        if check_safeguarding(req.message):
            await log_event(
                AuditEvent.SAFEGUARDING,
                role="demo_code",
                success=True,
                detail=f"trigger:{req.message[:80]} (sandbox demo preview)",
                **audit_from_request(request),
            )
            yield json.dumps({'type': 'text', 'content': SAFEGUARDING_RESPONSE})
            yield json.dumps({'type': 'done'})
            return

        try:
            async for chunk in with_stall_timeout(stream_sandbox_response(
                conversation_history=req.conversation_history,
                message=req.message,
                custom_instructions=req.custom_instructions,
                locale=auth.get("locale", "en"),
            )):
                yield chunk
        except asyncio.TimeoutError:
            log.warning("Sandbox demo stream stalled past %.0fs", STREAM_STALL_TIMEOUT_SECONDS)
            log_event_nowait(
                AuditEvent.AI_BACKEND_FAILURE, role="demo_code", success=False,
                detail="cause=stall subject=sandbox_demo", **audit_from_request(request),
            )
            yield json.dumps({'type': 'text', 'content': _STALL_MESSAGE})
            yield json.dumps({'type': 'done'})
        except Exception as exc:
            log.exception("Sandbox demo stream failed mid-turn")
            log_event_nowait(
                AuditEvent.AI_BACKEND_FAILURE, role="demo_code", success=False,
                detail=f"cause=exception subject=sandbox_demo error={type(exc).__name__}",
                **audit_from_request(request),
            )
            yield json.dumps({'type': 'text', 'content': _ERROR_MESSAGE})
            yield json.dumps({'type': 'done'})

    return EventSourceResponse(event_generator(), media_type="text/event-stream")
