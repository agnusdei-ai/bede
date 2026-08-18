import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from core.audit import AuditEvent, audit_from_request, log_event
from core.database import get_db
from core.demo_code_session import get_personalization
from core.deps import require_demo_preview, require_parent
from core.diagnostic_preview_quota import has_quota, record_use
from models.schemas import DiagnosticChatRequest, MasteryProfileSummary
from services.diagnostic import get_mastery_summary
from services.diagnostic.composition import get_composition_summary
from services.diagnostic.phonics import get_phonics_summary
from services.diagnostic.language_exposure import get_language_summary
from services.diagnostic.literacy import get_literacy_summary
from services.diagnostic_demo import get_mastery_summary_demo

router = APIRouter(prefix="/diagnostic", tags=["diagnostic"])

CONTACT_CTA = "reach out at info@agnusdei.ai"


# The demo-domain restriction here — no separate login, reachable with the
# exact same demo_code token the child's own session already has (like the
# "Ask Bede" sandbox preview), since this is single-session, non-sensitive
# preview data rather than a real family's data, and deliberately NOT
# reachable by parent/child — used to be a local `_require_demo_code`
# helper performing an inline role comparison. It's now the
# "diagnostic.demo_preview" action in core/policy.py's table; the guard
# below composes on top of require_demo_preview, which enforces it.


async def _require_diagnostic_quota(request: Request, auth: dict = Depends(require_demo_preview)) -> dict:
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
    if not await has_quota(ip, code):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "You've used up this demo's diagnostic preview for now. It's meant to give you a "
                "taste, not replace a full account. We'd love to show you the full-featured "
                f"version and our monthly/annual plans. Please {CONTACT_CTA}."
            ),
        )
    return auth


@router.get("/demo/activity")
async def get_demo_activity(
    auth: dict = Depends(require_demo_preview),
) -> dict:
    """
    The work ledger for the current demo session — what this visitor has
    actually finished, in the same shape and with the same refusals as a
    real family's GET /{student_name}/activity above.

    Guarded by require_demo_preview (core/policy.py's
    "diagnostic.demo_preview" action), so it is reachable with the demo
    token and never by parent/child.

    NOT quota-gated, unlike /summary. That endpoint's quota exists because
    a mastery estimate is the demo's expensive, easily-scraped asset; this
    one is a plain aggregation over what this very visitor did minutes ago
    in this very session, costs nothing to compute, and is worthless to
    anyone but them. Making them spend a preview use to see their own work
    would be charging for the receipt.

    404 with the same "nothing yet" contract the sibling endpoint uses, so
    the frontend can show a keep-going state rather than an empty card.

    WHY THE DEMO HAS THIS WHEN IT HAS NO MASTERY HISTORY. The ledger
    records events, not an estimate, so its first entry is as true as its
    two-hundredth — there is no calibration to clear and therefore nothing
    about a fifteen-minute session that makes showing it dishonest. It
    reads from the demo code's own TTL'd encrypted blob
    (core/database.py's DemoCodeActivityLog), deleted on logout and gone
    within 6 hours regardless; never SkillActivityLog, which is a real
    family's permanent record.
    """
    from services.diagnostic_demo import get_activity_summary_demo

    code = auth.get("code", "")
    student_name, _grade = await get_personalization(code)
    summary = await get_activity_summary_demo(code, student_name or "Guest")
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No completed work recorded in this demo session yet. This fills in as "
                "you work through a lesson together."
            ),
        )
    return summary


@router.get("/summary", response_model=MasteryProfileSummary)
async def get_diagnostic_summary(
    request: Request,
    auth: dict = Depends(_require_diagnostic_quota),
) -> MasteryProfileSummary:
    """
    Render-only mastery summary for the current demo session — built
    entirely from that code's own single-session state (services/diagnostic_demo.py),
    never the production mastery_profiles table. 404 until the session has
    actually produced some real math evidence. demo_code-only, so this
    never reaches homeschool-tutor/production data.

    Quota (core/diagnostic_preview_quota.py) is only actually spent below,
    once real evidence exists to show — a 404 (nothing to evaluate yet)
    doesn't burn one of the visitor's uses for nothing.
    """
    code = auth.get("code", "")
    student_name, _grade = await get_personalization(code)
    summary = await get_mastery_summary_demo(code, student_name or "Guest")
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No mastery data yet. This builds up once some math tutoring happens in this demo session.",
        )
    await record_use(audit_from_request(request)["ip"], code)
    await log_event(
        AuditEvent.DIAGNOSTIC_VIEW,
        role="demo_code",
        student_name=student_name,
        success=True,
        **audit_from_request(request),
    )
    return MasteryProfileSummary(**summary)


