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
