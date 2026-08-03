"""
Composition mastery — a lightweight, DAG-free rollup over assess_narration's
existing 5-dimension rubric (completeness, sequence, detail, language_quality,
synthesis). Reuses the SAME MasteryProfile/DiagnosticEvidenceLog persistence
layer as the math CDM/IRT/KST engine (subject_area="composition" — the
composite PK was explicitly designed for exactly this; see MasteryProfile's
own docstring: "subject_area='reading' is a new row, not a new table"), but
with its own much simpler update rule — see docs/diagnostic/
DIAGNOSTIC_ENGINE_DESIGN.md §13 for the full writeup.

Why not reuse mastery.bayesian_update directly: that pipeline
(cdm.update_attribute_posteriors, kst.propagate_prerequisites) is built
around skill_map.py's K-8 math skill DAG — discrete skills with real
prerequisite edges (multiplication requires addition), probed indirectly
through binary/partial-credit outcomes that need latent-trait (CDM)
modeling to interpret at all. Composition's five dimensions aren't
prerequisite-ordered that way (sequence isn't a prerequisite of
synthesis), and assess_narration already reports a direct 1-5 rating per
dimension on every call — a much more direct signal than math's probe
outcomes, so a simple calibrated blend toward the observed score is the
honest model here, not an under-used CDM/KST machine built for a
different evidence shape.

Deliberately does NOT track handwriting/drawing mechanics (letter
formation, penmanship) — per this app's own pedagogy (the nature-study
subject context's own rule: "Never correct the drawing; accuracy comes
with practice over the weeks, not correction today"), only the THINKING
behind a narration is ever assessed, spoken or written alike. This
mirrors assess_narration's own scope exactly; it is not a claim that
handwriting itself doesn't matter, just that this engine isn't where it
would be scored.

Fed by every assess_narration call regardless of subject — oral or
written, across every subject Bede tutors — not gated to invite_
handwriting submissions specifically. Charlotte Mason narration and
written composition are one continuous skill in this app's own pedagogy
(see services/ai_service.py's _STAGE_GUIDANCE: "the child who has
learned to render a thing aloud now begins the transition to written
narration"), so tracking mastery from the full narration stream — not
just written submissions — is both truer to that pedagogy and reaches a
usable read far faster: assess_narration already fires regularly, so
CALIBRATION_THRESHOLD can honestly sit much lower than math's.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from services.diagnostic.mastery import calibration_weight_for, classify_level

log = logging.getLogger(__name__)

MasteryVector = dict[str, float]

# Two assess_narration calls, not five — each call already carries five
# dimensions of direct, explicit signal at once (versus math's one
# probe = one skill), so a usable first read arrives much sooner. Still a
# placeholder in the same spirit as mastery.CALIBRATION_THRESHOLD's own
# "[to verify final N]" flag — not yet tuned against real sessions.
CALIBRATION_THRESHOLD = 2

DOMAINS: tuple[str, ...] = ("completeness", "sequence", "detail", "language_quality", "synthesis")

# assess_narration's own tool-schema descriptions (services/ai_service.py),
# reworded for a parent audience rather than Bede's own scoring instructions.
DOMAIN_LABELS: dict[str, str] = {
    "completeness": "Covers the Main Ideas",
    "sequence": "Logical Order",
    "detail": "Richness of Detail",
    "language_quality": "Own Words & Voice",
    "synthesis": "Connects to Prior Learning",
}


def new_vector() -> MasteryVector:
    """Cold start: flat 0.5 across all five dimensions. Composition domains
    aren't grade-differentiated the way math skill bands are — a young
    child's narration is judged on the SAME five dimensions as an older
    child's, just against different expectations Bede itself already holds
    via GradeStage-aware prompting. This vector tracks relative growth
    within that expectation, not an absolute grade-leveled skill, so there's
    no analog to mastery.new_vector's grade_band distance logic."""
    return {domain: 0.5 for domain in DOMAINS}


@dataclass
class CompositionUpdate:
    domain: str
    prior: float
    posterior: float
    observed_at: str


def apply_assessment(
    vector: MasteryVector,
    scores: dict,
    calibration_weight: float = 1.0,
) -> tuple[MasteryVector, list[CompositionUpdate]]:
    """
    One assess_narration call's worth of evidence: each present 1-5 score is
    normalized to [0,1] ((score-1)/4) and blended toward the prior by
    calibration_weight, mirroring mastery.bayesian_update's own blend
    formula exactly (prior + weight*(observed-prior), clamped to [0,1]) —
    same shape, simpler input, no CDM/KST step needed. A domain missing
    from `scores` (assess_narration's five rubric fields are all required
    by its own tool schema, but this stays defensive against a malformed
    call) is left untouched and produces no CompositionUpdate for that
    domain.
    """
    updated = dict(vector)
    updates: list[CompositionUpdate] = []
    observed_at = datetime.now(timezone.utc).isoformat()

    for domain in DOMAINS:
        raw = scores.get(domain)
        if not isinstance(raw, (int, float)):
            continue
        observed = max(0.0, min(1.0, (raw - 1) / 4))
        prior = vector.get(domain, 0.5)
        blended = prior + calibration_weight * (observed - prior)
        blended = max(0.0, min(1.0, blended))
        updated[domain] = blended
        updates.append(CompositionUpdate(domain=domain, prior=prior, posterior=blended, observed_at=observed_at))

    return updated, updates


