"""
Demo-only adapter between the diagnostic engine (services/diagnostic/) and
the demo's single-session code store (core/demo_code_session.py).

Deliberately NOT the production integration described in
docs/diagnostic/DIAGNOSTIC_ENGINE_DESIGN.md §7-§9 (that path is db-backed
via services.diagnostic.process_evidence into the production
mastery_profiles table, persists indefinitely across sessions, and keys
off a real student_name). This module exists because the demo's scope for
this feature is a single-session preview only: evidence recorded during
one demo code's session builds a MasteryVector that lives exactly as long
as that code does (core/demo_code_session.py's own DemoCodeSession row and
its normal TTL/eviction rules — Postgres-backed like everything else in
that module now, but still its own separate table, never
mastery_profiles) and is gone forever the moment it expires or the
visitor logs out — never seen across two different codes. Production
(homeschool-tutor, the parent/child roles) is untouched by this module
entirely.
"""

from services.diagnostic import apply_evidence
from services.diagnostic.mastery import build_summary_view, calibration_weight_for, new_vector

from core.demo_code_session import (
    get_mastery_evidence_count,
    get_mastery_vector,
    set_mastery_vector,
)

# Total evidence points (not per-skill — Phase 2 only persists a single
# scalar count, see DIAGNOSTIC_BUILD_PROGRESS.md's Phase 2 decisions log)
# below which the session is still "getting to know" the visitor. A demo
# session is short by nature, so this is a small number by design, not a
# tuned production constant — see design doc §8.3 for the (still
# unresolved for production) per-skill framing this deliberately simplifies.
CALIBRATION_THRESHOLD = 5


async def record_skill_evidence_demo(
    code: str,
    grade_band: str,
    probe_id: str,
    outcome: str,
    confidence: float = 1.0,
) -> None:
    """Demo-scoped equivalent of services.diagnostic.process_evidence —
    cold-starts a vector for this code if it doesn't have one yet, applies
    one observation, and stores the result back onto the same code's
    DemoCodeSession row (never mastery_profiles). An unknown probe_id is a
    true no-op (apply_evidence returns no updates), matching
    process_evidence's own contract. Never raises — a diagnostic hiccup
    must not break the child's tutoring turn.

    calibration_weight decays with this code's own evidence count so far
    (mastery.calibration_weight_for(), parameterized by this module's own,
    separately-declared CALIBRATION_THRESHOLD above — which happens to
    also be 5 right now, but is not imported from production and is free
    to diverge, per that constant's own docstring) — matching
    process_evidence's real-backend behavior, not just this module's own
    calibration banner in get_mastery_summary_demo below."""
    vector = await get_mastery_vector(code)
    evidence_count_before = await get_mastery_evidence_count(code)
    if vector is None:
        vector = new_vector(grade_band)

    updated_vector, updates = await apply_evidence(
        vector, probe_id, outcome, confidence,
        calibration_weight=calibration_weight_for(evidence_count_before, CALIBRATION_THRESHOLD),
    )
    if not updates:
        return

    await set_mastery_vector(code, updated_vector, evidence_count_before + 1)


async def get_mastery_summary_demo(code: str, student_name: str, subject_area: str = "mathematics") -> dict | None:
    """Builds the same shape as models.schemas.MasteryProfileSummary (as a
    plain dict — routers/diagnostic.py constructs the actual Pydantic model
    so a schema mismatch fails loudly there, not silently here), or None if
    this code has no evidence recorded yet. View-building itself lives in
    mastery.build_summary_view, shared with the real db-backed path
    (services.diagnostic.get_mastery_summary) — this function's own job is
    just supplying this backend's session state."""
    vector = await get_mastery_vector(code)
    if vector is None:
        return None

    evidence_count = await get_mastery_evidence_count(code)
    return build_summary_view(
        vector, student_name, subject_area, evidence_count, CALIBRATION_THRESHOLD, _now_iso(),
    )


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ── The demo's own work ledger ──────────────────────────────────────────
#
# Same relationship to services/diagnostic/activity.py that
# record_skill_evidence_demo above has to services.diagnostic: identical
# COMPUTATION, completely different storage. What the visitor sees has to
# be the real card — a demo that shows something the product doesn't do is
# worse than no demo — but what it reads from is one TTL'd, encrypted blob
# scoped to this demo code, deleted on logout and gone within 6 hours
# regardless. Never SkillActivityLog, which is a real family's permanent
# per-student record; a demo visitor's `student_name` is whatever they
# typed at the code screen and is not isolated from a real family's.
#
# WHY THE LEDGER WORKS IN THE DEMO WHEN THE MASTERY VECTOR BARELY DOES.
# The ledger records events, so entry one is as true as entry two hundred —
# there is no estimate waiting to converge and no calibration threshold to
# clear. That is exactly why it is the honest thing to show a visitor in a
# fifteen-minute session, and it is the same reason it is the instrument a
# real family can trust in their first two weeks.

async def record_work_done_demo(
    code: str,
    subject_area: str,
    skill_id: str,
    label: str,
    outcome: str,
    quality: str | None = None,
    distinction: str | None = None,
    speed: str | None = None,
) -> None:
    """Demo-scoped equivalent of services.diagnostic.activity.record_activity.

    Applies the same `incorrect writes no row` refusal by reusing that
    module's own assistance_for_outcome — a missed attempt is not completed
    work in the demo either, and the demo must not be the place that quietly
    turns this into a record of failures. Never raises."""
    from services.diagnostic.activity import assistance_for_outcome
    from models.schemas import (
        WORK_DISTINCTION_LEVELS, WORK_QUALITY_LEVELS, WORK_SPEED_LEVELS,
    )

    assistance = assistance_for_outcome(outcome)
    if assistance is None:
        return

    from core.demo_code_session import append_activity

    await append_activity(code, {
        "skill_id": skill_id,
        "label": label,
        "assistance": assistance,
        "subject_area": subject_area,
        "quality": quality if quality in WORK_QUALITY_LEVELS else None,
        "distinction": distinction if distinction in WORK_DISTINCTION_LEVELS else None,
        "speed": speed if speed in WORK_SPEED_LEVELS else None,
        # Recorded per entry rather than derived from the row's own
        # created_at, since one row holds the whole session's list.
        "at": _now_iso(),
    })


async def get_activity_summary_demo(code: str, student_name: str) -> dict | None:
    """The work ledger for this demo session, or None when nothing has been
    completed yet (so the frontend can show a "keep going" state rather than
    an empty card).

    Runs services.diagnostic.activity.summarize_records — the SAME
    aggregation the real Progress page uses, not a second implementation —
    so every refusal that function makes holds here too: no average, no
    level, no percentage. initiative_signal is likewise the real one."""
    from services.diagnostic.activity import initiative_signal, summarize_records
    from core.demo_code_session import get_activities

    entries = await get_activities(code)
    if not entries:
        return None

    records = [
        (e.get("skill_id") or "", e.get("subject_area") or "", e, e.get("at") or "")
        for e in entries
        if e.get("skill_id")
    ]
    if not records:
        return None

    # since_days is the demo code's own 6-hour lifetime, not a window the
    # visitor picks — there is nothing older than this session to include.
    summary = summarize_records(records, student_name, since_days=1)
    summary["initiative"] = initiative_signal(summary)
    return summary
