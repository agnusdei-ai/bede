"""Synthetic pre-pilot conformance simulation against real Bede code.

Tests teaching-move selection and educator-entered DIBELS data integrity;
does NOT test whether real children learn, live LLM behavior, or test items.
Research supplies pedagogical *principles*, not numerical efficacy scores.
Run: python -m evaluation.classical_core_simulation
"""
import argparse
import json
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from pydantic import ValidationError
from services.adaptive_learning import select_instruction, render_instruction, WorkObservation, POLICY_VERSION
from services.assessment_interop import EducatorAssessmentSubmission, DIBELS_UNITS, frameworks_catalog

NOW = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
SEED = 20261013
SKILL = "oa.add_within_20"
# Independent expectations: changing code without reviewing the research
# and this oracle makes the fixed-seed suite fail.
EXPECTED = {
    "cold_start": None,
    "two_supported": "change_representation",
    "one_supported": "smaller_step",
    "one_hint": "fade_hint",
    "two_independent": "transfer",
    "one_independent": "explain_reasoning",
    "spaced_retrieval": "revisit",
    "stale_record": None,
    "future_record": None,
    "invalid_skill": None,
    "invalid_status": None,
    "grade_unavailable": None,
    "duplicate_record": "explain_reasoning",
}
SOURCES = {
    "IES_2007_Learning": "https://ies.ed.gov/ncee/wwc/PracticeGuide/1",
    "IES_2021_Mathematics": "https://ies.ed.gov/ncee/wwc/PracticeGuide/26",
    "DIBELS_8_Official": "https://dibels.uoregon.edu/materials/dibels",
}


def event(event_id, assistance="unaided", days=2, minutes=0, skill=SKILL):
    return WorkObservation(event_id=event_id, assistance=assistance, skill_id=skill,
                           completed_at=NOW - timedelta(days=days, minutes=minutes))


def evidence(kind):
    return {
        "cold_start": [],
        "two_supported": [event(1, "with_help"), event(2, "with_help", minutes=30)],
        "one_supported": [event(1, "with_help")],
        "one_hint": [event(1, "with_a_hint")],
        "two_independent": [event(1), event(2, minutes=30)],
        "one_independent": [event(1)],
        "spaced_retrieval": [event(1, days=28)],
        "stale_record": [event(1, days=121)],
        "future_record": [event(1, days=-1)],
        "invalid_skill": [event(1, skill="not.a.real.skill")],
        "invalid_status": [event(1, assistance="not_completed")],
        "grade_unavailable": [event(1, skill="fn.slope")],
        "duplicate_record": [event(1), event(1)],
    }[kind]


def background_noise():
    return [event(9001, "not_completed"), event(9002, skill="not.a.real.skill"),
            event(9003, days=125), event(9004, days=-1),
            event(9005, skill="fn.slope")]


def run(seed=SEED, repeats=500):
    rng = random.Random(seed)
    bad = []
    correct = total = 0
    by_case = {}
    for kind, expected in EXPECTED.items():
        matched = 0
        for _ in range(repeats):
            data = evidence(kind) + background_noise()
            rng.shuffle(data)
            decision = select_instruction(data, "K-2", now=NOW)
            actual = decision.method if decision else None
            total += 1
            if actual == expected:
                matched += 1
                correct += 1
            elif len(bad) < 20:
                bad.append({"layer": "adaptive", "case": kind, "expected": expected, "actual": actual})
            if decision:
                instruction = render_instruction(decision, parent_focus=True)
                if "NEVER redirect" not in instruction or "Never claim a teaching move is experimentally proven" not in instruction:
                    if len(bad) < 20:
                        bad.append({"layer": "adaptive", "case": kind, "fault": "educator_precedence"})
        by_case[kind] = {"matched": matched, "trials": repeats}
    teaching_ok = all(v["matched"] == repeats for v in by_case.values()) and not any(f["layer"] == "adaptive" for f in bad)

    kinds = ["valid", "unit_swap", "missing_grade", "missing_window", "invented_risk",
             "bad_percentage", "extra_test_material", "wrong_framework", "fake_help", "nan"]
    data_cases = {}
    data_total = data_correct = 0
    for kind in kinds:
        matched = 0
        for _ in range(repeats):
            measure = rng.choice(sorted(DIBELS_UNITS))
            unit = DIBELS_UNITS[measure]
            entry = {
                "framework": "dibels8", "measure": measure,
                "assessed_on": date(2026, 10, 12).isoformat(),
                "source_name": "Synthetic third-party educator report",
                "score": 91 if unit == "percent" else 70,
                "score_unit": unit, "reported_band": "not_reported",
                "assessed_grade": "4", "assessment_window": "middle_of_year",
            }
            if kind == "unit_swap": entry["score_unit"] = "other"
            elif kind == "missing_grade": entry["assessed_grade"] = None
            elif kind == "missing_window": entry["assessment_window"] = None
            elif kind == "invented_risk": entry["reported_band"] = "classified_by_ai"
            elif kind == "bad_percentage": entry.update(measure="ORF_ACCURACY", score=110, score_unit="percent")
            elif kind == "extra_test_material": entry["item_stimulus"] = "SYNTHETIC PLACEHOLDER"
            elif kind == "wrong_framework": entry["framework"] = "fake_test"
            elif kind == "fake_help": entry["assistance"] = "unaided"
            elif kind == "nan": entry["score"] = float("nan")
            try:
                EducatorAssessmentSubmission.model_validate(entry)
                allowed = True
            except ValidationError:
                allowed = False
            expected_allowed = kind == "valid"
            data_total += 1
            if allowed == expected_allowed:
                matched += 1
                data_correct += 1
            elif len(bad) < 20:
                bad.append({"layer": "dibels", "case": kind, "should_accept": expected_allowed, "accepted": allowed})
        data_cases[kind] = {"matched": matched, "trials": repeats}
    catalog = next(c for c in frameworks_catalog() if c["id"] == "dibels8")
    catalog_valid = (catalog["measure_units"] == DIBELS_UNITS and
                     catalog["interpretation"] == "educator_supplied_only" and
                     "cut_scores" not in catalog)
    passed = teaching_ok and data_correct == data_total and catalog_valid
    return {
        "schema_version": 1, "seed": seed, "repetitions": repeats,
        "simulation": "synthetic_software_behavior_only",
        "real_student_records": False, "live_ai_model_called": False,
        "DIBELS_test_content": False, "external_accounts_contacted": False,
        "claimed_learning_improvements": False,
        "policy_version": POLICY_VERSION, "sources": SOURCES,
        "adaptive": {"trials": total, "matched": correct, "scenarios": by_case},
        "assessment": {"trials": data_total, "matched": data_correct,
                       "scenarios": data_cases, "official_catalog_contract": catalog_valid},
        "sample_faults": bad, "result": "pass" if passed else "fail",
        "unverified": [
            "Whether the LLM actually delivered each recommended teaching move",
            "Whether real learners improve on independent assessments",
            "Whether teacher preparation time decreases",
            "Production installation, MFA device flows and recovery",
            "No direct DIBELS administration or proprietary scoring",
        ],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--repetitions", type=int, default=500)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    if not 1 <= args.repetitions <= 10_000:
        p.error("repetitions must be 1 to 10000")
    outcome = run(args.seed, args.repetitions)
    print(json.dumps(outcome, sort_keys=True, indent=2))
    return 0 if outcome["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
