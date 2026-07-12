"""
Bede Diagnostic Engine — pure-Python CDM/IRT/KST core.

See docs/diagnostic/DIAGNOSTIC_ENGINE_DESIGN.md for the full design and
docs/diagnostic/DIAGNOSTIC_LOOP.md for the runtime S1-S9 loop this
package implements, tracked unit by unit in
docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md.

This is the public façade — process_evidence and get_next_probe_hint —
composing skill_map/qmatrix/irt/cdm/kst/mastery into the two entry points
the rest of bede is meant to call.

Phase 1 scope note (unit 1.8): the design doc's §4.8 spec for
process_evidence takes `db` and does "encrypt+persist" — but Phase 1's
hard rule is no DB at all, and Phase 2's own unit 2.2 repeats the
identical "load->update->encrypt->store" phrase as its own deliverable.
So this is the in-memory façade: it operates on a MasteryVector directly,
not a database row. Phase 2 adds the real db-load -> this -> encrypt+store
wrapper around this same bayesian_update core, matching the design doc's
full db-taking signature at that point — not duplicating this logic.
"""

from services.diagnostic.cat import select_next_probes
from services.diagnostic.mastery import MasteryUpdate, MasteryVector, bayesian_update
from services.diagnostic.qmatrix import EvidenceObservation, Q_MATRIX


async def process_evidence(
    vector: MasteryVector,
    probe_id: str,
    outcome: str,
    confidence: float = 1.0,
    calibration_weight: float = 1.0,
    model: str = "dina",
) -> tuple[MasteryVector, list[MasteryUpdate]]:
    """
    In-memory evidence-processing entry point (see module docstring for
    why this doesn't take `db` yet). Builds the EvidenceObservation from
    primitive params and delegates to mastery.bayesian_update — this
    function's whole job is to be the one stable call site Phase 2's
    real database-backed version wraps, and Phase 3's
    _record_skill_evidence tool handler calls, without either of those
    needing to know the CDM/KST internals directly.

    async even though nothing here awaits anything yet: Phase 2 will add
    real I/O (a DB load before this, an encrypted store after), and every
    caller should already be written against an awaitable so that change
    doesn't ripple through call sites later.
    """
    observation: EvidenceObservation = {
        "probe_id": probe_id,
        "outcome": outcome,
        "confidence": confidence,
    }
    return bayesian_update(vector, observation, calibration_weight=calibration_weight, model=model)


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
