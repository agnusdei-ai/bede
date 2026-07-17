"""
Bede Diagnostic Engine — pure-Python CDM/IRT/KST core.

See docs/diagnostic/DIAGNOSTIC_ENGINE_DESIGN.md for the full design and
docs/diagnostic/DIAGNOSTIC_LOOP.md for the runtime S1-S9 loop this
package implements, tracked unit by unit in
docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md.

This is the public façade — process_evidence and get_next_probe_hint —
composing skill_map/qmatrix/irt/cdm/kst/mastery into the two entry points
the rest of bede is meant to call.

Phase 2 (unit 2.2): process_evidence is now the real db-backed entry
point matching the design doc's §4.8 signature exactly (db, student_name,
probe_id, outcome, confidence, grade_band) — Phase 3's
_record_skill_evidence handler will call this directly. apply_evidence
(the Phase 1 in-memory step — same body as the old process_evidence) is
kept as its own function: process_evidence calls it internally rather
than duplicating the load->update->encrypt->store logic, and it stays
useful on its own for calibration tooling/tests that don't have `db`.
"""

from datetime import datetime
from typing import Optional

from services.diagnostic.cat import select_next_probes
from services.diagnostic.mastery import (
    CALIBRATION_THRESHOLD,
    MasteryUpdate,
    MasteryVector,
    bayesian_update,
    build_summary_view,
    classify_level,
    new_vector,
)
from services.diagnostic.qmatrix import EvidenceObservation, Q_MATRIX


async def apply_evidence(
    vector: MasteryVector,
    probe_id: str,
    outcome: str,
    confidence: float = 1.0,
    calibration_weight: float = 1.0,
    model: str = "dina",
) -> tuple[MasteryVector, list[MasteryUpdate]]:
    """
    In-memory evidence-processing step. Builds the EvidenceObservation
    from primitive params and delegates to mastery.bayesian_update —
    process_evidence (below) is the one stable call site that wraps this
    with real DB load/encrypt/store; Phase 3's _record_skill_evidence
    tool handler calls process_evidence, not this, in production.
    """
    observation: EvidenceObservation = {
        "probe_id": probe_id,
        "outcome": outcome,
        "confidence": confidence,
    }
    return bayesian_update(vector, observation, calibration_weight=calibration_weight, model=model)


