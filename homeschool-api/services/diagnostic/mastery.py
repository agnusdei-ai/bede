"""
The mastery vector itself — cold-start initialization, the Bayesian
update loop, and the parent-facing rollup — realizes runtime-loop step
S7 (see docs/diagnostic/DIAGNOSTIC_LOOP.md). Pure stdlib, no numpy, per
docs/diagnostic/DIAGNOSTIC_BUILD_LOOP.md's Phase 1 hard rules.

This is where cdm.py (unit 1.4) and kst.py (unit 1.5) compose: one
observation's CDM posterior gets blended into the vector, then
kst.propagate_prerequisites enforces the surmise relation so a
confidently-mastered skill's prerequisites are never left behind. This
module is also Phase 1's acceptance unit — its own real check is a
synthetic evidence stream proving the whole pipeline converges sensibly
and never produces a vector where a mastered skill's prerequisites lag
behind (see tests/diagnostic/test_mastery.py).
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from services.diagnostic.cdm import update_attribute_posteriors
from services.diagnostic.kst import fringe, propagate_prerequisites
from services.diagnostic.qmatrix import EvidenceObservation, q_row
from services.diagnostic.skill_map import GradeBand, all_skill_ids, get_skill

MasteryVector = dict[str, float]

_MASTERY_LEVELS = (
    ("secure", 0.8),
    ("developing", 0.4),
    ("gap", 0.0),
)

_BAND_ORDER = (GradeBand.K_2, GradeBand.THREE_5, GradeBand.SIX_8)
_BAND_INDEX = {band.value: index for index, band in enumerate(_BAND_ORDER)}

# Per-subject evidence-point count (MasteryProfile.evidence_count's own
# scalar, not a per-skill count — see DIAGNOSTIC_BUILD_PROGRESS.md's unit
# 2.2 review) below which a student is still "calibrating": design doc
# §8.3's own explicit "[to verify final N]" flag — this is a placeholder,
# not yet tuned against real sessions. Coincidentally the same value as
# services/diagnostic_demo.py's own, separately-declared CALIBRATION_
# THRESHOLD today, but the two are not coupled — this one is free to
# change at Phase 5's tuning pass without touching the demo's number.
CALIBRATION_THRESHOLD = 5


def calibration_weight_for(evidence_count: int, threshold: int = CALIBRATION_THRESHOLD) -> float:
    """
    Linear decay from a doubled posterior push at evidence_count==0 down to
    a normal 1.0 blend once evidence_count reaches threshold — design doc
    §8.3: "higher calibration_weight... early evidence moves the posterior
    more — faster cold-start convergence." Never below 1.0 (bayesian_update
    itself clamps the result to [0,1] regardless, but this keeps the
    caller's own semantics: calibration only ever pushes harder than a
    normal update, never softer)."""
    if evidence_count >= threshold:
        return 1.0
    return 2.0 - (evidence_count / threshold)


@dataclass
class MasteryUpdate:
    skill_id: str
    prior: float
    posterior: float
    probe_id: str
    model_used: str
    observed_at: str


def new_vector(grade_band: str) -> MasteryVector:
    """Cold-start vector: prior 0.5 for skills in the student's own band,
    lower for bands above (less likely mastered yet), higher for bands
    below (a student at this level has very likely already mastered
    earlier-band foundations, even if never directly probed). An
    unrecognized grade_band gets a flat 0.5 prior everywhere rather than
    raising — this only ever seeds a starting point, never a
    security-relevant decision, matching grade_to_stage()'s own
    degrade-gracefully convention in models/schemas.py."""
    student_index = _BAND_INDEX.get(grade_band)
    vector: MasteryVector = {}
    for skill_id in all_skill_ids():
        skill = get_skill(skill_id)
        if student_index is None or skill is None:
            vector[skill_id] = 0.5
            continue
        distance = _BAND_INDEX[skill.band.value] - student_index
        if distance == 0:
            vector[skill_id] = 0.5
        elif distance > 0:
            vector[skill_id] = max(0.1, 0.5 - 0.2 * distance)
        else:
            vector[skill_id] = min(0.9, 0.5 - 0.2 * distance)
    return vector


def _classify(probability: float) -> str:
    for level, floor in _MASTERY_LEVELS:
        if probability >= floor:
            return level
    return "gap"


def bayesian_update(
    vector: MasteryVector,
    observation: EvidenceObservation,
    calibration_weight: float = 1.0,
    model: str = "dina",
) -> tuple[MasteryVector, list[MasteryUpdate]]:
    """
    One evidence-driven update cycle:
      1. Look up q_row(probe_id) — an unknown probe touches nothing.
      2. cdm.update_attribute_posteriors() for those skills.
      3. Blend each skill's CDM posterior into the vector, scaled by
         calibration_weight (1.0 = trust the CDM posterior as computed;
         >1.0, used during calibration mode per design doc §8.3, pushes
         further than one natural Bayesian step for faster cold-start
         convergence; results are clamped to [0,1] regardless).
      4. kst.propagate_prerequisites() over the blended vector, so a
         skill that crossed the "mastered" threshold this turn correctly
         raises its own prerequisites' floors immediately.

    Returns the new vector (input is not mutated) and one MasteryUpdate
    per skill actually touched, timestamped now in UTC ISO8601 — the
    only thing that may optionally be persisted (design doc §5.3), never
    the raw observation itself.
    """
    required_skills = q_row(observation["probe_id"])
    if not required_skills:
        return dict(vector), []

    cdm_posteriors = update_attribute_posteriors(vector, observation, model=model)

    updated = dict(vector)
    updates: list[MasteryUpdate] = []
    observed_at = datetime.now(timezone.utc).isoformat()

    for skill_id in required_skills:
        prior = vector.get(skill_id, 0.5)
        cdm_posterior = cdm_posteriors.get(skill_id, prior)
        blended = prior + calibration_weight * (cdm_posterior - prior)
        blended = max(0.0, min(1.0, blended))
        updated[skill_id] = blended
        updates.append(MasteryUpdate(
            skill_id=skill_id,
            prior=prior,
            posterior=blended,
            probe_id=observation["probe_id"],
            model_used=model,
            observed_at=observed_at,
        ))

    updated = propagate_prerequisites(updated)
    return updated, updates


def aggregate_for_parent(vector: MasteryVector) -> dict:
    """Render-only rollup for the parent dashboard (design doc §9/§10):
    per-domain average probability + level classification, a gaps list
    (level=='gap', worst first), and next_steps from kst.fringe(). No
    raw evidence, no per-skill history — just where things stand now."""
    domain_probabilities: dict[str, list[float]] = {}
    for skill_id, probability in vector.items():
        skill = get_skill(skill_id)
        if skill is None:
            continue
        domain_probabilities.setdefault(skill.domain, []).append(probability)

    domains = {
        domain: {
            "average_probability": sum(probabilities) / len(probabilities),
            "level": _classify(sum(probabilities) / len(probabilities)),
        }
        for domain, probabilities in domain_probabilities.items()
    }

    gaps = sorted(
        (skill_id for skill_id, probability in vector.items() if _classify(probability) == "gap"),
        key=lambda skill_id: vector[skill_id],
    )

    return {
        "domains": domains,
        "gaps": gaps,
        "next_steps": fringe(vector),
    }
