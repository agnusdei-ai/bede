import asyncio
import base64
import binascii
import hashlib
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession

from services.adapters.openai_compatible_adapter import backend_failure_detail
from core.audit import AuditEvent, audit_from_request, log_event, log_event_nowait
from core.log_redaction import exc_summary, learner_ref
from core.config import settings
from core import consent
from core.database import get_db, release_idle_connection
from core.demo_code_session import (
    claim_email_send as demo_code_claim_email_send,
    get_current_unit as get_demo_current_unit,
    get_faith_tradition as get_demo_faith_tradition,
    get_parent_config as get_demo_parent_config,
    get_personalization as get_demo_personalization,
    has_message_quota as demo_code_has_message_quota,
    record_message as demo_code_record_message,
)
from core.deps import require_auth, require_email_summary, require_parent, require_learner_access
from core.sse_utils import STREAM_STALL_TIMEOUT_SECONDS, with_stall_timeout
from models.schemas import (
    CompanionMode,
    EmailSummaryRequest,
    demo_grade_to_stage,
    GradeStage,
    NarrationUploadRequest,
    SessionConfig,
    SessionSummaryRequest,
    Subject,
    SpeakRequest,
    TermSchedule,
    TutorRequest,
)
from services.ai_service import (
    _redact_credentials,
    _sanitize_parent_field,
    check_safeguarding,
    ai_unavailable_response,
    demo_quota_response,
    generate_session_summary,
    moderation_redirect_response,
    safeguarding_response,
    stream_tutor_response,
)
from services import content_screen, file_safety, pilot_authz, safeguarding_alerts, turn_replay
from services.adversarial_detection import build_signals
from services.document_extraction import extract_narration_text, UnsupportedNarrationFileError
from services.email_service import build_summary_email_html, send_email
from services.adapters import router as adapter_router
from services.moderation import classify_child_message
from services.policy_engine import decide as decide_policy
from services.voice_synthesis import (
    active_provider, synthesis_configured, synthesize_speech, unconfigured_reason, voice_available,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/tutor", tags=["tutor"])


def _demo_current_term(code: str | None) -> int:
    """
    A demo session has no real academic calendar to derive current_term
    from, and SessionConfig's own default (1) is never overridden here —
    which meant every single demo visitor, forever, saw term 1's
    picture-study artist (at the time Millet for every grade; the artist
    is now a function of grade AND term, ai_service.py's
    _term_rotation_index), with no way to ever see the others. Deriving a
    1-4 value from the demo code itself keeps one session internally
    consistent (the artist can't shift mid-conversation) while actually
    exercising the rotation feature across different visitors/codes,
    which is presumably the point of having it in a demo meant to show
    the curriculum's breadth. Which PICTURE of that artist's is featured
    then rotates on the calendar week on its own, as for a real family.

    This value also gets reused as poetry's week_salt (services/
    poetry_catalog.py) — not because poetry is term-based anymore (it now
    rotates weekly off the calendar, which is what actually fixed poetry
    always landing on the same poem), but so different demo codes don't
    all land on the identical poem within the same calendar week.
    """
    if not code:
        return 1
    return (int(hashlib.sha256(code.encode()).hexdigest(), 16) % 4) + 1


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

    term_schedule is pinned to quarterly (4 terms) rather than the default
    trimester (3) specifically so _demo_current_term's 1-4 range lines up
    with a full year of the picture-study artist rotation, not just its
    first three terms (the visitor's chosen grade supplies the year).

    current_unit is the other optional per-code personalization (see
    DemoCodeRequest.current_unit and CLAUDE.md's "Continuing Mastery
    (demo)" section) — a visitor's own "what we're already covering at
    home" note, threaded straight into SessionConfig.current_unit exactly
    like a real parent's field. It already gets the same
    _sanitize_parent_field pass every current_unit does in
    _build_subject_prompt (services/ai_service.py), on top of the
    sanitization applied once at /auth/demo-code — belt and suspenders on
    public, anonymous input.

    faith_tradition is a third optional per-code personalization (see
    DemoCodeRequest.faith_tradition and core/database.py's
    DemoCodeFaithNote) — the visiting family's own church tradition,
    threaded into SessionConfig.faith_tradition so Bede can frame Scripture
    & Bible Study / Saints & Catechism content consistently with it, since
    `subjects=list(Subject)` below means every demo visitor sees both
    modules regardless of their own background.
    """
    student_name, grade = (None, None)
    current_unit = None
    faith_tradition = None
    parent_config: dict = {}
    if code:
        student_name, grade = await get_demo_personalization(code)
        current_unit = await get_demo_current_unit(code)
        faith_tradition = await get_demo_faith_tradition(code)
        parent_config = await get_demo_parent_config(code) or {}

    # The visitor's own Parent Setup, if they opened it (POST
    # /auth/demo-code/config). Every value was already validated by
    # building a real SessionConfig at the write path and sanitized on the
    # way in, so this only decides PRECEDENCE — and the rule is that an
    # explicit setup wins over the intake-screen note, which wins over the
    # demo's own default. current_unit and faith_tradition can be set in
    # both places (the code screen asks for them before a visitor has seen
    # anything, the setup panel after), and the later, more deliberate
    # answer is the setup panel's.
    # New course subjects are adult opt-ins, not additions to existing demos.
    subjects = [Subject(s) for s in parent_config.get("subjects") or []] or [
        s for s in Subject if s not in {Subject.spanish, Subject.computing, Subject.movement_health}
    ]
    companion = parent_config.get("companion_mode")

    return SessionConfig(
        student_name=student_name or settings.demo_student_name,
        grade=grade or settings.demo_grade,
        grade_stage=demo_grade_to_stage(grade) if grade else GradeStage(settings.demo_grade_stage),
        subjects=subjects,
        voice_required=False,
        term_schedule=TermSchedule.quarterly,
        current_term=_demo_current_term(code),
        current_unit=parent_config.get("current_unit") or current_unit,
        grade8_curriculum=parent_config.get("grade8_curriculum"),
        upper_curriculum=parent_config.get("upper_curriculum"),
        faith_tradition=parent_config.get("faith_tradition") or faith_tradition,
        **({"companion_mode": CompanionMode(companion)} if companion else {}),
        lesson_focus=parent_config.get("lesson_focus"),
        faith_emphasis=parent_config.get("faith_emphasis"),
        bible_translation=parent_config.get("bible_translation"),
        curriculum_resources=parent_config.get("curriculum_resources") or [],
        character_virtues=parent_config.get("character_virtues") or [],
        learning_support=parent_config.get("learning_support") or [],
    )


# The three course subjects that exist only in the Grade 8 curriculum.
_GRADE8_ONLY_SUBJECTS = frozenset({Subject.spanish, Subject.computing, Subject.movement_health})

_FILE_REFUSED = {
    "en": "Bede couldn't use that picture. Please try a different photo or drawing.",
    "es": "Bede no pudo usar esa imagen. Prueba con otra foto u otro dibujo.",
}


async def _check_lesson_file(image_b64: str, locale: str) -> tuple[str | None, str | None]:
    """(the rebuilt picture, None), or (None, what to tell the child). A file
    the virus scanner flags gets the same calm line as any other refused
    file; the parent is told separately (AuditEvent.FILE_FLAGGED)."""
    try:
        return await file_safety.lesson_picture(image_b64), None
    except file_safety.FileRejected:
        return None, _FILE_REFUSED.get(locale, _FILE_REFUSED["en"])
    except (file_safety.ScannerUnavailable, file_safety.UploadBusy):
        return None, content_screen.unavailable_message("lesson", locale)


async def _screen_lesson_picture(image_b64: str, auth: dict, student_name: str,
                                 request: Request) -> tuple[str | None, str | None]:
    """(None, None) when the picture may reach the tutor; otherwise what to
    tell the child, and, for a safeguarding signal (self-harm or sexual
    content, in any style), its label, which the caller answers with the
    crisis path."""
    from services import ai_service

    locale = auth.get("locale", "en")
    try:
        await content_screen.screen_images(
            ai_service._client, [(content_screen.media_type_of(image_b64), image_b64)], "lesson")
    except content_screen.ContentRefused as exc:
        content_screen.record_refusal(
            exc, audit=audit_from_request(request), role=auth.get("role"), student_name=student_name)
        if exc.crisis:
            return safeguarding_response(locale), content_screen.CRISIS_LABELS[exc.category]
        return content_screen.refusal_message(exc.category, "lesson", locale), None
    except content_screen.ScreeningUnavailable:
        return content_screen.unavailable_message("lesson", locale), None
    return None, None


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
    if auth.get("role") == "child":
        await require_learner_access(auth, req.session_config.student_name, db)
    # AIUC-1 A008 — redact credential-shaped text (API keys, tokens,
    # connection strings) before it reaches the safeguarding-audit excerpt
    # below, model context, or anywhere else this turn's message is used.
    req.child_message = _redact_credentials(req.child_message) or req.child_message

    role = auth.get("role")
    is_demo_code = role == "demo_code"
    # The educator's resolved authorization context (services/pilot_authz.py).
    # None for every other role. When set, the turn re-validates the grant
    # before context retrieval, before every chunk it releases, before every
    # durable write, and periodically while generation is silent. A retry is
    # a new request and resolves a fresh context from scratch.
    tutor_ctx = None
    if is_demo_code:
        # Never trust client-supplied session_config for the demo role —
        # only the subject choice (browsing the curriculum) and the
        # name/grade they set once at /auth/demo-code are theirs to make.
        req.session_config = await _demo_session_config(auth.get("code"))
        db = None
    elif role == "educator":
        # An educator must not be able to swap student_name or inject a
        # different curriculum in the request body. Check assignment FIRST,
        # then reload the authoritative, parent-approved saved SessionConfig.
        from routers.educators import my_student_config
        saved = await my_student_config(
            req.session_config.student_name, auth=auth, db=db,
        )
        if req.current_subject not in saved.subjects:
            raise HTTPException(
                status_code=403,
                detail="Subject not included in approved learner plan",
            )
        req.session_config = saved
        tutor_ctx = await pilot_authz.resolve_legacy_learner(
            db, auth, saved.student_name, pilot_authz.ACTION_TUTOR,
        )
        # No write this turn makes can become durable once the grant stops
        # holding: every commit and flush re-validates first.
        db = pilot_authz.RevocationGatedSession(db, tutor_ctx, audit_from_request(request))

    # COPPA: no child content is collected for a student until a parent has
    # consented, and not while collection is paused (core/consent.py). The
    # demo role is a pseudonymous public session with no StudentConfig and
    # its own retention story, so it is not gated here. The educator branch
    # above has already replaced session_config with the saved, authoritative
    # plan, so this checks the student whose data would be written. It runs
    # before the Grade 8 plan lookup below, so a student without consent is
    # refused for consent, never told about a plan.
    if not is_demo_code:
        await consent.require_collection(db, req.session_config.student_name)

    # Keep stored plans readable/editable while a release is disabled. Reject
    # teaching before starting a stream or contacting any model provider.
    # The saved plan is loaded only for a Grade 8 turn (the request claims the
    # Grade 8 curriculum, or asks for one of its three course subjects), so an
    # ordinary lesson makes no extra lookup and behaves exactly as before.
    from services.grade8_curriculum_service import enabled as grade8_enabled, authoritative_config
    from services.upper_curriculum_service import enabled as upper_enabled
    upper_turn = bool(req.session_config.upper_curriculum)
    grade8_turn = (bool(req.session_config.grade8_curriculum) or upper_turn
                   or req.current_subject in _GRADE8_ONLY_SUBJECTS)
    if role in ("child", "parent") and (grade8_enabled() or upper_enabled()) and grade8_turn:
        from routers.pod import get_student_config
        try:
            saved = await get_student_config(req.session_config.student_name, auth=auth, db=db)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            raise HTTPException(
                status_code=409,
                detail="The Grade 8 plan changed or was not saved; reload Parent Setup",
            ) from exc
        try:
            req.session_config = authoritative_config(req.session_config, saved, req.current_subject)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    if req.current_subject in _GRADE8_ONLY_SUBJECTS and (
        not (req.session_config.grade8_curriculum or req.session_config.upper_curriculum)
        or req.current_subject not in req.session_config.subjects
    ):
        raise HTTPException(status_code=403, detail="This course subject is not enabled in the adult-selected plan.")
    if req.session_config.grade8_curriculum and not grade8_enabled():
        raise HTTPException(status_code=409, detail="The Grade 8 curriculum has not been activated by the operator.")
    if req.session_config.upper_curriculum and not upper_enabled():
        raise HTTPException(status_code=409, detail="The Grades 9-12 curriculum has not been activated by the operator.")

    if role in ("child", "parent") and req.session_config.grade_stage == GradeStage.foundations:
        # K-2 practice: the per-child setting comes from the SAVED config,
        # never the tablet's copy, so a parent's change mid-session (to "off"
        # or "only sets I approved") stops offers on the next turn. Only this
        # one field is taken; everything else in the turn's config is as sent.
        # Read only on a foundations-stage turn, the only kind the offer gate
        # can allow; a tablet claiming an older grade gets no offer, and the
        # practice routes still take the grade from the saved config.
        from routers.k2_practice import saved_practice_offers
        req.session_config = req.session_config.model_copy(update={
            "practice_offers": await saved_practice_offers(db, req.session_config.student_name),
        })

    demo_quota_exceeded = False
    if is_demo_code:
        demo_code = auth.get("code", "")
        # The actual LLM10 enforcement point (see core/demo_code_session.py's
        # _MAX_MESSAGES_PER_CODE) — checked BEFORE record_message increments,
        # so an over-quota turn is never double-counted and never reaches
        # stream_tutor_response below, i.e. no model call is spent refusing it.
        if await demo_code_has_message_quota(demo_code):
            await demo_code_record_message(demo_code)
        else:
            demo_quota_exceeded = True

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

    async def _trigger_safeguarding(trigger_excerpt: str, detail_prefix: str = "trigger",
                                    picture: str | None = None, dedupe_source: str | None = None) -> None:
        await log_event(
            AuditEvent.SAFEGUARDING,
            role=auth.get("role"),
            student_name=req.session_config.student_name,
            success=True,
            detail=f"{detail_prefix}:{trigger_excerpt}",
            **audit_from_request(request),
        )
        # Fire-and-forget: the child's safety response must not wait on a
        # network round-trip to Resend. The audit entry above is the durable
        # record whatever happens to the email. safeguarding_alerts routes it
        # (the parent, or the school's own route in school mode), sends it
        # once even if the client retries the turn, and audits the outcome.
        asyncio.create_task(safeguarding_alerts.deliver(
            role=auth.get("role"),
            student_name=req.session_config.student_name,
            display_name=req.session_config.display_name,
            trigger_excerpt=trigger_excerpt,
            dedupe_source=dedupe_source if dedupe_source is not None else req.child_message,
            picture=picture,
            audit=audit_from_request(request),
        ))

    async def event_generator():
        # The checks above ran queries, so this request's session holds a
        # pool connection. Return it before the moderation call and the
        # streamed reply, which are the long waits (docs/CAPACITY.md).
        await release_idle_connection(db)
        if demo_quota_exceeded:
            await log_event(
                AuditEvent.RATE_LIMITED,
                role=role,
                student_name=req.session_config.student_name,
                success=False,
                detail="demo_message_quota",
                **audit_from_request(request),
            )
            yield json.dumps({'type': 'text', 'content': demo_quota_response(auth.get("locale", "en"))})
            yield json.dumps({'type': 'done'})
            return

        # Deterministic safeguarding check — bypasses LLM entirely for crisis
        # signals, free and zero-latency, so it runs before paying for a
        # moderation classification call at all.
        if check_safeguarding(req.child_message):
            await _trigger_safeguarding(req.child_message[:80])
            yield json.dumps({'type': 'text', 'content': safeguarding_response(auth.get("locale", "en"))})
            yield json.dumps({'type': 'done'})
            return

        # AIUC-1 B005 — automated moderation classifier, broader than the
        # regex above (any language, indirect phrasing, content categories
        # no fixed phrase list enumerates). classify_child_message() already
        # fails open internally (services/moderation.py) — this second,
        # router-level guard is deliberate belt-and-suspenders: a turn must
        # never fail to reach the child just because a classifier call had
        # an unexpected failure mode its own try/except didn't anticipate.
        try:
            moderation = await classify_child_message(req.child_message, req.session_config.student_name)
        except Exception:
            log.warning("Moderation classifier call failed at the router level — failing open", exc_info=True)
            moderation = {"flagged": False, "categories": [], "confidence": "low", "should_block": False}
        if moderation["flagged"]:
            await log_event(
                AuditEvent.MODERATION_FLAGGED,
                role=auth.get("role"),
                student_name=req.session_config.student_name,
                success=True,
                detail=(
                    f"categories={','.join(moderation['categories'])} "
                    f"confidence={moderation['confidence']} blocked={moderation['should_block']}"
                ),
                **audit_from_request(request),
            )
        if moderation["should_block"]:
            if "self_harm" in moderation["categories"]:
                # Same crisis path as the regex above — a broader net for
                # the same kind of signal, not a different kind of response.
                await _trigger_safeguarding(req.child_message[:80], detail_prefix="trigger(moderation)")
                yield json.dumps({'type': 'text', 'content': safeguarding_response(auth.get("locale", "en"))})
            else:
                yield json.dumps({'type': 'text', 'content': moderation_redirect_response(auth.get("locale", "en"))})
            yield json.dumps({'type': 'done'})
            return

        # Policy Engine — the second stage of the adversarial-resilience
        # pipeline (services/policy_engine.py). Reuses this same `moderation`
        # result (no second classifier call) plus a free Tier 1 regex pass
        # (services/adversarial_detection.py) to catch jailbreak/policy-
        # override/data-exfiltration/social-engineering framing the original
        # five moderation categories above don't cover. Only reached once a
        # turn has already survived safeguarding + the original moderation
        # block, so this can never widen what those two already redirect.
        signals = build_signals(req.child_message, moderation)
        policy = decide_policy(signals)
        if policy.detected_categories:
            await log_event(
                AuditEvent.ADVERSARIAL_DETECTED,
                role=auth.get("role"),
                student_name=req.session_config.student_name,
                success=True,
                detail=(
                    f"categories={','.join(sorted(policy.detected_categories))} "
                    f"blocked={policy.should_redirect}"
                ),
                **audit_from_request(request),
            )
        if policy.should_redirect:
            yield json.dumps({'type': 'text', 'content': moderation_redirect_response(auth.get("locale", "en"))})
            yield json.dumps({'type': 'done'})
            return

        # A lesson photo or canvas drawing is checked before the turn reaches
        # the tutor (services/content_screen.py), with the same client the
        # tutor uses, so the picture goes nowhere it was not already going.
        # It fails closed: a check that cannot run refuses the picture.
        # A picture showing self-harm or sexual content (in any style, a
        # cartoon included) takes the same crisis path as a child writing
        # about self-harm: the parent is emailed straight away.
        # Before that, the file itself is checked, virus-scanned when the
        # household runs a scanner, and rebuilt from its pixels
        # (services/file_safety.py); only the rebuilt picture goes further.
        picture = req.drawing_image
        if picture:
            picture, refusal = await _check_lesson_file(picture, auth.get("locale", "en"))
            if refusal is not None:
                yield json.dumps({'type': 'text', 'content': refusal})
                yield json.dumps({'type': 'done'})
                return
        if picture:
            refusal, crisis = await _screen_lesson_picture(
                picture, auth, req.session_config.student_name, request)
            if crisis:
                await _trigger_safeguarding(f"[picture: {crisis}]", detail_prefix="trigger(picture)",
                                            picture=crisis, dedupe_source=req.drawing_image)
            if refusal is not None:
                yield json.dumps({'type': 'text', 'content': refusal})
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
            chunks = with_stall_timeout(
                stream_tutor_response(
                    config=req.session_config,
                    subject=req.current_subject,
                    history=req.conversation_history,
                    child_message=req.child_message,
                    db=db,
                    drawing_image=picture,
                    demo_code=auth.get("code") if is_demo_code else None,
                    time_of_day=req.local_time_of_day,
                    previous_subject=req.previous_subject,
                    local_date=req.local_date,
                    locale=auth.get("locale", "en"),
                    role=role,
                    session_id=req.session_id,
                    time_remaining_seconds=req.time_remaining_seconds,
                    # One attempt of a retried turn records the child's work;
                    # the others answer and record nothing (turn_replay.py).
                    evidence_gate=turn_replay.gate_for(
                        f"{role}:{auth.get('code') if is_demo_code else req.session_config.student_name}",
                        req.turn_id,
                    ),
                    **audit_from_request(request),
                ),
                timeout_seconds=STREAM_STALL_TIMEOUT_SECONDS,
            )
            if tutor_ctx is not None:
                chunks = pilot_authz.guarded_stream(
                    chunks, tutor_ctx, stage="tutor", request_ctx=audit_from_request(request),
                )
            async for chunk in chunks:
                yield chunk
        except pilot_authz.AuthzRevoked:
            # The grant stopped holding mid-turn. Generation is already
            # cancelled and the revocation audited (pilot_authz). Nothing
            # protected follows: the stream simply ends.
            yield json.dumps({'type': 'done'})
        except asyncio.TimeoutError:
            log.warning(
                "Tutor stream stalled past %.0fs for %s — closing with a recoverable error",
                STREAM_STALL_TIMEOUT_SECONDS, learner_ref(req.session_config.student_name),
            )
            # See core/audit.py's AI_BACKEND_FAILURE / _GLOBAL_ANOMALY_EVENTS —
            # a repeated pattern here (pooled across every device, not just
            # this one) is what actually tells a parent/operator Bede's AI
            # backend is unhealthy, rather than that surfacing only as a
            # string of individually-unremarkable "try again" replies with
            # nobody watching. Fire-and-forget: must not delay the error
            # response the child is waiting on.
            log_event_nowait(
                AuditEvent.AI_BACKEND_FAILURE,
                role=role, student_name=req.session_config.student_name,
                success=False, detail=f"cause=stall subject={req.current_subject.value}",
                **audit_from_request(request),
            )
            yield json.dumps({
                'type': 'text',
                'content': "Sorry, that took too long to come through. Could you try sending that again?",
            })
            yield json.dumps({'type': 'done'})
        except Exception as exc:
            # Child-facing path: log the exception's type and location only.
            # log.exception() would write its message and traceback, and the
            # message can carry the child's own words (COPPA readiness C-16).
            log.error(
                "Tutor stream failed mid-turn for %s: %s",
                learner_ref(req.session_config.student_name), exc_summary(exc),
            )
            # Every provider refused (no credit, a rate limit, a plan without
            # the model): say so plainly and record each provider's reason,
            # so the alert and the audit log name what to fix.
            refusals = adapter_router.provider_failures(exc)
            reasons = (
                " providers=" + ",".join(f"{name}:{code}" for name, code in refusals)
                if refusals else ""
            )
            log_event_nowait(
                AuditEvent.AI_BACKEND_FAILURE,
                role=role, student_name=req.session_config.student_name,
                success=False,
                detail=(
                    f"cause=exception subject={req.current_subject.value} "
                    f"{backend_failure_detail(exc)}{reasons}"
                ),
                **audit_from_request(request),
            )
            yield json.dumps({
                'type': 'text',
                'content': (
                    ai_unavailable_response(auth.get("locale", "en")) if refusals
                    else "Something went wrong on my end. Could you try sending that again?"
                ),
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
    # The file is checked against its kind and virus-scanned when the
    # household runs a scanner (services/file_safety.py) before any text is
    # pulled out of it.
    ext = req.filename.rsplit(".", 1)[-1].lower() if "." in req.filename else ""
    try:
        raw = base64.b64decode(req.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not read that file")
    try:
        await file_safety.narration_file(raw, ext)
    except file_safety.FileRejected as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except (file_safety.ScannerUnavailable, file_safety.UploadBusy) as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    try:
        text = extract_narration_text(req.filename, req.content_base64)
    except UnsupportedNarrationFileError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"text": _sanitize_parent_field(text, max_len=2000) or ""}


@router.get("/voice")
async def voice_status(auth: dict = Depends(require_auth)) -> dict:
    """Whether Bede has a voice on this deployment, whether it runs on this
    computer ("local") or a cloud service ("cloud"), and whether it can speak
    right now in the session's language ("available"). Parent Setup shows it;
    the chat uses "available" so a practice round serves only items a child
    can do on screen when Bede cannot speak. With no voice, or a voice that is
    down, Bede continues without narration and never uses the browser's own
    voice (docs/DECISIONS.md entry 46). Names no provider, credential or
    address, and sends no text anywhere."""
    provider = active_provider()
    return {"configured": provider is not None,
            "where": {"local": "local", "openai": "cloud"}.get(provider or ""),
            "reason": unconfigured_reason(),
            "available": await voice_available(auth.get("locale") or settings.locale)}


@router.post("/speak")
async def speak(req: SpeakRequest, auth: dict = Depends(require_auth)):
    """
    Synthesize Bede's spoken voice: the local voice, or OpenAI's, whichever
    this deployment is set to (services/voice_synthesis.py). Returns 204 with
    no body when synthesis fails or no voice is configured, and the frontend
    stays silent: it never substitutes the browser's own voice.

    The X-TTS-Configured header says whether Bede has a voice at all here,
    so the frontend can tell "no voice on this deployment" from "this line
    failed". The line is spoken in the session's own locale (the JWT's).

    Uses require_auth (not require_real_user) so the scoped demo role can
    reach this too — unlike catalog/pod/narration/transcripts/voice, this
    endpoint reads no student data and writes nothing; it's the same
    ephemeral speak-this-line trade the demo already makes for /chat.
    """
    spoken = await synthesize_speech(req.text, locale=auth.get("locale") or settings.locale)
    headers = {"X-TTS-Configured": str(synthesis_configured())}
    if spoken is None:
        return Response(status_code=204, headers=headers)
    return Response(content=spoken.audio, media_type=spoken.media_type, headers=headers)


@router.post("/summary")
async def session_summary(
    req: SessionSummaryRequest,
    request: Request,
    auth: dict = Depends(require_parent),   # parent only
    db: AsyncSession = Depends(get_db),
):
    """Generate end-of-session parent report. Parent role required."""
    await log_event(
        AuditEvent.SESSION_END,
        role="parent",
        student_name=req.session_config.student_name,
        detail=f"duration={req.duration_minutes}min",
        **audit_from_request(request),
    )
    summary = await generate_session_summary(req, locale=auth.get("locale", "en"), db=db)
    return {"summary": summary}


@router.post("/email-summary")
async def email_summary(
    req: EmailSummaryRequest,
    request: Request,
    auth: dict = Depends(require_email_summary),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate the same end-of-session summary as /summary, then email it once
    to a parent-supplied address via Resend — never shown to the child, never
    written anywhere (see services/email_service.py). Available to the parent
    role and the scoped public demo role; a child may not send mail to an
    arbitrary address, and the transient roles aren't parents either.

    That restriction used to be an inline `role not in ("parent",
    "demo_code")` check in this function body — a real authorization
    decision living outside the dependency layer, invisible to anyone
    auditing authorization by reading core/deps.py. It's now the
    "tutor.email_summary" action in core/policy.py's table, enforced by
    require_email_summary.

    The demo role is additionally capped to exactly one send per session
    (core/demo_code_session.claim_email_send) — the public demo shouldn't
    let one visitor spam an address or run up the operator's Resend usage.
    That cap is a quota, not an authorization decision, so it stays here.
    """
    role = auth.get("role")
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

    # db only for the real parent role — never demo_code, whose student_name
    # isn't guaranteed isolated from a real family's and whose evidence never
    # lands in the real diagnostic_evidence_log table anyway (see
    # generate_session_summary's own docstring on this same gate).
    summary = await generate_session_summary(
        req, locale=auth.get("locale", "en"), db=db if role == "parent" else None,
    )
    html_body = build_summary_email_html(req.session_config.display_name, summary)
    sent = await send_email(
        to_address=req.email,
        subject="Bede's notes from today's session",
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
