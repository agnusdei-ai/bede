"""Pure reference checks and deterministic review export; no promotion authority."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from schema import ContractError, GATES, SCHEMA, validate
from vocabulary import existing_skills

ROOT = Path(__file__).resolve().parents[2]
VERSION = "1.0.0"
MAX_INPUT = 1024 * 1024


def require(condition, message):
    if not condition:
        raise ContractError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def ref(value):
    return {"id": value["id"], "version": value["version"], "sha256": digest(value)}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MODELS = load_module("bede_spec_models", ROOT / "homeschool-api/services/curriculum/models.py")
SKILLS = load_module("bede_spec_skills", ROOT / "homeschool-api/services/diagnostic/skill_map.py")


def timestamp(value):
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError) as error:
        raise ContractError("invalid UTC timestamp") from error


def checked_file(base, record):
    path = Path(record["path"])
    require(not path.is_absolute() and ".." not in path.parts, "unsafe artifact path")
    resolved = (base / path).resolve()
    require(resolved.is_relative_to(base.resolve()), "artifact escapes workspace")
    require(resolved.is_file(), "missing artifact")
    require(resolved.stat().st_size <= MAX_INPUT, "artifact too large")
    data = resolved.read_bytes()
    require(len(data) == record["bytes"], "artifact size mismatch")
    require(hashlib.sha256(data).hexdigest() == record["sha256"], "artifact hash mismatch")
    return data


def unique(items, label):
    by_id = {item["id"]: item for item in items}
    require(len(by_id) == len(items), f"duplicate {label} ID")
    return by_id


def resolve(reference, records):
    target = records.get(reference["id"])
    require(target is not None and reference == ref(target), "missing or stale exact reference")
    return target


def acyclic(objectives):
    visited, active = set(), set()

    def visit(key):
        require(key in objectives, "unknown prerequisite")
        require(key not in active, "prerequisite cycle")
        if key in visited:
            return
        active.add(key)
        for parent in objectives[key]["prerequisites"]:
            visit(parent)
        active.remove(key)
        visited.add(key)

    for key in objectives:
        visit(key)


def idempotency(ledger):
    return digest({key: (sorted(ledger[key], key=lambda f: f["path"])
                         if key == "inputs" else ledger[key])
                   for key in ("task_ref", "workspace", "inputs", "versions")})


TRANSITIONS = {
    "queued": {"running", "blocked", "canceled"},
    "running": {"succeeded", "failed", "blocked", "canceled"},
    "failed": {"queued", "blocked", "canceled"},
    "blocked": {"queued", "canceled"},
    "succeeded": {"stale"}, "stale": {"queued", "canceled"}, "canceled": set(),
}


def transition(before, after, *, repair_attempts=0, blocker_resolved=False):
    require(after in TRANSITIONS.get(before, set()), "invalid ledger transition")
    require(repair_attempts <= 3, "repair budget exhausted")
    if before == "blocked" and after == "queued":
        require(blocker_resolved, "unresolved blocker")


def invalidated(changed, dependencies):
    """Return changed records and all transitive consumers, without executing."""
    stale = set(changed)
    while True:
        expanded = stale | {item for item, inputs in dependencies.items() if stale & set(inputs)}
        if expanded == stale:
            return stale
        stale = expanded


def resume_decision(ledger, current_inputs, versions, base):
    """No execution: report reuse, stale, canceled or checkpoint verification."""
    if ledger["status"] == "canceled":
        return "canceled"
    if (ledger["inputs"] != current_inputs or ledger["versions"] != versions
            or ledger["status"] == "stale"):
        return "stale"
    for output in ledger["outputs"]:
        checked_file(base, output)
    return "reuse" if ledger["status"] == "succeeded" else "verify_checkpoint_and_lease"


def check_ledger(ledger, base):
    require(ledger["idempotency_key"] == idempotency(ledger), "wrong idempotency key")
    require(ledger["versions"]["schema"] == VERSION and ledger["versions"]["tool"] == VERSION,
            "unsupported contract/tool version")
    require(ledger["repair_attempts"] <= 3, "repair budget exhausted")
    limits = ledger["limits"]
    for name, ceiling in (("wall_seconds", 30), ("memory_mib", 256),
                          ("input_bytes", MAX_INPUT), ("output_bytes", 10485760),
                          ("concurrency", 1)):
        require(limits[name] <= ceiling, "offline limit exceeds approved bound")
    times = [timestamp(ledger[k]) for k in ("started_at", "updated_at")]
    require(times[0] <= times[1], "ledger timestamps out of order")
    if ledger["status"] in {"succeeded", "failed", "canceled"}:
        require(ledger["finished_at"] is not None, "missing completion timestamp")
    if ledger["finished_at"] is not None:
        require(times[0] <= timestamp(ledger["finished_at"]) <= times[1],
                "invalid completion timestamp")
    cancellation = ledger["cancellation"]
    if cancellation["requested_at"] is not None:
        require(times[0] <= timestamp(cancellation["requested_at"]) <= times[1],
                "invalid cancellation timestamp")
        require(cancellation["reason"] is not None, "missing cancellation reason")
    if ledger["status"] == "canceled":
        require(cancellation["requested_at"] is not None, "missing cancellation request")
    if ledger["status"] == "blocked":
        require(bool(ledger["blockers"]), "missing blocker")
    usage = ledger["usage"]
    if any(usage[k] is not None for k in ("tokens", "seconds", "cost")):
        require(usage["measurement_source"] is not None, "unmeasured usage")
    if usage["cost"] is not None:
        require(usage["currency"] is not None, "cost currency missing")
    for record in ledger["inputs"] + ledger["outputs"] + ledger["artifacts"]:
        checked_file(base, record)
    if ledger["status"] == "succeeded":
        require(bool(ledger["outputs"]), "successful job missing outputs")
        require(all(v["result"] == "pass" for v in ledger["validations"]),
                "successful job has incomplete validation")


def check(bundle, base):
    validate(bundle)
    sources = unique(bundle["sources"], "source")
    objectives = unique(bundle["objectives"], "objective")
    lessons = unique(bundle["lessons"], "lesson")
    units = unique(bundle["units"], "unit")
    all_records = unique(bundle["sources"] + bundle["objectives"] + bundle["lessons"]
                         + bundle["units"] + [bundle["grade"]], "bundle")
    acyclic(objectives)
    known_skills = existing_skills(ROOT, SKILLS)
    for objective in objectives.values():
        require(set(objective["skill_ids"]) <= known_skills, "unknown skill")
        require(objective["exercises_no_tracked_skill"] == (not objective["skill_ids"]),
                "explicit objective skill mapping required")
    for source in sources.values():
        timestamp(source["retrieved_at"])
        checked_file(base, source["asset"])
        require(source["permissions"]["training"]["decision"] == "denied",
                "training not authorized")
        for permission in source["permissions"].values():
            if permission["decision"] == "allowed":
                require(bool(permission["evidence_refs"]), "permission evidence missing")
                require(bool(source["rights_evidence_refs"]), "source rights evidence missing")
        MODELS.SourceRecord(source["id"], source["edition"], source["url"],
                            timestamp(source["retrieved_at"]), source["asset"]["sha256"],
                            MODELS.RightsStatus(source["rights"]))
    for lesson in lessons.values():
        require(set(lesson["objective_ids"] + lesson["prerequisites"]) <= set(objectives),
                "unknown lesson objective")
        require(set(lesson["skill_ids"]) <= known_skills, "unknown lesson skill")
        require(lesson["exercises_no_tracked_skill"] == (not lesson["skill_ids"]),
                "explicit lesson skill mapping required")
        for oid in lesson["objective_ids"]:
            require(set(objectives[oid]["skill_ids"]) <= set(lesson["skill_ids"]),
                    "lesson skill mapping incomplete")
        require({s["mode"] for s in lesson["steps"]} ==
                {"explicit_teaching", "worked_example", "seminar", "studio", "practice", "exit"},
                "missing teaching mode")
        source_rights = []
        for usage in lesson["source_refs"]:
            source = resolve(usage["source"], sources)
            require(source["rights"] not in {"unverified", "teacher_private"},
                    "source not eligible for shared draft")
            source_rights.append(MODELS.RightsStatus(source["rights"]))
            if usage["verbatim"]:
                require(source["rights"] == "public_domain_verified",
                        "verbatim requires verified public domain")
            for use in usage["uses"]:
                require(source["permissions"][use]["decision"] == "allowed",
                        f"source permission blocked: {use}")
                if source["rights"] == "licensed":
                    raise ContractError("licensed use needs separately authenticated pathway")
        MODELS.Lesson(lesson["id"], lesson["title"], tuple(lesson["objective_ids"]),
                      tuple(lesson["skill_ids"]), lesson["subject"], lesson["stage"],
                      "fixture-campus", MODELS.Visibility.campus, MODELS.ItemStatus.staged,
                      lesson["version"], tuple(u["source"]["id"] for u in lesson["source_refs"]),
                      tuple(source_rights))
        unique(lesson["assessments"], "assessment")
        for assessment in lesson["assessments"]:
            require(assessment["objective_id"] in lesson["objective_ids"], "unmapped assessment")
            if assessment["kind"] == "delayed":
                require(7 <= assessment["delay_days"] <= 14, "delayed evidence interval")
        for oid in lesson["objective_ids"]:
            require({a["kind"] for a in lesson["assessments"] if a["objective_id"] == oid} ==
                    {"guided", "independent", "delayed", "transfer"}, "assessment coverage gap")
        require({o["kind"] for o in lesson["outputs"]} == {"student", "teacher"},
                "student and teacher outputs required")
        for output in lesson["outputs"]:
            require(set(output["attribution_source_ids"]) <= set(sources), "unknown attribution")
            if output["kind"] == "student":
                require(not any("key" in s.lower() or "solution" in s.lower()
                                for s in output["sections"]), "student key leakage")
    seen_lessons = set()
    available = set()
    for unit_ref in bundle["grade"]["unit_refs"]:
        unit = resolve(unit_ref, units)
        require(set(unit["prerequisites"]) <= set(objectives), "unknown unit prerequisite")
        available.update(unit["prerequisites"])
        covered = set()
        for lesson_ref in unit["lesson_refs"]:
            lesson = resolve(lesson_ref, lessons)
            require(lesson["id"] not in seen_lessons, "duplicate lesson placement")
            seen_lessons.add(lesson["id"])
            needed = set(lesson["prerequisites"])
            for oid in lesson["objective_ids"]:
                needed.update(objectives[oid]["prerequisites"])
            require(needed <= available, "prerequisite order")
            available.update(lesson["objective_ids"])
            covered.update(lesson["objective_ids"])
        require(set(unit["objective_ids"]) == covered, "unit objective coverage")
    require(seen_lessons == set(lessons), "orphan lesson")
    require({r["id"] for r in bundle["grade"]["unit_refs"]} == set(units), "orphan unit")
    require({oid for lesson in lessons.values() for oid in lesson["objective_ids"]}
            == set(objectives), "orphan objective")
    for evidence in bundle["evidence"]:
        resolve(evidence["target"], all_records)
        require(evidence["author_run"] != evidence["reviewer_run"], "self review")
        timestamp(evidence["at"])
        for artifact in evidence["artifacts"]:
            checked_file(base, artifact)
    for lesson in lessons.values():
        if lesson["status"] == "agent_reviewed":
            require(any(e["target"] == ref(lesson) and e["role"] == "agent_academic"
                        and e["decision"] == "agent_reviewed" and not e["findings"]
                        and not e["disagreements"] and not e["conditions"]
                        for e in bundle["evidence"]), "missing independent academic evidence")
    require(len(bundle["gates"]) == len(GATES)
            and {g["kind"] for g in bundle["gates"]} == set(GATES), "missing/duplicate gates")
    for gate in bundle["gates"]:
        resolve(gate["target"], all_records)
        require(gate["state"] == "pending" and gate["receipt_ref"] is None,
                "human approvals require trusted workflow resolution, not offline strings")
    check_ledger(bundle["ledger"], base)
    return digest(export(bundle))


def export(bundle):
    return {key: bundle[key] for key in
            ("schema_version", "sources", "objectives", "lessons", "units", "grade")}


def read_bundle(path):
    require(path.stat().st_size <= MAX_INPUT, "input too large")
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, "duplicate JSON key")
            value[key] = item
        return value
    def nonfinite(_):
        raise ContractError("nonfinite JSON number")
    try:
        return json.loads(path.read_bytes(), object_pairs_hook=pairs, parse_constant=nonfinite)
    except (ValueError, RecursionError) as error:
        raise ContractError(f"invalid JSON: {error}") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "schema", "export"))
    parser.add_argument("path", nargs="?", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "schema":
            print(canonical(SCHEMA).decode())
            return
        if args.path is None:
            from example import example
            bundle = example()
            base = Path(__file__).parent / "fixtures"
        else:
            bundle = read_bundle(args.path)
            base = args.path.parent
        output_hash = check(bundle, base)
        if args.action == "export":
            print(canonical(export(bundle)).decode())
        else:
            print(f"PASS contract {VERSION}; review export sha256={output_hash}; no approval")
    except (ContractError, OSError, MODELS.CurriculumModelError) as error:
        parser.exit(1, f"BLOCKED: {error}\n")


if __name__ == "__main__":
    main()
