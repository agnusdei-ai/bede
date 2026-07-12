"""
Computerized Adaptive Testing — probe selection and the stopping rule —
realizes runtime-loop steps S2/S9 (see docs/diagnostic/DIAGNOSTIC_LOOP.md).
Pure stdlib `math`, no numpy, per
docs/diagnostic/DIAGNOSTIC_BUILD_LOOP.md's Phase 1 hard rules.

Naming/signature note: the design doc's §4.6 calls this function
`select_next_probe` (singular) with signature (vector, theta, grade_band,
calibration). DIAGNOSTIC_LOOP.md's own pseudocode and
DIAGNOSTIC_BUILD_PROGRESS.md's unit table both call it
`select_next_probes` (plural) and pass the fringe set F explicitly. This
implementation follows the two documents that agree — plural name,
computing the fringe internally via kst.fringe() rather than requiring
the caller to pass it, since a caller-supplied redundant argument that
must always equal kst.fringe(vector) invites drift.

Ranking uses posterior entropy, not Fisher information, despite the
design doc mentioning both as options ("maximum Fisher information (or
posterior entropy — maximum uncertainty reduction)"): true per-item
Fisher information needs calibrated item difficulty/discrimination (a, b)
parameters, which nothing in this codebase defines for probe archetypes
yet (irt.py, unit 1.3, computes it from parameters a caller must supply —
qmatrix.py's 1:1 probes carry no such calibration). Bernoulli entropy of
the CDM posterior probability itself needs no fabricated parameters and
is maximized at exactly the same point (p=0.5) that Fisher information
is maximized at theta==b — the same "most uncertain, most informative to
probe next" intent, without inventing item statistics nobody has
measured.
"""

import math

from services.diagnostic.kst import fringe
from services.diagnostic.qmatrix import probes_for_skill
from services.diagnostic.skill_map import get_skill, skills_in_band


def _entropy(probability: float) -> float:
    """Bernoulli entropy in bits, maximized at p=0.5 (maximum uncertainty),
    zero at p=0 or p=1 (fully certain)."""
    p = max(1e-9, min(1.0 - 1e-9, probability))
    return -(p * math.log2(p) + (1.0 - p) * math.log2(1.0 - p))


def select_next_probes(
    vector: dict[str, float],
    theta: dict[str, float],
    grade_band: str,
    calibration: bool,
    limit: int = 5,
) -> list[str]:
    """
    Ranked list of probe_ids to prefer for the next turn (highest
    posterior-entropy fringe skills first, flattened to their probe
    archetypes via qmatrix.probes_for_skill).

    Off calibration: prefers fringe skills in the student's own grade
    band; if none are on-band (e.g. everything on-band is already
    mastered), falls back to the full fringe rather than returning
    nothing.

    In calibration mode (design doc §8.3): does NOT filter by band at
    all — deliberately widens the spread across bands to localize a new
    student's level faster, per the design doc's own description.

    theta is accepted per the design doc's spec but not used as the
    primary ranking signal here (see module docstring) — reserved for a
    future revision once real item calibration exists.
    """
    candidates = fringe(vector)

    if not calibration:
        on_band = [
            skill_id for skill_id in candidates
            if (skill := get_skill(skill_id)) is not None and skill.band == grade_band
        ]
        if on_band:
            candidates = on_band
        # else: fall back to the full (off-band) fringe rather than [].

    ranked_skills = sorted(candidates, key=lambda skill_id: _entropy(vector[skill_id]), reverse=True)

    probe_ids: list[str] = []
    for skill_id in ranked_skills[:limit]:
        for probe_id in probes_for_skill(skill_id):
            if probe_id not in probe_ids:
                probe_ids.append(probe_id)
    return probe_ids


def _is_confident(probability: float, se_threshold: float) -> bool:
    """A skill's posterior is 'confident' once the standard deviation of
    its Bernoulli(p) posterior — sqrt(p*(1-p)), the standard statistical
    measure of spread for a probability estimate — falls below
    se_threshold. Symmetric: equally strict near 0 as near 1."""
    standard_error = math.sqrt(probability * (1.0 - probability))
    return standard_error < se_threshold


def should_stop_probing(vector: dict[str, float], skill_ids: list[str], se_threshold: float = 0.15) -> bool:
    """
    True iff every skill in skill_ids has a confident posterior (see
    _is_confident) — Bede should stop steering probes toward all of them
    and tutor normally. Pass a single-skill list to check one skill;
    pass a whole grade band's skill list to check a calibration-exit
    condition (S9: "if enough on-band skills reach resolved, exit
    calibration mode").

    A skill_id with no entry in vector at all defaults to probability
    0.5 (maximum uncertainty) rather than being skipped — there is no
    evidence yet, so it cannot be "confident," and the aggregate
    correctly returns False rather than silently ignoring untested
    skills.
    """
    if not skill_ids:
        return False
    return all(_is_confident(vector.get(skill_id, 0.5), se_threshold) for skill_id in skill_ids)
