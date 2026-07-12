"""
Real check for Diagnostic build-loop unit 1.4 (cdm.py) — see
docs/diagnostic/DIAGNOSTIC_BUILD_PROGRESS.md. Asserts slip/guess sanity
for DINA/DINO/G-DINA, and that the Bayesian posterior actually moves in
the right direction (and by the right relative amount) given evidence.
"""

import pytest

from services.diagnostic.cdm import (
    CdmParams,
    dina_likelihood,
    dino_likelihood,
    gdina_likelihood,
    update_attribute_posteriors,
)


def test_dina_likelihood_all_mastered_returns_one_minus_slip():
    alpha = {"a": 1, "b": 1}
    assert dina_likelihood(alpha, ["a", "b"], slip=0.1, guess=0.2) == pytest.approx(0.9)


def test_dina_likelihood_missing_one_returns_guess():
    alpha = {"a": 1, "b": 0}
    assert dina_likelihood(alpha, ["a", "b"], slip=0.1, guess=0.2) == pytest.approx(0.2)


def test_dina_likelihood_missing_from_pattern_entirely_counts_as_not_mastered():
    alpha = {"a": 1}  # "b" absent from the pattern
    assert dina_likelihood(alpha, ["a", "b"], slip=0.1, guess=0.2) == pytest.approx(0.2)


def test_dino_likelihood_any_mastered_returns_one_minus_slip():
    alpha = {"a": 1, "b": 0}
    assert dino_likelihood(alpha, ["a", "b"], slip=0.1, guess=0.2) == pytest.approx(0.9)


def test_dino_likelihood_none_mastered_returns_guess():
    alpha = {"a": 0, "b": 0}
    assert dino_likelihood(alpha, ["a", "b"], slip=0.1, guess=0.2) == pytest.approx(0.2)


def test_gdina_likelihood_intercept_only():
    assert gdina_likelihood({"a": 1}, ["a"], {(): 0.3}) == pytest.approx(0.3)


def test_gdina_likelihood_single_skill_can_reproduce_dina_shape():
    # delta[()] = guess, delta[(a,)] = (1-slip) - guess reproduces DINA's
    # two-state behavior for a single-required-skill probe.
    delta = {(): 0.2, ("a",): 0.9 - 0.2}
    assert gdina_likelihood({"a": 1}, ["a"], delta) == pytest.approx(0.9)
    assert gdina_likelihood({"a": 0}, ["a"], delta) == pytest.approx(0.2)


def test_gdina_likelihood_clamped_to_unit_interval():
    assert gdina_likelihood({"a": 1}, ["a"], {(): 1.5}) == 1.0
    assert gdina_likelihood({"a": 1}, ["a"], {(): -0.5}) == 0.0


def test_update_posteriors_correct_outcome_increases_posterior():
    prior = {"cc.rote_count_20": 0.5}
    observation = {"probe_id": "probe.cc.rote_count_20", "outcome": "correct", "confidence": 1.0}
    posterior = update_attribute_posteriors(prior, observation)
    assert posterior["cc.rote_count_20"] > 0.5


def test_update_posteriors_incorrect_outcome_decreases_posterior():
    prior = {"cc.rote_count_20": 0.5}
    observation = {"probe_id": "probe.cc.rote_count_20", "outcome": "incorrect", "confidence": 1.0}
    posterior = update_attribute_posteriors(prior, observation)
    assert posterior["cc.rote_count_20"] < 0.5


def test_update_posteriors_zero_confidence_leaves_posterior_at_prior():
    prior = {"cc.rote_count_20": 0.5}
    observation = {"probe_id": "probe.cc.rote_count_20", "outcome": "correct", "confidence": 0.0}
    posterior = update_attribute_posteriors(prior, observation)
    assert posterior["cc.rote_count_20"] == pytest.approx(0.5, abs=1e-9)


def test_update_posteriors_partial_credit_moves_less_than_full_correct():
    prior = {"cc.rote_count_20": 0.5}
    full_correct = update_attribute_posteriors(
        prior, {"probe_id": "probe.cc.rote_count_20", "outcome": "correct", "confidence": 1.0}
    )
    partial = update_attribute_posteriors(
        prior, {"probe_id": "probe.cc.rote_count_20", "outcome": "partial", "confidence": 1.0}
    )
    assert 0.5 < partial["cc.rote_count_20"] < full_correct["cc.rote_count_20"]


def test_update_posteriors_hint_dependent_moves_posterior_down_not_up():
    """hint_dependent ('only after heavy scaffolding') should read as mild
    evidence AGAINST independent mastery, not for it — the opposite
    direction from 'partial'."""
    prior = {"cc.rote_count_20": 0.5}
    posterior = update_attribute_posteriors(
        prior, {"probe_id": "probe.cc.rote_count_20", "outcome": "hint_dependent", "confidence": 1.0}
    )
    assert posterior["cc.rote_count_20"] < 0.5


def test_update_posteriors_unknown_probe_returns_empty_dict():
    prior = {"cc.rote_count_20": 0.5}
    observation = {"probe_id": "not.a.real.probe", "outcome": "correct", "confidence": 1.0}
    assert update_attribute_posteriors(prior, observation) == {}


def test_update_posteriors_result_bounded_in_unit_interval():
    prior = {"cc.rote_count_20": 0.99}
    for outcome in ("correct", "partial", "hint_dependent", "incorrect"):
        posterior = update_attribute_posteriors(
            prior, {"probe_id": "probe.cc.rote_count_20", "outcome": outcome, "confidence": 1.0}
        )
        assert 0.0 <= posterior["cc.rote_count_20"] <= 1.0


def test_repeated_correct_evidence_converges_mastery_upward():
    prior = {"cc.rote_count_20": 0.5}
    for _ in range(10):
        prior["cc.rote_count_20"] = update_attribute_posteriors(
            prior, {"probe_id": "probe.cc.rote_count_20", "outcome": "correct", "confidence": 1.0}
        )["cc.rote_count_20"]
    assert prior["cc.rote_count_20"] > 0.95


def test_repeated_incorrect_evidence_converges_mastery_downward():
    prior = {"cc.rote_count_20": 0.5}
    for _ in range(10):
        prior["cc.rote_count_20"] = update_attribute_posteriors(
            prior, {"probe_id": "probe.cc.rote_count_20", "outcome": "incorrect", "confidence": 1.0}
        )["cc.rote_count_20"]
    assert prior["cc.rote_count_20"] < 0.05


def test_default_cdm_params_match_design_doc_defaults():
    params = CdmParams()
    assert params.slip == pytest.approx(0.1)
    assert params.guess == pytest.approx(0.2)


def test_a_raw_score_of_exactly_half_is_structurally_uninformative():
    """Documents the property that forced qmatrix.py's partial/hint_dependent
    scores away from 0.5: score*p + (1-score)*(1-p) == 0.5 identically for
    ANY p when score==0.5, so an outcome scored at exactly the midpoint
    carries zero evidential weight under this soft-label likelihood,
    regardless of slip/guess. qmatrix.outcome_to_score must never map a
    real outcome to exactly 0.5, or that outcome becomes a no-op."""
    from services.diagnostic.qmatrix import outcome_to_score

    for outcome in ("correct", "partial", "hint_dependent", "incorrect"):
        assert outcome_to_score(outcome) != 0.5, (
            f"outcome_to_score({outcome!r}) == 0.5 would make this outcome "
            "carry no evidence at all in update_attribute_posteriors"
        )
