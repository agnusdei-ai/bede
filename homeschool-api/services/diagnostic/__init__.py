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

from services.diagnostic.cat import select_next_probes
from services.diagnostic.mastery import MasteryUpdate, MasteryVector, bayesian_update, new_vector
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
