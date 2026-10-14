"""Mac mini Bede bundle catalog and measured pre-pilot acceptance gate.

Learner entitlement is not inference concurrency. Hardware is separately
purchased and cannot grant Bede licenses. This module evaluates operator-
supplied physical-device metrics; it does not run a model or prove outcomes.
See docs/MAC_MINI_BUNDLES.md.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Bundle:
    sku: str
    name: str
    chip: str
    memory_gb: int
    ssd_tb: int
    manufacturer: str = "Apple"
    product_family: str = "Mac mini"
    hardware_sold_separately: bool = True
    software_subscription_included: bool = False
    established_concurrency_limit: None = None
    schoolwide_capacity_proven: bool = False


BUNDLES = {
    "classroom": Bundle(
        "classroom", "Bede Classroom Mac mini", "Apple M6", 32, 1,
    ),
    "campus": Bundle(
        "campus", "Bede Campus Mac mini", "Apple M5 Pro", 64, 4,
    ),
}

# Official September 2026 Apple silicon configurations:
# https://support.apple.com/en-us/128108
_APPLE_MAX = {"Apple M6": (32, 2), "Apple M5 Pro": (64, 8)}

# Preliminary engineering pilot targets, NOT published educational benchmarks.
MIN_TURNS = 30
MAX_P95_TTFT_MS = 10000
MAX_P95_COMPLETE_MS = 45000
MAX_ERROR_RATE = 0.01
MAX_MEMORY_FRACTION = 0.85

REQUIRED_EVIDENCE = (
    "local_model_provenance",
    "tutor_accuracy_and_source_review",
    "moderation_and_safety_fail_closed",
    "approved_curriculum_enforced",
    "learner_data_isolation",
    "educator_mfa_and_revocation",
    "diagnostic_source_provenance",
    "dibels_external_assessment_boundary",
    "filevault_and_data_encryption",
    "backup_restore_rehearsed",
    "network_access_controlled",
    "restart_and_recovery_rehearsed",
)


def p95(values: list[float]) -> float:
    if not values or any(not isinstance(v, (int, float))
                         or isinstance(v, bool) or not math.isfinite(v) or v < 0
                         for v in values):
        raise ValueError("Need nonnegative finite measured values")
    return sorted(values)[math.ceil(0.95 * len(values)) - 1]


def evaluate(sku: str, evidence: dict) -> dict:
    """Strict comparison of real-device evidence to one SKU and chosen load.

    This is an operator attestation, not cryptographic hardware attestation.
    Synthetic CI inputs MUST fail real-world qualification. Never supply
    student records, actual credential values, or prompts in this report.
    """
    if sku not in BUNDLES:
        raise ValueError("Unknown hardware bundle")
    if not isinstance(evidence, dict):
        raise ValueError("Evidence must be an object")
    bundle = BUNDLES[sku]
    failures: list[str] = []
    checklist = []

    def check(name: str, passed: bool, reason: str) -> None:
        checklist.append({"name": name, "passed": bool(passed)})
        if not passed:
            failures.append(reason)

    hw = evidence.get("hardware")
    if not isinstance(hw, dict):
        hw = {}
    check(
        "model_identity", hw.get("manufacturer") == "Apple"
        and hw.get("family") == "Mac mini"
        and hw.get("chip") == bundle.chip
        and hw.get("architecture") == "arm64",
        "The named Apple Silicon Mac mini was not verified",
    )
    ram = hw.get("memory_gb")
    disk = hw.get("internal_ssd_tb")
    check(
        "minimum_ram", type(ram) in (int, float) and math.isfinite(ram)
        and bundle.memory_gb <= ram <= _APPLE_MAX[bundle.chip][0],
        f"{bundle.memory_gb} GB unified memory required",
    )
    check(
        "minimum_internal_ssd", type(disk) in (int, float) and math.isfinite(disk)
        and bundle.ssd_tb <= disk <= _APPLE_MAX[bundle.chip][1],
        f"{bundle.ssd_tb} TB internal storage required",
    )
    check("physical_test_origin",
          evidence.get("origin") == "real_target_device_test",
          "CI or synthetic data cannot qualify production-pilot hardware")
    check(
        "recorded_model_and_runtime",
        isinstance(evidence.get("model_id"), str)
        and len(evidence["model_id"]) >= 3
        and isinstance(evidence.get("runtime_version"), str)
        and len(evidence["runtime_version"]) >= 2,
        "Exact local inference model and runtime versions required",
    )

    target = evidence.get("target_concurrent_sessions")
    observed = evidence.get("observed_peak_concurrent_sessions")
    valid_concurrency = (
        type(target) is int and type(observed) is int
        and target >= 1 and observed >= target
    )
    check("target_concurrency", valid_concurrency,
          "Actual concurrent inference sessions did not reach target")

    turns = evidence.get("turns")
    if not isinstance(turns, list):
        turns = []
    well_formed = all(
        isinstance(t, dict)
        and type(t.get("success")) is bool
        and type(t.get("time_to_first_token_ms")) in (int, float)
        and type(t.get("complete_turn_ms")) in (int, float)
        and math.isfinite(t["time_to_first_token_ms"])
        and math.isfinite(t["complete_turn_ms"])
        and 0 <= t["time_to_first_token_ms"] <= t["complete_turn_ms"]
        for t in turns
    )
    check("measured_turn_count", well_formed and len(turns) >= MIN_TURNS,
          f"At least {MIN_TURNS} valid measured turns required")
    first = complete = error_rate = None
    if well_formed and turns:
        first = p95([t["time_to_first_token_ms"] for t in turns])
        complete = p95([t["complete_turn_ms"] for t in turns])
        error_rate = sum(not t["success"] for t in turns) / len(turns)
    check("first_token_p95",
          first is not None and first <= MAX_P95_TTFT_MS,
          "First-token p95 exceeds preliminary pilot ceiling")
    check("complete_turn_p95",
          complete is not None and complete <= MAX_P95_COMPLETE_MS,
          "Completed-turn p95 exceeds preliminary pilot ceiling")
    check("error_rate",
          error_rate is not None and error_rate <= MAX_ERROR_RATE,
          "Observed turn error rate exceeds preliminary pilot ceiling")

    memory = evidence.get("peak_unified_memory_fraction")
    check("memory_headroom",
          type(memory) in (int, float) and math.isfinite(memory)
          and 0 <= memory <= MAX_MEMORY_FRACTION,
          "Too little measured free unified-memory headroom")
    checks = evidence.get("workflow_checks")
    if not isinstance(checks, dict):
        checks = {}
    for key in REQUIRED_EVIDENCE:
        check(key, checks.get(key) is True,
              "Missing required operational evidence: " + key)

    return {
        "sku": sku, "hardware_bundle": asdict(bundle),
        "target_concurrent_sessions": target if valid_concurrency else None,
        "measured_concurrent_sessions": observed if valid_concurrency else None,
        "measured_turns": len(turns), "ttft_p95_ms": first,
        "complete_p95_ms": complete, "error_rate": error_rate,
        "checks": checklist, "failures": failures,
        "qualifies_for_tested_concurrency": not failures,
        "campuswide_capacity_proven": False,
        "learning_efficacy_proven": False,
        "unlimited_learner_license_means_unlimited_simultaneous_sessions": False,
        "measurement_origin": evidence.get("origin"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Qualify a real Mac mini pilot load report")
    parser.add_argument("--sku", required=True, choices=sorted(BUNDLES))
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    report = evaluate(args.sku, json.loads(args.evidence.read_text(encoding="utf-8")))
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report["qualifies_for_tested_concurrency"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
