"""Synthetic regression tests, not physical capacity certification."""
from copy import deepcopy

import pytest

from core.mac_bundle_qualification import (
    BUNDLES, REQUIRED_EVIDENCE, evaluate, p95,
)


def report(sku="campus"):
    b = BUNDLES[sku]
    return {
        "origin": "real_target_device_test",
        "hardware": {
            "manufacturer": "Apple", "family": "Mac mini",
            "chip": b.chip, "architecture": "arm64",
            "memory_gb": b.memory_gb, "internal_ssd_tb": b.ssd_tb,
        },
        "model_id": "approved-open-weight-model-version",
        "runtime_version": "local-macos-inference-1.0.0",
        "target_concurrent_sessions": 8,
        "observed_peak_concurrent_sessions": 8,
        "turns": [
            {
                "success": True,
                "time_to_first_token_ms": 3000,
                "complete_turn_ms": 17000,
            } for _ in range(60)
        ],
        "peak_unified_memory_fraction": 0.72,
        "workflow_checks": {name: True for name in REQUIRED_EVIDENCE},
    }


@pytest.mark.parametrize("sku", ["classroom", "campus"])
def test_both_apple_silicon_skus_are_consistent_with_current_specs(sku):
    result = evaluate(sku, report(sku))
    assert result["qualifies_for_tested_concurrency"]
    assert result["measured_concurrent_sessions"] == 8
    assert result["hardware_bundle"]["hardware_sold_separately"]
    assert result["hardware_bundle"]["software_subscription_included"] is False
    assert result["hardware_bundle"]["established_concurrency_limit"] is None
    assert result["campuswide_capacity_proven"] is False
    assert result["learning_efficacy_proven"] is False


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(origin="ci_synthetic"),
    lambda r: r["hardware"].update(chip="Apple M4 Pro"),
    lambda r: r["hardware"].update(architecture="x86_64"),
    lambda r: r["hardware"].update(memory_gb=32),
    lambda r: r["hardware"].update(internal_ssd_tb=1),
    lambda r: r.update(model_id=""),
    lambda r: r.update(runtime_version=""),
    lambda r: r.update(observed_peak_concurrent_sessions=4),
    lambda r: r.update(turns=r["turns"][:2]),
    lambda r: r["turns"][0].update(time_to_first_token_ms=100000, complete_turn_ms=100000),
    lambda r: r["turns"][0].update(success=False),
    lambda r: r.update(peak_unified_memory_fraction=0.92),
    lambda r: r["workflow_checks"].update(educator_mfa_and_revocation=False),
    lambda r: r["workflow_checks"].update(learner_data_isolation=False),
    lambda r: r["workflow_checks"].update(dibels_external_assessment_boundary=False),
    lambda r: r["workflow_checks"].update(backup_restore_rehearsed=False),
    lambda r: r["workflow_checks"].update(moderation_and_safety_fail_closed=False),
])
def test_pilot_qualifications_fail_closed_without_real_safe_operational_proof(mutate):
    data = report()
    mutate(data)
    result = evaluate("campus", data)
    assert not result["qualifies_for_tested_concurrency"]
    assert result["failures"]


def test_p95_nearest_rank_and_invalid_measurement_guard():
    assert p95([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 99]) == 99
    with pytest.raises(ValueError):
        p95([])
    with pytest.raises(ValueError):
        p95([1, float("nan")])


def test_memory_cannot_claim_physically_unavailable_configuration():
    data = report("classroom")
    data["hardware"]["memory_gb"] = 64
    assert not evaluate("classroom", data)["qualifies_for_tested_concurrency"]


def test_a_synthetic_ci_test_even_if_technically_good_does_not_prove_deployment():
    data = report()
    data["origin"] = "synthetic_ci_data"
    output = evaluate("campus", data)
    assert not output["qualifies_for_tested_concurrency"]
    assert output["campuswide_capacity_proven"] is False


def test_license_and_operational_capacity_are_independent():
    for b in BUNDLES.values():
        assert b.established_concurrency_limit is None
        assert b.schoolwide_capacity_proven is False
        assert b.hardware_sold_separately
