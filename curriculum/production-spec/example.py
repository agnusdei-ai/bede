"""Executable structured fixture, not approved instruction or rights evidence."""
from copy import deepcopy

from contract import canonical, idempotency, ref
from schema import GATES, USES

NOW = "2026-11-12T12:00:00Z"
ASSET = {
    "path": "pairs.txt",
    "sha256": "3510bbfdd099d16bdf8dbe8ef166eaf58333fb4ae0f75f5eb404ff96743726da",
    "bytes": 55,
}


def example():
    """Return fresh fixture records with computed exact-version child references."""
    source = {
        "id": "fixture-source-pairs", "version": 1,
        "title": "Synthetic pairs", "creator_editor_translator": "Bede synthetic fixture",
        "edition": "fixture-1; text only; no external illustrations",
        "url": "fixture:pairs.txt", "retrieved_at": NOW, "asset": deepcopy(ASSET),
        "rights": "original", "territory": "Synthetic offline testing only",
        "license": "Bede proprietary; fixture assertions are not human rights approval",
        "attribution": "Bede synthetic contract fixture; not learner evidence",
        "notices": ["Repository proprietary LICENSE; no open license granted"],
        "rights_evidence_refs": ["fixture:original-synthetic-bytes"],
        "permissions": {
            use: {"decision": "allowed" if use in {"copy", "storage"} else "denied",
                  "evidence_refs": ["fixture:synthetic-test-only"]} for use in USES
        },
        "licensed_pathway_ref": None,
    }
    objective = {
        "id": "fixture-objective-scatter", "version": 1,
        "statement": "Illustrative mapping to an existing scatter-plot skill; not an approved outcome",
        "skill_ids": ["sp.scatter_plots"], "prerequisites": [],
        "exercises_no_tracked_skill": False,
        "skill_mapping_rationale": "Reuse existing diagnostic skill; synthetic example only",
        "success_criteria": "Fixture only: identify the three supplied pairs without interpreting causality",
    }
    assessment = {
        "id": "fixture-assessment-guided", "objective_id": objective["id"],
        "kind": "guided", "delay_days": 0,
        "prompt": "Synthetic contract prompt: state the second coordinate of (2,4).",
        "key_rubric": "4; fixture checks structure, not learner validity",
        "supports": ["Read aloud or point; record the chosen support"],
        "prompt_rescue_record": "Record prompts and rescue separately; no real learner records here",
        "assessor_role": "Responsible adult; synthetic test only",
        "success_criteria": "Correct coordinate and an explanation; criterion is illustrative only",
    }
    assessments = [assessment]
    for kind, prompt in (
        ("independent", "Novel fixture pair (4,8): identify the second coordinate without hints."),
        ("delayed", "At proposed day 7, novel fixture pair (5,10): identify the second coordinate."),
        ("transfer", "In a different synthetic measurement context, identify y in (6,12)."),
    ):
        item = deepcopy(assessment)
        item.update(id=f"fixture-assessment-{kind}", kind=kind, prompt=prompt,
                    delay_days=7 if kind == "delayed" else 0,
                    key_rubric={"independent": "8", "delayed": "10", "transfer": "12"}[kind])
        assessments.append(item)
    lesson = {
        "id": "fixture-lesson-pairs", "version": 1,
        "title": "Contract fixture, not authored instruction", "subject": "mathematics",
        "stage": "6-8", "status": "draft",
        "objective_ids": [objective["id"]], "skill_ids": ["sp.scatter_plots"],
        "exercises_no_tracked_skill": False,
        "skill_mapping_rationale": "Same existing skill as the illustrative objective",
        "prerequisites": [], "entry_evidence": "Pending real Grade 8 scope and entry assessment",
        "source_refs": [{"source": ref(source), "locator": "line 1",
                         "uses": ["copy", "storage"], "verbatim": False}],
        "steps": [
            {"mode": mode, "minutes": 2, "materials": ["Paper; synthetic pairs"],
             "instruction": instruction}
            for mode, instruction in (
                ("explicit_teaching", "Fixture slot: explain coordinate notation."),
                ("worked_example", "Fixture slot: model locating the second coordinate."),
                ("seminar", "Fixture slot: ask what a pattern does and does not establish."),
                ("studio", "Fixture slot: represent supplied synthetic points on paper."),
                ("practice", "Fixture slot: distinguish hints from independent work."),
                ("exit", "Fixture slot: collect a response and plan next steps."),
            )
        ],
        "assessments": assessments,
        "access": {
            "construct": "Coordinate interpretation, not handwriting or speech fluency",
            "supports": ["Large-print pairs", "Pointing or oral response"],
            "alternative_response": "Adult records the pointed coordinate without supplying it",
            "privacy": "Synthetic-only fixture; no names or student submissions",
            "retention_deletion": "Disposable test output; future evidence needs authorized retention",
        },
        "safety": {
            "hazards": ["No physical investigation authorized"],
            "supervision": "Responsible adult chooses appropriate paper task",
            "stop_escalation": "Stop unsafe suggestions; refer to responsible adult",
            "safer_alternative": "Use supplied synthetic pairs, not live personal measurements",
        },
        "outputs": [
            {"id": "fixture-student", "version": 1, "kind": "student",
             "sections": ["Reading", "Task", "Accessible response"],
             "attribution_source_ids": [source["id"]]},
            {"id": "fixture-teacher", "version": 1, "kind": "teacher",
             "sections": ["Explanation", "Worked solutions", "Misconceptions",
                          "Prompting and reteaching", "Safety and access", "Evidence collection"],
             "attribution_source_ids": [source["id"]]},
        ],
    }
    unit = {
        "id": "fixture-unit", "version": 1, "title": "One-lesson structural example",
        "lesson_refs": [ref(lesson)], "prerequisites": [],
        "objective_ids": [objective["id"]],
        "culminating_task": "Pending reviewed real-world synthesis; fixture only",
        "synthesis_reteaching": "Adult interprets independent evidence and selects next support",
        "adult_minutes": 10,
    }
    grade = {
        "id": "fixture-grade-8", "version": 1, "grade": 8,
        "unit_refs": [ref(unit)], "entry_evidence": "Pending baseline acceptance",
        "domains": ["Synthetic mathematics example only"], "calendar_weeks": 1,
        "learner_minutes_week": 12, "adult_minutes_week": 10,
        "coverage_decisions": ["Not a complete grade; all actual domains and sequence pending"],
        "completion_criteria": ["Must meet GATES.md; this fixture never qualifies"],
        "transition_evidence": "Unavailable; no learner work collected", "complete": False,
    }
    ledger = {
        "task_ref": "fixture-spec", "parent_ref": None, "dependencies": [],
        "workspace": "isolated-bede-development-fixture", "inputs": [deepcopy(ASSET)],
        "outputs": [], "versions": {"schema": "1.0.0", "tool": "1.0.0", "content": "fixture-1"},
        "idempotency_key": "0" * 64, "sequence": 1, "previous_event_hash": "0" * 64,
        "status": "blocked", "initial_attempt": 1, "repair_attempts": 0,
        "failure_cluster": None, "started_at": NOW, "updated_at": NOW, "finished_at": None,
        "cancellation": {"requested_at": None, "reason": None},
        "usage": {"tokens": None, "seconds": None, "cost": None,
                  "currency": None, "measurement_source": None},
        "limits": {"wall_seconds": 30, "memory_mib": 256, "input_bytes": 1048576,
                   "output_bytes": 10485760, "concurrency": 1, "paid_inference": False},
        "validations": [{"command": "fixture-only: no model execution",
                         "result": "not_run", "evidence_ref": "fixture:pending-execution"}],
        "artifacts": [], "blockers": ["Real Grade 8 scope, source rights and model limits pending"],
        "reviewer_roles": ["agent_academic", "authenticated_human", "rights", "safety",
                           "owner", "school_administrator"],
    }
    ledger["idempotency_key"] = idempotency(ledger)
    return {
        "schema_version": "1.0.0", "fixture_only": True, "sources": [source],
        "objectives": [objective], "lessons": [lesson], "units": [unit], "grade": grade,
        "evidence": [],
        "gates": [{"kind": kind, "target": ref(grade), "state": "pending", "receipt_ref": None}
                  for kind in GATES],
        "ledger": ledger,
    }


if __name__ == "__main__":
    print(canonical(example()).decode())
