"""
Real check for Diagnostic build-loop unit 1.3 (irt.py) — see
docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md. Asserts known P values at
hand-computable points, Fisher information's monotonic relationship with
discrimination, and that theta estimation actually converges in the
expected direction on a synthetic response stream.
"""

import math

import pytest

from services.diagnostic.irt import (
    estimate_theta_mle,
    fisher_information,
    p_1pl,
    p_2pl,
    p_3pl,
)


def test_p_1pl_known_values():
    assert p_1pl(theta=0.0, b=0.0) == pytest.approx(0.5)
    assert p_1pl(theta=5.0, b=0.0) > 0.99
    assert p_1pl(theta=-5.0, b=0.0) < 0.01


def test_p_2pl_known_values():
    assert p_2pl(theta=1.0, a=2.0, b=1.0) == pytest.approx(0.5)
    assert p_2pl(theta=1.0, a=0.1, b=1.0) == pytest.approx(0.5)
    assert p_2pl(theta=10.0, a=2.0, b=0.0) > 0.99


def test_p_3pl_known_values():
    # At theta == b, the logistic term is 0.5, so P = c + (1-c)*0.5 = (1+c)/2.
    assert p_3pl(theta=0.0, a=1.0, b=0.0, c=0.2) == pytest.approx(0.6, abs=1e-6)
    # Guessing floor: as theta -> -inf, P approaches c, never below it.
    assert p_3pl(theta=-20.0, a=1.0, b=0.0, c=0.25) == pytest.approx(0.25, abs=1e-3)
    # Ceiling: as theta -> +inf, P approaches 1.
    assert p_3pl(theta=20.0, a=1.0, b=0.0, c=0.25) > 0.99


def test_fisher_information_monotonic_in_discrimination():
    """At theta == b (item matched to ability), information should
    strictly increase as discrimination `a` increases."""
    infos = [fisher_information(theta=0.0, a=a, b=0.0, c=0.0) for a in (0.5, 1.0, 2.0, 3.0)]
    assert infos == sorted(infos)
    assert infos[0] < infos[-1]


def test_fisher_information_peaks_near_matched_difficulty():
    at_match = fisher_information(theta=0.0, a=1.0, b=0.0, c=0.0)
    far_above = fisher_information(theta=4.0, a=1.0, b=0.0, c=0.0)
    far_below = fisher_information(theta=-4.0, a=1.0, b=0.0, c=0.0)
    assert at_match > far_above
    assert at_match > far_below


def test_fisher_information_zero_when_guessing_certain():
    assert fisher_information(theta=0.0, a=1.0, b=0.0, c=1.0) == 0.0


def test_estimate_theta_converges_upward_on_all_correct_stream():
    responses = [(1.0, b, 0.0) for b in (-2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0)]
    outcomes = [1.0] * len(responses)
    theta_hat, se = estimate_theta_mle(responses, outcomes, prior_mean=0.0, prior_sd=1.0)
    assert theta_hat > 1.5, f"theta should climb well above the prior on an all-correct stream, got {theta_hat}"
    assert se > 0


def test_estimate_theta_converges_downward_on_all_incorrect_stream():
    responses = [(1.0, b, 0.0) for b in (-4.0, -3.0, -2.0, -1.0, 0.0, 1.0, 2.0)]
    outcomes = [0.0] * len(responses)
    theta_hat, _ = estimate_theta_mle(responses, outcomes, prior_mean=0.0, prior_sd=1.0)
    assert theta_hat < -1.5, f"theta should fall well below the prior on an all-incorrect stream, got {theta_hat}"


def test_estimate_theta_mixed_stream_lands_near_the_crossover_difficulty():
    # Correct on easy items, incorrect on hard ones -> ability should land
    # somewhere between the easy and hard item difficulties, not at either
    # extreme.
    responses = [(1.0, -2.0, 0.0), (1.0, -1.0, 0.0), (1.0, 1.0, 0.0), (1.0, 2.0, 0.0)]
    outcomes = [1.0, 1.0, 0.0, 0.0]
    theta_hat, _ = estimate_theta_mle(responses, outcomes, prior_mean=0.0, prior_sd=1.0)
    assert -2.0 < theta_hat < 2.0


def test_estimate_theta_no_responses_returns_prior_unchanged():
    theta_hat, se = estimate_theta_mle([], [], prior_mean=0.7, prior_sd=1.3)
    assert theta_hat == 0.7
    assert se == 1.3


def test_estimate_theta_raises_on_mismatched_lengths():
    with pytest.raises(ValueError):
        estimate_theta_mle([(1.0, 0.0, 0.0)], [1.0, 0.0])


def test_standard_error_shrinks_with_more_evidence():
    one_response = [(1.0, 0.0, 0.0)]
    many_responses = [(1.0, 0.0, 0.0)] * 20
    _, se_one = estimate_theta_mle(one_response, [1.0], prior_mean=0.0, prior_sd=1.0)
    _, se_many = estimate_theta_mle(many_responses, [1.0] * 20, prior_mean=0.0, prior_sd=1.0)
    assert se_many < se_one


def test_probabilities_never_hit_exact_zero_or_one():
    """Guards the log-likelihood math in estimate_theta_mle against a
    log(0) blow-up on saturated estimates."""
    assert 0.0 < p_3pl(theta=1000.0, a=5.0, b=0.0, c=0.0) < 1.0
    assert 0.0 < p_3pl(theta=-1000.0, a=5.0, b=0.0, c=0.0) < 1.0