_SUMMARY_BUILDERS = {
    "mathematics": get_mastery_summary,
    "composition": get_composition_summary,
    "phonics": get_phonics_summary,
    "language_exposure": get_language_summary,
    "literacy": get_literacy_summary,
}


@router.get("/pod/activity")
async def get_pod_activity(
    students: list[str] = Query(default_factory=list),
    since_days: int = 90,
    subject_area: str | None = None,
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    The same ledger across the parent's own students, so a pod can be run
    as a self-managed team: per skill, WHO HAS DONE the work and how often.

    Emits no ranking, no per-student total, and no student ordering — see
    services/diagnostic/activity.pod_activity for why each of those is
    deliberately absent. Parent-only and never surfaced to a child.

    `students` is a REPEATED query parameter (students=Ada&students=Wren),
    capped at the same 10-seat pod limit PodConfigsRequest enforces. It was
    briefly a single comma-separated value, which was wrong: student_name
    is free text a parent types with no character restriction, so a name
    containing a comma split into two students who don't exist and the
    parent silently got a roster missing that child.

    DECLARED BEFORE /{student_name}/activity deliberately: FastAPI matches
    routes in declaration order, so the parameterized path would otherwise
    swallow this one as student_name="pod".
    """
    from services.diagnostic.activity import pod_activity

    names = [n.strip() for n in students if n.strip()][:10]
    if not names:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Name at least one student.",
        )
    return await pod_activity(db, names, min(365, max(1, since_days)), subject_area)


@router.get("/{student_name}/coverage")
async def get_subject_coverage(
    student_name: str,
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Which of this student's scheduled subjects are actually getting taught,
    and when each was last taught.

    Answers a question a parent could not previously ask: a subject
    producing nothing might never have been scheduled, or might have been
    scheduled for six weeks and opened twice. Those need opposite responses
    and nothing could tell them apart — see services/subject_coverage.py.

    Reports the SCHEDULE, never the child. It does not score engagement or
    interest; a subject can go untaught because of the hour, the book, or a
    busy fortnight. Parent-only, like every other route on this router — a
    child shown "you have not done History in three weeks" has been handed a
    reproach.
    """
    from sqlalchemy import select

    from core import student_keys
    from core.database import StudentConfig
    from core.encryption import decrypt_json
    from models.schemas import SessionConfig
    from routers.pod import _config_aad
    from services.subject_coverage import coverage_for_student, to_payload

    row = (await db.execute(
        select(StudentConfig).where(StudentConfig.student_name == student_name)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No saved plan for {student_name} yet.",
        )
    config = SessionConfig(**decrypt_json(
        row.config_enc, _config_aad(student_name), await student_keys.get_existing(db, student_name)
    ))
    coverage = await coverage_for_student(db, student_name, config.subjects)
    return to_payload(coverage)


@router.get("/{student_name}/activity")
async def get_student_activity(
    student_name: str,
    since_days: int = 90,
    subject_area: str | None = None,
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    The work ledger: what this student has actually DONE — counts and
    dates, never a score. Parent-only, like every other route on this
    router.

    Distinct from /summary above on purpose. That endpoint reports inferred
    mastery ("how likely is it they can do X"); this one reports observed
    activity ("what have they finished, and how much help did it take").
    See services/diagnostic/activity.py for why both exist and why this one
    deliberately emits no average, level, or percentage.

    since_days is capped at 365, the same size-capped convention
    GET /admin/audit's limit uses.
    """
    from services.diagnostic.activity import initiative_signal, summarize

    summary = await summarize(db, student_name, min(365, max(1, since_days)), subject_area)
    # The entrepreneurial read, alongside the raw ledger — counts of work
    # done exemplarily, taken beyond the task, and done briskly. Never a
    # verdict on the child; see activity.initiative_signal.
    summary["initiative"] = initiative_signal(summary)
    return summary


@router.get("/{student_name}/plan")
async def get_session_plan(
    student_name: str,
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    How Bede would order today's subjects, and why.

    Parent-only, like every other route on this router, and deliberately so:
    a child shown "Bede put maths first because you haven't done it in a
    while" has been told something about themselves that Bede has no
    standing to say.

    ADVISORY. This endpoint reports an ordering; it does not apply one. The
    plan is always a permutation of the subjects the parent already chose —
    never a subject added, dropped, or shortened — and every entry carries a
    plain-language reason, so the ordering is explained rather than imposed.
    See services/lesson_planner.py for the constitutional limits on what
    this may decide, in particular why faith-formation subjects never move
    on evidence.
    """
    from datetime import datetime, timezone

    from sqlalchemy import select

    from core.database import LessonBookmark, StudentConfig
    from core.encryption import decrypt_json
    from models.schemas import SessionConfig, Subject
    # Imported rather than re-derived: the AAD must match byte-for-byte what
    # routers/pod.py encrypted with, and a second copy of that expression is
    # a silent decryption failure waiting to happen.
    from routers.pod import _config_aad
    from services.lesson_planner import (
        PlanningSignals,
        plan_session,
        stale_subjects_from_bookmarks,
    )

    row = await db.get(StudentConfig, student_name)
    if row is None:
        raise HTTPException(status_code=404, detail="No configuration for that student.")
    config = SessionConfig(**decrypt_json(row.config_enc, _config_aad(student_name)))

    now = datetime.now(timezone.utc)
    ages: dict[Subject, float | None] = {subject: None for subject in config.subjects}
    bookmarks = (
        await db.execute(
            select(LessonBookmark).where(LessonBookmark.student_name == student_name)
        )
    ).scalars().all()
    for bookmark in bookmarks:
        try:
            subject = Subject(bookmark.subject)
        except ValueError:
            # A bookmark for a subject that no longer exists in the enum is
            # simply not a signal — never a reason to fail the request.
            continue
        if subject in ages:
            updated = bookmark.updated_at
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            ages[subject] = (now - updated).total_seconds() / 86400

    plan = plan_session(
        PlanningSignals(
            subjects=list(config.subjects),
            grade_stage=config.grade_stage,
            resume_subjects={entry.subject for entry in (config.lesson_resume or [])},
            stale_subjects=stale_subjects_from_bookmarks(ages),
        )
    )
    return {
        "student_name": student_name,
        "advisory": True,
        "subjects": [
            {"subject": entry.subject.value, "reason": entry.reason}
            for entry in plan.subjects
        ],
    }


@router.get("/{student_name}/summary", response_model=MasteryProfileSummary)
async def get_student_mastery_summary(
    student_name: str,
    request: Request,
    subject_area: str = "mathematics",
    auth: dict = Depends(require_parent),
    db: AsyncSession = Depends(get_db),
) -> MasteryProfileSummary:
    """
    Render-only mastery summary for a real student's REAL, persisted
    profile, never the demo's ephemeral single-session vector above.
    Parent-only (require_parent) — never reachable by the child role,
    matching the design doc's P1 (mastery profile is parent-confidential).
    No quota: unlike the public demo, this is the family's own data behind
    a real login, not a free-tier abuse surface.

    subject_area picks which engine's summary to build — "mathematics"
    (services.diagnostic.get_mastery_summary, the CDM/IRT/KST engine),
    "composition" (services.diagnostic.composition.get_composition_summary,
    a rollup over assess_narration's own rubric), "phonics"
    (services.diagnostic.phonics.get_phonics_summary, K-2 reading
    foundations), or "language_exposure"
    (services.diagnostic.language_exposure.get_language_summary, foreign-
    language check-ins woven into History/Saints/Art & Music — see that
    module's docstring). All four read the same mastery_profiles table
    keyed by (student_name, subject_area), so this one endpoint covers all
    of them without a per-subject route; an unrecognized subject_area 404s
    the same as "no data yet" rather than a separate error shape, since
    from the frontend's perspective both mean nothing to show.

    404 until this student has produced some real evidence in that subject
    — same no-data contract as the demo endpoint above, so the frontend
    can reuse one "nothing here yet" empty state for both.
    """
    builder = _SUMMARY_BUILDERS.get(subject_area)
    summary = await builder(db, student_name) if builder else None
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No mastery data yet. This builds up as tutoring happens in real sessions.",
        )
    await log_event(
        AuditEvent.DIAGNOSTIC_VIEW,
        role="parent",
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
    student_name, _grade = await get_personalization(code)
    summary = await get_mastery_summary_demo(code, student_name or "Guest")
    if summary:
        await record_use(audit_from_request(request)["ip"], code)
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
            "No math evidence has been recorded in this demo session yet. Try working through "
            "a question or two in the Mathematics subject, then come back and check again.\n\n"
            f"This preview shows a snapshot only. Want a real conversation about your child's "
            f"progress, plus full-featured tutoring? We'd love to talk. Please {CONTACT_CTA}."
        )

    lines = [
        f"Here's where {summary['student_name']} stands in {summary['subject_area']} so far "
        f"({summary['evidence_count']} observation{'' if summary['evidence_count'] == 1 else 's'}"
        + (" — early signal, not a settled read" if summary["calibration"] else "") + "):",
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
        f"progress, plus full-featured tutoring? We'd love to talk about our monthly/annual plans. "
        f"Please {CONTACT_CTA}."
    )
    return "\n".join(lines)
