"""Bede-original synthetic data; no learner or independent academic evidence."""
from copy import deepcopy
import hashlib

from boundary import contract as c
from schema import GATES, USES

TEXT = b"Bede synthetic coordinates: (1, 2), (2, 4), (3, 6).\n"
NOW = "2026-11-12T12:00:00Z"


def example():
    asset = dict(path="pairs.txt", bytes=len(TEXT), sha256=hashlib.sha256(TEXT).hexdigest())
    source = dict(
        id="synthetic-pairs", version=1, title="Bede synthetic pairs",
        creator_editor_translator="Bede", edition="Original synthetic fixture",
        url="fixture:pairs.txt", retrieved_at=NOW, asset=asset, rights="original",
        territory="Synthetic development testing only", license="Bede proprietary",
        attribution="Bede-original synthetic fixture; not learner evidence",
        notices=["Copyright 2026 Agnus Dei Technologies, LLC. All Rights Reserved."],
        rights_evidence_refs=["fixture:original-bytes"],
        permissions={use: dict(decision="allowed" if use in ("copy", "storage") else "denied",
                               evidence_refs=["fixture:synthetic-only"]) for use in USES},
        licensed_pathway_ref=None,
    )
    objective = dict(
        id="coordinate", version=1, statement="Identify the second coordinate.",
        skill_ids=["sp.scatter_plots"], exercises_no_tracked_skill=False,
        skill_mapping_rationale="Existing diagnostic mapping, not an effectiveness claim.",
        prerequisites=[], success_criteria="State and explain the second coordinate.",
    )
    assessments = [
        dict(id=kind, objective_id="coordinate", kind=kind,
             delay_days=7 if kind == "delayed" else 0,
             prompt=f"{kind}: identify the second coordinate of ({i}, {2*i}).",
             key_rubric=f"Second coordinate: {2*i}; independently verify before student use.",
             supports=["Large print or pointing"], prompt_rescue_record="Record prompts separately.",
             assessor_role="Responsible adult", success_criteria="Correct coordinate and explanation.")
        for i, kind in enumerate(("guided", "independent", "delayed", "transfer"), 1)
    ]
    lesson = dict(
        id="pairs", version=1, title="Synthetic coordinate fixture", subject="mathematics",
        stage="6-8", status="draft", objective_ids=["coordinate"], skill_ids=["sp.scatter_plots"],
        exercises_no_tracked_skill=False, skill_mapping_rationale="Same as objective.",
        prerequisites=[], entry_evidence="Not evaluated; synthetic only",
        source_refs=[dict(source=c.ref(source), locator="line 1",
                          uses=["copy", "storage"], verbatim=False)],
        steps=[dict(mode=mode, minutes=2, materials=["Paper"],
                    instruction=instruction) for mode, instruction in (
                        ("explicit_teaching", "Coordinate pairs give horizontal then vertical position."),
                        ("worked_example", "Adult models identifying the second coordinate."),
                        ("seminar", "What can a pattern establish?"),
                        ("studio", "Represent the synthetic points on paper."),
                        ("practice", "Explain how you located a coordinate."),
                        ("exit", "Record a response and discuss next steps."))],
        assessments=assessments,
        access=dict(construct="Coordinate interpretation, not handwriting",
                    supports=["Large print", "Pointing"], alternative_response="Point or speak.",
                    privacy="Synthetic only; no learner submissions.",
                    retention_deletion="Delete disposable test outputs when no longer needed."),
        safety=dict(hazards=[], supervision="Responsible adult.",
                    stop_escalation="Stop if unsafe; ask adult.", safer_alternative="Paper only."),
        outputs=[
            dict(id="student", version=1, kind="student", sections=["Tasks", "Access"],
                 attribution_source_ids=[source["id"]]),
            dict(id="teacher", version=1, kind="teacher", sections=["Solutions", "Safety"],
                 attribution_source_ids=[source["id"]]),
        ],
    )
    unit = dict(
        id="unit", version=1, title="Synthetic unit", lesson_refs=[c.ref(lesson)],
        prerequisites=[], objective_ids=["coordinate"], culminating_task="Pending real review.",
        synthesis_reteaching="Adult interprets evidence and chooses next supports.", adult_minutes=10,
    )
    grade = dict(
        id="grade", version=1, grade=8, unit_refs=[c.ref(unit)], entry_evidence="Not evaluated",
        domains=["Synthetic mathematics only"], calendar_weeks=1, learner_minutes_week=12,
        adult_minutes_week=10, coverage_decisions=["All other domains uncovered."],
        completion_criteria=["Not a complete grade."], transition_evidence="Unavailable", complete=False,
    )
    ledger = dict(
        task_ref="synthetic-factory", parent_ref=None, dependencies=[], workspace="fixture",
        inputs=[deepcopy(asset)], outputs=[], versions=dict(schema="1.0.0", tool="1.0.0", content="1"),
        idempotency_key="0"*64, sequence=1, previous_event_hash="0"*64, status="blocked",
        initial_attempt=1, repair_attempts=0, failure_cluster=None, started_at=NOW, updated_at=NOW,
        finished_at=None, cancellation=dict(requested_at=None, reason=None),
        usage=dict(tokens=None, seconds=None, cost=None, currency=None, measurement_source=None),
        limits=dict(wall_seconds=30, memory_mib=256, input_bytes=1048576, output_bytes=10485760,
                    concurrency=1, paid_inference=False),
        validations=[dict(command="synthetic fixture", result="not_run", evidence_ref="fixture:only")],
        artifacts=[], blockers=["Not instruction-ready"], reviewer_roles=["authenticated_human"],
    )
    ledger["idempotency_key"] = c.idempotency(ledger)
    return dict(
        schema_version="1.0.0", fixture_only=True, sources=[source], objectives=[objective],
        lessons=[lesson], units=[unit], grade=grade, evidence=[],
        gates=[dict(kind=kind, target=c.ref(grade), state="pending", receipt_ref=None)
               for kind in GATES], ledger=ledger,
    )


def write_fixture(directory):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pairs.txt").write_bytes(TEXT)
    (directory / "bundle.json").write_bytes(c.canonical(example()))