def build_summary_view(
    vector: MasteryVector,
    student_name: str,
    evidence_count: int,
    updated_at: str,
) -> dict:
    """
    Builds a MasteryProfileSummary-shaped dict (models.schemas.
    MasteryProfileSummary — the exact same Pydantic response model math's
    get_mastery_summary returns, so routers/diagnostic.py and the frontend
    need no composition-specific shape). One pseudo-"skill" per domain
    (skill_id="composition.<domain>") since SkillMasteryView expects a
    skill/domain pair — composition's domains ARE the finest grain this
    engine tracks, so skill and domain collapse to the same thing here.
    grade_band is left "" (SkillMasteryView requires the field, but
    composition doesn't band by grade — see new_vector's own docstring).
    """
    domains = []
    gaps = []
    for domain in DOMAINS:
        probability = vector.get(domain, 0.5)
        level = classify_level(probability)
        label = DOMAIN_LABELS[domain]
        skill_view = {
            "skill_id": f"composition.{domain}",
            "label": label,
            "domain": label,
            "grade_band": "",
            "probability": probability,
            "level": level,
        }
        domains.append({
            "domain": label,
            "average_probability": probability,
            "level": level,
            "skills": [skill_view],
        })
        if level == "gap":
            gaps.append(skill_view)

    # "Next steps" without a KST fringe to draw on: the domains furthest
    # from secure, worst first — same spirit as math's fringe() (what's
    # worth attending to next), computed directly since there's no
    # prerequisite graph to walk.
    all_skill_views = [d["skills"][0] for d in domains]
    next_steps = sorted(
        (v for v in all_skill_views if v["level"] != "secure"),
        key=lambda v: v["probability"],
    )[:3]

    return {
        "student_name": student_name,
        "subject_area": "composition",
        "evidence_count": evidence_count,
        "calibration": evidence_count < CALIBRATION_THRESHOLD,
        "domains": domains,
        "gaps": gaps,
        "next_steps": next_steps,
        "updated_at": updated_at,
    }


async def process_assessment(db, student_name: str, scores: dict) -> Optional[MasteryVector]:
    """
    The persistence-backed entry point — mirrors services.diagnostic.
    __init__.process_evidence's load/update/store shape exactly, but against
    MasteryProfile(subject_area="composition") and this module's simpler
    apply_assessment instead of the math engine's bayesian_update. Called
    from ai_service.py's _save_assessment on every assess_narration call,
    alongside (not instead of) the existing NarrationAssessment save —
    best-effort: a failure here must never break narration assessment
    itself, so every exception is caught and logged, never raised.

    Returns the updated vector, or None if nothing was persisted (a
    malformed tool call with no usable scores, or a persistence failure).
    """
    from sqlalchemy import select

    from core.database import MasteryProfile
    from core.encryption import decrypt_json, encrypt_json, student_aad
    from core import student_keys

    row = None
    vector_is_cold_start = False

    try:
        result = await db.execute(
            select(MasteryProfile).where(
                MasteryProfile.student_name == student_name,
                MasteryProfile.subject_area == "composition",
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            vector = new_vector()
            vector_is_cold_start = True
        else:
            vector = decrypt_json(
                row.profile_enc,
                student_aad("mastery_profiles", "profile_enc", student_name, "composition"),
                await student_keys.get_existing(db, student_name),
            )
    except Exception as exc:
        log.warning(
            "Composition mastery load failed for %s, treating as cold-start: %s", student_name, exc,
        )
        vector = new_vector()
        vector_is_cold_start = True

    evidence_count_before = 0 if vector_is_cold_start else row.evidence_count
    updated_vector, updates = apply_assessment(
        vector, scores, calibration_weight=calibration_weight_for(evidence_count_before, CALIBRATION_THRESHOLD),
    )

    if not updates:
        await db.rollback()
        return None

    try:
        profile_enc = encrypt_json(
            updated_vector,
            student_aad("mastery_profiles", "profile_enc", student_name, "composition"),
            await student_keys.get_or_create(db, student_name),
        )
        if row is None:
            db.add(MasteryProfile(
                student_name=student_name,
                subject_area="composition",
                evidence_count=1,
                profile_enc=profile_enc,
            ))
        else:
            row.profile_enc = profile_enc
            row.evidence_count += 1
        await db.commit()
    except Exception as exc:
        await db.rollback()
        log.warning("Composition mastery persist failed for %s: %s", student_name, exc)
        return None

    return updated_vector


async def get_composition_summary(db, student_name: str) -> Optional[dict]:
    """
    Render-only parent summary of a student's composition mastery —
    mirrors services.diagnostic.__init__.get_mastery_summary exactly
    (same defensive load, same None-on-missing/corrupt-row contract so
    routers/diagnostic.py's 404 handling needs no composition-specific
    branch beyond which builder function it calls).
    """
    from sqlalchemy import select

    from core.database import MasteryProfile
    from core.encryption import decrypt_json, student_aad
    from core import student_keys

    try:
        result = await db.execute(
            select(MasteryProfile).where(
                MasteryProfile.student_name == student_name,
                MasteryProfile.subject_area == "composition",
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        vector = decrypt_json(
                row.profile_enc,
                student_aad("mastery_profiles", "profile_enc", student_name, "composition"),
                await student_keys.get_existing(db, student_name),
            )
    except Exception as exc:
        log.warning("Composition mastery summary load failed for %s: %s", student_name, exc)
        return None

    return build_summary_view(
        vector, student_name, row.evidence_count, row.updated_at.replace(microsecond=0).isoformat(),
    )
