"""
Item Response Theory (1PL/2PL/3PL logistic models, Fisher information,
ability/theta estimation) — realizes runtime-loop step S6 (see
docs/diagnostic/DIAGNOSTIC_LOOP.md). Pure stdlib `math`, no numpy, per
docs/diagnostic/DIAGNOSTIC_BUILD_LOOP.md's Phase 1 hard rules.

Implements published, open-standard formulas from scratch (design doc
§14 Open-Standards Appendix — Rasch 1960, Birnbaum 1968, Lord 1980): the
1PL/Rasch, 2PL, and 3PL logistic item response functions, their Fisher
information, and a Fisher-scoring (Newton-Raphson using Fisher
information as the curvature estimate) MAP ability estimator — the
standard, well-documented technique for computing an ability estimate
without needing a full numerical-integration EAP, which pure Python has
no fast library support for here.

theta = latent ability; a = discrimination; b = difficulty; c = guessing.
"""

import math

_MIN_PROB = 1e-9
_MAX_PROB = 1.0 - 1e-9


def _sigmoid(z: float) -> float:
    """Numerically stable logistic function — math.exp(z) overflows for
    large positive z and underflows harmlessly for large negative z, so
    branch on the sign to only ever exponentiate a non-positive number."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _clamp_probability(p: float) -> float:
    """Keeps probabilities strictly inside (0, 1) so log-likelihood terms
    never hit log(0) on a saturated/near-certain estimate."""
    return max(_MIN_PROB, min(_MAX_PROB, p))


def p_1pl(theta: float, b: float) -> float:
    """Rasch model: P(correct) = sigmoid(theta - b)."""
    return _clamp_probability(_sigmoid(theta - b))


def p_2pl(theta: float, a: float, b: float) -> float:
    """P(correct) = sigmoid(a * (theta - b))."""
    return _clamp_probability(_sigmoid(a * (theta - b)))


def p_3pl(theta: float, a: float, b: float, c: float) -> float:
    """P(correct) = c + (1 - c) * sigmoid(a * (theta - b)) — adds a
    guessing floor c to the 2PL curve."""
    return _clamp_probability(c + (1.0 - c) * _sigmoid(a * (theta - b)))


def fisher_information(theta: float, a: float, b: float, c: float = 0.0) -> float:
    """Item (Fisher) information at a given ability level — how much this
    item narrows uncertainty about theta there. Standard 3PL formula
    (reduces cleanly to 2PL/1PL when c=0, a=1); peaks near theta==b and
    grows with discrimination a."""
    p = p_3pl(theta, a, b, c)
    if c >= 1.0:
        return 0.0
    numerator = (a ** 2) * ((p - c) ** 2) * (1.0 - p)
    denominator = ((1.0 - c) ** 2) * p
    return numerator / denominator if denominator > 0 else 0.0


def _dp_dtheta(theta: float, a: float, b: float, c: float) -> float:
    """dP/dtheta for the 3PL curve: (1-c) * a * L * (1-L), where L is the
    plain 2PL logistic term."""
    logistic = _sigmoid(a * (theta - b))
    return (1.0 - c) * a * logistic * (1.0 - logistic)


def estimate_theta_mle(
    responses: list[tuple[float, ...]],
    outcomes: list[float],
    prior_mean: float = 0.0,
    prior_sd: float = 1.0,
    max_iterations: int = 25,
    convergence_threshold: float = 1e-4,
) -> tuple[float, float]:
    """
    Fisher-scoring MAP estimate of ability from a set of (a, b, c) item
    params paired with observed outcomes (0/1 for a strict right/wrong
    response, or a graded value in [0, 1] — e.g. qmatrix.outcome_to_score's
    partial/hint_dependent scores — treated as a Bernoulli-style target so
    partial credit pulls theta less far than a clean correct/incorrect).

    Returns (theta_hat, standard_error). With zero responses, returns the
    prior unchanged and its own spread as the standard error — there is no
    evidence yet to update on.
    """
    if len(responses) != len(outcomes):
        raise ValueError("responses and outcomes must be the same length")
    if not responses:
        return prior_mean, prior_sd

    normalized = [(params + (0.0, 0.0, 0.0))[:3] for params in responses]
    prior_precision = 1.0 / (prior_sd ** 2)
    theta = prior_mean

    for _ in range(max_iterations):
        score = -(theta - prior_mean) * prior_precision
        information = prior_precision

        for (a, b, c), outcome in zip(normalized, outcomes):
            p = p_3pl(theta, a, b, c)
            score += _dp_dtheta(theta, a, b, c) * (outcome - p) / (p * (1.0 - p))
            information += fisher_information(theta, a, b, c)

        if information <= 0:
            break

        step = score / information
        theta += step
        if abs(step) < convergence_threshold:
            break

    total_information = prior_precision + sum(
        fisher_information(theta, a, b, c) for a, b, c in normalized
    )
    standard_error = 1.0 / math.sqrt(total_information) if total_information > 0 else prior_sd

    return theta, standard_error
