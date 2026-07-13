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
from services.diagnostic.mastery import _classify, aggregate_for_parent, calibration_weight_for, new_vector
from services.diagnostic.skill_map import get_skill

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
    this code has no evidence recorded yet."""
    vector = await get_mastery_vector(code)
    if vector is None:
        return None

    rollup = aggregate_for_parent(vector)

    def _skill_view(skill_id: str) -> dict | None:
        skill = get_skill(skill_id)
        if skill is None:
            return None
        probability = vector[skill_id]
        return {
            "skill_id": skill_id,
            "label": skill.label,
            "domain": skill.domain,
            "grade_band": skill.band.value,
            "probability": probability,
            "level": _classify(probability),
        }

    domains = []
    for domain, info in rollup["domains"].items():
        domain_skill_ids = sorted(
            (skill_id for skill_id in vector if (s := get_skill(skill_id)) is not None and s.domain == domain),
            key=lambda skill_id: vector[skill_id],
        )
        domains.append({
            "domain": domain,
            "average_probability": info["average_probability"],
            "level": info["level"],
            "skills": [v for skill_id in domain_skill_ids if (v := _skill_view(skill_id)) is not None],
        })

    evidence_count = await get_mastery_evidence_count(code)
    return {
        "student_name": student_name,
        "subject_area": subject_area,
        "evidence_count": evidence_count,
        "calibration": evidence_count < CALIBRATION_THRESHOLD,
        "domains": domains,
        "gaps": [v for skill_id in rollup["gaps"] if (v := _skill_view(skill_id)) is not None],
        "next_steps": [v for skill_id in rollup["next_steps"] if (v := _skill_view(skill_id)) is not None],
        "updated_at": _now_iso(),
    }


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