async def process_evidence(
    db,
    student_name: str,
    probe_id: str,
    outcome: str,
    confidence: float,
    grade_band: str,
    subject_area: str = "mathematics",
    model: str = "dina",
) -> MasteryVector:
    """
    The real, persistence-backed entry point (design doc §4.8): load and
    decrypt the student's mastery vector (cold-starting one via
    mastery.new_vector(grade_band) if this is their first evidence for
    subject_area), run it through apply_evidence(), encrypt and store the
    result, and — only when settings.diagnostic_evidence_log_enabled —
    append one DiagnosticEvidenceLog row holding this call's MasteryUpdate
    deltas. Never persists the raw outcome or probe text, only the
    resulting vector and (optionally) the derived deltas.

    calibration_weight (design doc §8.3) is computed internally from the
    existing row's evidence_count — the count of evidence already
    gathered before this call, so it's still 0 (maximum calibration push)
    on a true cold start — via mastery.calibration_weight_for(), not a
    caller-supplied param: nothing in this codebase has ever needed to
    override it, and a settable-but-unused param is exactly the kind of
    dead surface unit 3.1's post-merge review caught once already (see
    that unit's decisions log entry on the dropped grade_band param).

    An unknown probe_id is a true no-op: apply_evidence returns no
    MasteryUpdate, so nothing is written and evidence_count doesn't move
    — a typo'd probe id doesn't cold-start a phantom row.

    Returns the new vector (not None, unlike the design doc's sketch) so
    Phase 3's dispatcher/prompt-injection code can reuse it in the same
    turn without a second DB round trip.

    Defensive like ai_service.py's _save_assessment, which this mirrors:
    a corrupted/undecryptable existing row is treated as a cold start
    (logged, not raised) rather than permanently blocking evidence for
    that student, and a persistence failure still returns the in-memory
    updated vector so a diagnostic hiccup never breaks the child's
    tutoring turn — this function doesn't rely on every future caller
    (e.g. Phase 3's _record_skill_evidence) to supply that protection.
    """
    import logging

    from sqlalchemy import select

    from core.config import settings
    from core.database import DiagnosticEvidenceLog, MasteryProfile
    from core.encryption import decrypt_json, encrypt_json
    from services.diagnostic.mastery import calibration_weight_for

    log = logging.getLogger(__name__)
    row = None
    vector_is_cold_start = False

    try:
        result = await db.execute(
            select(MasteryProfile).where(
                MasteryProfile.student_name == student_name,
                MasteryProfile.subject_area == subject_area,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            vector = new_vector(grade_band)
            vector_is_cold_start = True
        else:
            vector = decrypt_json(row.profile_enc)
    except Exception as exc:
        log.warning(
            "Mastery profile load failed for %s/%s, treating as cold-start: %s",
            student_name, subject_area, exc,
        )
        vector = new_vector(grade_band)
        vector_is_cold_start = True

    # A corrupted row that failed to decrypt gets a fresh vector above —
    # its calibration_weight should reflect that same true cold start
    # (evidence_count effectively 0 for this vector), not the stale
    # row.evidence_count the old, now-unrecoverable vector had earned.
    evidence_count_before = 0 if vector_is_cold_start else row.evidence_count
    updated_vector, updates = await apply_evidence(
        vector, probe_id, outcome, confidence,
        calibration_weight=calibration_weight_for(evidence_count_before), model=model,
    )

    if not updates:
        await db.rollback()
        return updated_vector

    try:
        profile_enc = encrypt_json(updated_vector)
        if row is None:
            db.add(MasteryProfile(
                student_name=student_name,
                subject_area=subject_area,
                evidence_count=1,
                profile_enc=profile_enc,
            ))
        else:
            row.profile_enc = profile_enc
            row.evidence_count += 1

        if settings.diagnostic_evidence_log_enabled:
            # Explicit allowlist, not dataclasses.asdict(update) minus
            # observed_at — this is the one thing standing between a
            # future MasteryUpdate field and it silently landing in the
            # persisted evidence log (design doc §5.3's core guarantee).
            delta_payload = [
                {
                    "skill_id": update.skill_id,
                    "prior": update.prior,
                    "posterior": update.posterior,
                    "probe_id": update.probe_id,
                    "model_used": update.model_used,
                }
                for update in updates
            ]
            db.add(DiagnosticEvidenceLog(
                student_name=student_name,
                subject_area=subject_area,
                delta_enc=encrypt_json(delta_payload),
            ))

        await db.commit()
    except Exception as exc:
        await db.rollback()
        log.warning("Mastery profile persist failed for %s/%s: %s", student_name, subject_area, exc)

    return updated_vector


async def get_mastery_summary(db, student_name: str, subject_area: str = "mathematics") -> Optional[dict]:
    """
    Render-only parent summary of a student's REAL, persisted mastery
    profile (mastery_profiles table) — the production counterpart to
    services/diagnostic_demo.py's get_mastery_summary_demo, which builds
    the identical dict shape (via the shared mastery.build_summary_view)
    from a single demo session's ephemeral vector instead. Returns None
    when no MasteryProfile row exists yet (the student hasn't produced
    any math evidence) or when the row fails to decrypt, matching
    process_evidence's own defensive convention (a corrupted row
    degrades gracefully rather than raising) — routers/diagnostic.py's
    parent endpoint 404s either way, exactly as the demo one does.

    calibration mirrors process_evidence's own calibration_weight_for
    threshold (CALIBRATION_THRESHOLD, imported from mastery.py — the
    same module process_evidence itself already uses) — the picture
    below is flagged as an early signal, not a settled read, until this
    student's own evidence_count reaches it. Unlike the demo, evidence
    keeps accumulating indefinitely across every real session this
    student has, so calibration reflects the WHOLE relationship so far,
    not just today.
    """
    import logging

    from sqlalchemy import select

    from core.database import MasteryProfile
    from core.encryption import decrypt_json

    log = logging.getLogger(__name__)

    try:
        result = await db.execute(
            select(MasteryProfile).where(
                MasteryProfile.student_name == student_name,
                MasteryProfile.subject_area == subject_area,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        vector = decrypt_json(row.profile_enc)
    except Exception as exc:
        log.warning("Mastery summary load failed for %s/%s: %s", student_name, subject_area, exc)
        return None

    return build_summary_view(
        vector, student_name, subject_area, row.evidence_count, CALIBRATION_THRESHOLD,
        row.updated_at.replace(microsecond=0).isoformat(),
    )


async def get_session_growth(
    db, student_name: str, subject_area: str, since: datetime,
) -> list[dict]:
    """
    Deterministic before/after per skill for one session window, built from
    DiagnosticEvidenceLog rows observed since `since` — session start is the
    summary request's own timestamp minus SessionSummaryRequest.duration_minutes
    (see services/ai_service.py's generate_session_summary), so this needs no
    new session-start field anywhere. For each skill_id touched in the
    window: before is the EARLIEST prior seen, after is the LATEST posterior
    — a skill probed several times this session still reports one honest
    start-to-end movement, not just the last delta. Sorted by movement
    (largest gain first).

    Returns [] whenever there's nothing to report: the evidence log is
    disabled (settings.diagnostic_evidence_log_enabled=False, so the table
    is simply empty), no math evidence happened in this window, or the load
    fails outright — this is a parent-report nicety, not something that
    should ever raise into generate_session_summary and break the report.
    """
    import logging

    from sqlalchemy import select

    from core.database import DiagnosticEvidenceLog
    from core.encryption import decrypt_json
    from services.diagnostic.skill_map import get_skill

    log = logging.getLogger(__name__)

    try:
        result = await db.execute(
            select(DiagnosticEvidenceLog)
            .where(
                DiagnosticEvidenceLog.student_name == student_name,
                DiagnosticEvidenceLog.subject_area == subject_area,
                DiagnosticEvidenceLog.observed_at >= since,
            )
            .order_by(DiagnosticEvidenceLog.observed_at)
        )
        rows = result.scalars().all()
    except Exception as exc:
        log.warning("Session growth load failed for %s/%s: %s", student_name, subject_area, exc)
        return []

    before: dict[str, float] = {}
    after: dict[str, float] = {}
    for row in rows:
        try:
            deltas = decrypt_json(row.delta_enc)
        except Exception as exc:
            log.warning("Session growth delta decrypt failed for %s/%s: %s", student_name, subject_area, exc)
            continue
        for delta in deltas:
            skill_id = delta["skill_id"]
            before.setdefault(skill_id, delta["prior"])
            after[skill_id] = delta["posterior"]

    growth = []
    for skill_id, before_probability in before.items():
        skill = get_skill(skill_id)
        if skill is None:
            continue
        after_probability = after[skill_id]
        growth.append({
            "skill_id": skill_id,
            "label": skill.label,
            "domain": skill.domain,
            "before": before_probability,
            "after": after_probability,
            "before_level": classify_level(before_probability),
            "after_level": classify_level(after_probability),
        })

    growth.sort(key=lambda g: g["after"] - g["before"], reverse=True)
    return growth


def get_next_probe_hint(
    vector: MasteryVector,
    theta: dict[str, float],
    grade_band: str,
    calibration: bool,
) -> str:
    """Human-readable one-liner for the subject prompt (design doc §8.2) —
    the prose Phase 3's _build_subject_prompt injection weaves into
    Bede's own context. Never child-facing; this is Bede's own probing
    guidance, not tutoring content."""
    probe_ids = select_next_probes(vector, theta, grade_band, calibration, limit=3)
    descriptions = [
        Q_MATRIX[probe_id].description for probe_id in probe_ids if probe_id in Q_MATRIX
    ]
    if not descriptions:
        return "No specific skills flagged for probing right now — tutor normally."
    return "Consider naturally probing: " + "; ".join(descriptions)
