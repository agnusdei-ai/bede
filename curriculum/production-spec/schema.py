"""Proprietary, dependency-free curriculum schema and bounded subset validator."""
from __future__ import annotations

import math
import re


class ContractError(ValueError):
    """An invalid specification is not an approved curriculum."""


def obj(**properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def arr(items, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": 256}


def choice(*values):
    return {"enum": list(values)}


TEXT = {"type": "string", "minLength": 1, "maxLength": 4096}
HASH = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
TIME = {"type": "string", "pattern": r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$"}
POS = {"type": "integer", "minimum": 1}
NAT = {"type": "integer", "minimum": 0}
NULL_TEXT = {"type": ["string", "null"], "minLength": 1}
NULL_NUMBER = {"type": ["number", "null"], "minimum": 0}
REF = obj(id=TEXT, version=POS, sha256=HASH)
FILE = obj(path=TEXT, sha256=HASH, bytes=NAT)
PERMISSION = obj(decision=choice("allowed", "denied", "pending"),
                 evidence_refs=arr(TEXT))
USES = ("copy", "distribution", "adaptation", "tts", "storage",
        "retrieval", "model_processing", "training")
SOURCE = obj(
    id=TEXT, version=POS, title=TEXT, creator_editor_translator=TEXT,
    edition=TEXT, url=TEXT, retrieved_at=TIME, asset=FILE,
    rights=choice("original", "public_domain_verified", "licensed",
                  "teacher_private", "unverified"),
    territory=TEXT, license=TEXT, attribution=TEXT, notices=arr(TEXT),
    rights_evidence_refs=arr(TEXT), permissions=obj(**{use: PERMISSION for use in USES}),
    licensed_pathway_ref=NULL_TEXT,
)
OBJECTIVE = obj(id=TEXT, version=POS, statement=TEXT, skill_ids=arr(TEXT),
                exercises_no_tracked_skill={"type": "boolean"}, skill_mapping_rationale=TEXT,
                prerequisites=arr(TEXT), success_criteria=TEXT)
ASSESSMENT = obj(
    id=TEXT, objective_id=TEXT,
    kind=choice("guided", "independent", "delayed", "transfer"),
    delay_days=NAT, prompt=TEXT, key_rubric=TEXT, supports=arr(TEXT),
    prompt_rescue_record=TEXT, assessor_role=TEXT, success_criteria=TEXT,
)
ACCESS = obj(construct=TEXT, supports=arr(TEXT, 1), alternative_response=TEXT,
             privacy=TEXT, retention_deletion=TEXT)
SAFETY = obj(hazards=arr(TEXT), supervision=TEXT, stop_escalation=TEXT,
             safer_alternative=TEXT)
OUTPUT = obj(id=TEXT, version=POS, kind=choice("student", "teacher"),
             sections=arr(TEXT, 1), attribution_source_ids=arr(TEXT))
LESSON = obj(
    id=TEXT, version=POS, title=TEXT, subject=TEXT, stage=TEXT,
    status=choice("draft", "authored", "agent_reviewed"),
    objective_ids=arr(TEXT, 1), skill_ids=arr(TEXT),
    exercises_no_tracked_skill={"type": "boolean"}, skill_mapping_rationale=TEXT,
    prerequisites=arr(TEXT),
    source_refs=arr(obj(source=REF, locator=TEXT, uses=arr(choice(*USES), 1),
                        verbatim={"type": "boolean"}), 1),
    entry_evidence=TEXT,
    steps=arr(obj(mode=choice("explicit_teaching", "worked_example", "seminar",
                             "studio", "practice", "exit"),
                  minutes=POS, materials=arr(TEXT), instruction=TEXT), 1),
    assessments=arr(ASSESSMENT, 1), access=ACCESS, safety=SAFETY,
    outputs=arr(OUTPUT, 2),
)
UNIT = obj(id=TEXT, version=POS, title=TEXT, lesson_refs=arr(REF, 1),
           prerequisites=arr(TEXT), objective_ids=arr(TEXT, 1),
           culminating_task=TEXT, synthesis_reteaching=TEXT, adult_minutes=POS)
GRADE = obj(
    id=TEXT, version=POS, grade=choice(8, 9, 10, 11, 12),
    unit_refs=arr(REF, 1), entry_evidence=TEXT, domains=arr(TEXT, 1),
    calendar_weeks=POS, learner_minutes_week=POS, adult_minutes_week=POS,
    coverage_decisions=arr(TEXT, 1), completion_criteria=arr(TEXT, 1),
    transition_evidence=TEXT, complete={"const": False},
)
EVIDENCE = obj(
    id=TEXT, target=REF, author_run=TEXT, reviewer_run=TEXT,
    reviewer_identity=TEXT, reviewer_version=TEXT,
    role=choice("agent_academic", "rights_recommendation", "safety_recommendation"),
    at=TIME, scope=TEXT, methods=arr(TEXT, 1), artifacts=arr(FILE, 1),
    findings=arr(TEXT), disagreements=arr(TEXT), conditions=arr(TEXT),
    decision=choice("agent_reviewed", "changes_required", "blocked"),
    command=TEXT, result=TEXT,
)
GATES = ("academic", "rights", "human_promotion", "slice_human",
         "pilot", "release", "live")
GATE = obj(kind=choice(*GATES), target=REF,
           state=choice("pending", "externally_recorded"), receipt_ref=NULL_TEXT)
LEDGER = obj(
    task_ref=TEXT, parent_ref=NULL_TEXT, dependencies=arr(TEXT), workspace=TEXT,
    inputs=arr(FILE, 1), outputs=arr(FILE),
    versions=obj(schema=TEXT, tool=TEXT, content=TEXT),
    idempotency_key=HASH, sequence=POS, previous_event_hash=HASH,
    status=choice("queued", "running", "succeeded", "failed", "blocked",
                  "canceled", "stale"),
    initial_attempt=POS, repair_attempts=NAT, failure_cluster=NULL_TEXT,
    started_at=TIME, updated_at=TIME, finished_at={"type": ["string", "null"]},
    cancellation=obj(requested_at={"type": ["string", "null"]}, reason=NULL_TEXT),
    usage=obj(tokens=NULL_NUMBER, seconds=NULL_NUMBER, cost=NULL_NUMBER,
              currency=NULL_TEXT, measurement_source=NULL_TEXT),
    limits=obj(wall_seconds=POS, memory_mib=POS, input_bytes=POS, output_bytes=POS,
               concurrency=POS, paid_inference={"const": False}),
    validations=arr(obj(command=TEXT, result=choice("pass", "fail", "not_run"),
                        evidence_ref=TEXT), 1),
    artifacts=arr(FILE), blockers=arr(TEXT),
    reviewer_roles=arr(choice("agent_academic", "authenticated_human", "rights",
                             "safety", "owner", "school_administrator"), 1),
)
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Bede proprietary development curriculum contract",
    **obj(schema_version={"const": "1.0.0"}, fixture_only={"const": True},
          sources=arr(SOURCE, 1), objectives=arr(OBJECTIVE, 1),
          lessons=arr(LESSON, 1), units=arr(UNIT, 1), grade=GRADE,
          evidence=arr(EVIDENCE), gates=arr(GATE, len(GATES)), ledger=LEDGER),
}

KEYWORDS = {"$schema", "title", "type", "properties", "required",
            "additionalProperties", "items", "minItems", "maxItems", "enum",
            "const", "minLength", "maxLength", "pattern", "minimum"}


def validate(value, schema=SCHEMA, path="$", depth=0):
    """Validate only this schema's explicit subset; unsupported keywords fail."""
    if depth > 32:
        raise ContractError(f"{path}: maximum depth exceeded")
    if set(schema) - KEYWORDS:
        raise ContractError(f"{path}: unsupported schema keywords")
    if "const" in schema and (type(value) is not type(schema["const"])
                              or value != schema["const"]):
        raise ContractError(f"{path}: incorrect constant")
    if "enum" in schema and not any(
        type(value) is type(option) and value == option for option in schema["enum"]
    ):
        raise ContractError(f"{path}: invalid enum")
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        matches = {
            "object": type(value) is dict, "array": type(value) is list,
            "string": type(value) is str, "boolean": type(value) is bool,
            "integer": type(value) is int, "number": type(value) in (int, float),
            "null": value is None,
        }
        if not any(matches.get(t, False) for t in types):
            raise ContractError(f"{path}: wrong type")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if set(schema.get("required", [])) - set(value):
            raise ContractError(f"{path}: missing required fields")
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            raise ContractError(f"{path}: unknown fields")
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key], f"{path}.{key}", depth + 1)
    elif isinstance(value, list):
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 256):
            raise ContractError(f"{path}: array bounds")
        for index, item in enumerate(value):
            validate(item, schema.get("items", {}), f"{path}[{index}]", depth + 1)
    elif isinstance(value, str):
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 4096):
            raise ContractError(f"{path}: string bounds")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise ContractError(f"{path}: pattern mismatch")
    elif type(value) in (int, float):
        if type(value) is float and not math.isfinite(value):
            raise ContractError(f"{path}: nonfinite number")
        if value < schema.get("minimum", float("-inf")):
            raise ContractError(f"{path}: below minimum")
