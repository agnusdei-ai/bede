"""
Cognitive Diagnostic Models — DINA/DINO/G-DINA attribute-mastery
inference — realizes runtime-loop step S6 (see
docs/diagnostic/DIAGNOSTIC_LOOP.md). Pure stdlib, no numpy, per
docs/diagnostic/DIAGNOSTIC_BUILD_LOOP.md's Phase 1 hard rules.

Implements published, open-standard models from scratch (design doc §14
— Junker & Sijtsma 2001 DINA; Templin & Henson 2006 DINO; de la Torre
2011 G-DINA). The engine tracks a continuous posterior P(mastery) per
attribute rather than a hard 0/1 classification, so
update_attribute_posteriors doesn't just evaluate one hypothesized
pattern — for each attribute a probe touches, it marginalizes the
likelihood over every other required attribute's current uncertainty
(weighted by that attribute's own prior probability), then applies
Bayes' rule. With today's 1:1 Q-matrix (qmatrix.py, unit 1.2) every
probe has exactly one required attribute, so there is nothing to
marginalize yet — but the math is written generally for when
multi-skill probes are added later (see qmatrix.py's own decision log).

An outcome isn't binary correct/incorrect in bede — record_skill_evidence
reports correct/partial/incorrect/hint_dependent, scored to [0,1] by
qmatrix.outcome_to_score. That graded score is treated as a soft label:
the observation likelihood is a score-weighted blend of the
correct-response and incorrect-response likelihoods, which is exactly
what "partial credit" should mean to a Bayesian update.
"""

from dataclasses import dataclass
from itertools import combinations, product
from typing import Literal

from services.diagnostic.qmatrix import EvidenceObservation, outcome_to_score, q_row as qmatrix_q_row

AttributePattern = dict[str, int]


@dataclass(frozen=True)
class CdmParams:
    """slip = P(incorrect | mastered) — a careless mistake. guess = P(correct
    | not mastered) — a lucky guess. Defaults are conservative literature
    priors (design doc §4.4). delta is G-DINA only: maps a sorted tuple of
    required-skill-id subsets to that subset's coefficient, empty tuple ()
    for the intercept."""
    slip: float = 0.1
    guess: float = 0.2
    delta: dict[tuple[str, ...], float] | None = None


def dina_likelihood(alpha: AttributePattern, q_row: list[str], slip: float, guess: float) -> float:
    """Conjunctive: P(correct) = (1-slip) if every required skill is
    mastered in this hypothesized pattern, else guess."""
    mastered_all = all(alpha.get(skill_id, 0) == 1 for skill_id in q_row)
    return (1.0 - slip) if mastered_all else guess


def dino_likelihood(alpha: AttributePattern, q_row: list[str], slip: float, guess: float) -> float:
    """Disjunctive: P(correct) = (1-slip) if any required skill is
    mastered, else guess."""
    mastered_any = any(alpha.get(skill_id, 0) == 1 for skill_id in q_row)
    return (1.0 - slip) if mastered_any else guess


def gdina_likelihood(alpha: AttributePattern, q_row: list[str], delta: dict[tuple[str, ...], float]) -> float:
    """General saturated model: P(correct) = delta[()] + sum over every
    non-empty subset S of q_row of delta[S] * product(alpha[j] for j in S).
    Missing subset keys default to a zero coefficient. Clamped to [0,1] —
    an arbitrary delta config isn't guaranteed to stay in range."""
    total = delta.get((), 0.0)
    sorted_row = sorted(q_row)
    for size in range(1, len(sorted_row) + 1):
        for subset in combinations(sorted_row, size):
            coefficient = delta.get(subset, 0.0)
            if coefficient == 0.0:
                continue
            attribute_product = 1
            for skill_id in subset:
                attribute_product *= alpha.get(skill_id, 0)
            total += coefficient * attribute_product
    return max(0.0, min(1.0, total))


def _p_correct(model: str, alpha: AttributePattern, q_row: list[str], params: CdmParams) -> float:
    if model == "dina":
        return dina_likelihood(alpha, q_row, params.slip, params.guess)
    if model == "dino":
        return dino_likelihood(alpha, q_row, params.slip, params.guess)
    if model == "gdina":
        return gdina_likelihood(alpha, q_row, params.delta or {})
    raise ValueError(f"Unknown CDM model: {model!r}")


def _expected_observation_likelihood(
    hypothesized_skill: str,
    hypothesized_value: int,
    q_row: list[str],
    prior: dict[str, float],
    effective_score: float,
    model: str,
    params: CdmParams,
) -> float:
    """P(this soft-labeled observation | hypothesized_skill=hypothesized_value),
    marginalized over every other required skill's current mastery
    uncertainty. With len(q_row) <= 1 (today's Q-matrix) there is nothing
    else to marginalize and this reduces to a single term."""
    other_skills = [s for s in q_row if s != hypothesized_skill]
    total_likelihood = 0.0
    total_weight = 0.0
    for combo in product((0, 1), repeat=len(other_skills)):
        alpha: AttributePattern = {hypothesized_skill: hypothesized_value}
        weight = 1.0
        for skill_id, value in zip(other_skills, combo):
            p_mastered = prior.get(skill_id, 0.5)
            alpha[skill_id] = value
            weight *= p_mastered if value == 1 else (1.0 - p_mastered)
        if weight == 0.0:
            continue
        p_correct = _p_correct(model, alpha, q_row, params)
        observation_likelihood = (
            effective_score * p_correct + (1.0 - effective_score) * (1.0 - p_correct)
        )
        total_likelihood += weight * observation_likelihood
        total_weight += weight
    return total_likelihood / total_weight if total_weight > 0 else 0.5


def update_attribute_posteriors(
    prior: dict[str, float],
    observation: EvidenceObservation,
    model: Literal["dina", "dino", "gdina"] = "dina",
    params: CdmParams | None = None,
) -> dict[str, float]:
    """
    Posterior P(mastery) for every skill the observation's probe touches
    (qmatrix.q_row(observation["probe_id"])). Skills outside that set are
    untouched — this returns only the probed skills' updated values, for
    the caller (mastery.py, unit 1.7) to blend into the full vector. An
    unknown probe_id resolves to q_row() == [], so this returns {} rather
    than raising — same degrade-gracefully contract as the rest of the
    Phase 1 core.

    observation["confidence"] shrinks the effective evidence toward the
    uninformative midpoint (0.5) as it approaches 0 — low-confidence
    evidence should move the posterior less, not not at all and not the
    full amount. At confidence=0, the posterior is provably unchanged
    from the prior (see tests/diagnostic/test_cdm.py).
    """
    if params is None:
        params = CdmParams()

    required_skills = qmatrix_q_row(observation["probe_id"])
    if not required_skills:
        return {}

    confidence = max(0.0, min(1.0, observation.get("confidence", 1.0)))
    raw_score = outcome_to_score(observation["outcome"])
    effective_score = 0.5 + confidence * (raw_score - 0.5)

    posterior: dict[str, float] = {}
    for skill_id in required_skills:
        p_prior = prior.get(skill_id, 0.5)
        likelihood_mastered = _expected_observation_likelihood(
            skill_id, 1, required_skills, prior, effective_score, model, params
        )
        likelihood_not_mastered = _expected_observation_likelihood(
            skill_id, 0, required_skills, prior, effective_score, model, params
        )
        numerator = p_prior * likelihood_mastered
        denominator = numerator + (1.0 - p_prior) * likelihood_not_mastered
        posterior[skill_id] = numerator / denominator if denominator > 0 else p_prior

    return posterior
