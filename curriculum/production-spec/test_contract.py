"""Synthetic acceptance fixtures; these tests do not authorize or evaluate teaching."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from contract import (
    ContractError, MODELS, ROOT, canonical, check, checked_file, digest, export,
    idempotency, invalidated, load_module, read_bundle, ref, resume_decision,
    timestamp, transition,
)
from example import ASSET, NOW, example
from schema import SCHEMA, validate
from vocabulary import existing_skills, literal_vocabulary

BASE = Path(__file__).parent / "fixtures"


def refresh(bundle):
    """Rebind fixture hashes after a mutation so a deeper denial is exercised."""
    for lesson in bundle["lessons"]:
        for usage in lesson["source_refs"]:
            source = next(s for s in bundle["sources"] if s["id"] == usage["source"]["id"])
            usage["source"] = ref(source)
    for unit in bundle["units"]:
        for index, child in enumerate(unit["lesson_refs"]):
            unit["lesson_refs"][index] = ref(
                next(l for l in bundle["lessons"] if l["id"] == child["id"]))
    for index, child in enumerate(bundle["grade"]["unit_refs"]):
        bundle["grade"]["unit_refs"][index] = ref(
            next(u for u in bundle["units"] if u["id"] == child["id"]))
    for gate in bundle["gates"]:
        gate["target"] = ref(bundle["grade"])
    bundle["ledger"]["idempotency_key"] = idempotency(bundle["ledger"])


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.bundle = example()

    def deny(self, pattern, mutate, rebind=True):
        mutate(self.bundle)
        if rebind:
            refresh(self.bundle)
        with self.assertRaisesRegex(ContractError, pattern):
            check(self.bundle, BASE)

    def test_valid_fixture_and_canonical_roundtrip(self):
        self.assertEqual(check(self.bundle, BASE), digest(export(self.bundle)))
        self.assertEqual(check(json.loads(canonical(self.bundle)), BASE),
                         check(self.bundle, BASE))

    def test_reuses_upstream_models_and_existing_skill(self):
        source = self.bundle["sources"][0]
        model = MODELS.SourceRecord(source["id"], source["edition"], source["url"],
                                    timestamp(NOW), ASSET["sha256"], MODELS.RightsStatus.original)
        self.assertEqual(model.source_id, source["id"])
        self.assertEqual(self.bundle["lessons"][0]["skill_ids"], ["sp.scatter_plots"])

    def test_feature_defaults_off_without_environment_modification(self):
        flag = load_module("bede_spec_flag", ROOT / "homeschool-api/services/curriculum/flag.py")
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(flag.curriculum_engine_enabled())

    def test_export_is_deterministic_and_excludes_ledger(self):
        before = canonical(export(self.bundle))
        self.bundle["ledger"]["workspace"] = "different-machine"
        self.bundle["ledger"]["updated_at"] = "2026-11-13T12:00:00Z"
        self.assertEqual(before, canonical(export(self.bundle)))
        reversed_keys = dict(reversed(list(export(self.bundle).items())))
        self.assertEqual(before, canonical(reversed_keys))
        self.assertNotIn("ledger", export(self.bundle))

    def test_source_content_is_hashed_as_bytes(self):
        self.assertEqual(checked_file(BASE, ASSET),
                         b"Synthetic pairs: (1,2), (2,4), (3,6). No learner data.\n")

    def test_tampered_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pairs.txt").write_text("tampered")
            with self.assertRaisesRegex(ContractError, "size mismatch"):
                check(self.bundle, root)

    def test_stale_source_hash(self):
        self.deny("stale exact reference",
                  lambda b: b["sources"][0].update(version=2), rebind=False)

    def test_stale_lesson_hash(self):
        self.deny("stale exact reference",
                  lambda b: b["lessons"][0].update(title="Changed rubric scope"), rebind=False)

    def test_stale_unit_hash(self):
        self.deny("stale exact reference",
                  lambda b: b["units"][0].update(adult_minutes=20), rebind=False)

    def test_unknown_field(self):
        self.deny("unknown fields", lambda b: b["lessons"][0].update(approved_by="Typed name"))

    def test_missing_access(self):
        self.deny("missing required", lambda b: b["lessons"][0].pop("access"))

    def test_type_confusion(self):
        self.deny("wrong type", lambda b: b["lessons"][0].update(version=True))

    def test_no_grade_completion_claim(self):
        self.deny("incorrect constant", lambda b: b["grade"].update(complete=True))

    def test_unknown_schema_keyword_fails_closed(self):
        with self.assertRaisesRegex(ContractError, "unsupported"):
            validate({}, {"type": "object", "unevaluatedProperties": False})

    def test_schema_is_json_serializable_and_closed(self):
        self.assertEqual(json.loads(canonical(SCHEMA)), SCHEMA)
        self.assertFalse(SCHEMA["additionalProperties"])
        self.assertEqual(set(SCHEMA["required"]), set(SCHEMA["properties"]))

    def test_duplicate_ids(self):
        self.deny("duplicate source", lambda b: b["sources"].append(deepcopy(b["sources"][0])))

    def test_unknown_skill(self):
        self.deny("unknown skill", lambda b: b["objectives"][0].update(skill_ids=["invented"]))

    def test_no_tracked_skill_requires_explicit_declaration(self):
        self.deny("explicit objective skill mapping",
                  lambda b: b["objectives"][0].update(skill_ids=[]))

    def test_untracked_objectives_do_not_invent_mastery_ids(self):
        self.bundle["objectives"][0].update(skill_ids=[], exercises_no_tracked_skill=True)
        self.bundle["lessons"][0].update(skill_ids=[], exercises_no_tracked_skill=True)
        refresh(self.bundle)
        check(self.bundle, BASE)

    def test_vocabulary_reuses_nonmath_diagnostic_ids(self):
        skills = existing_skills(ROOT, __import__("contract").SKILLS)
        self.assertTrue({"sp.scatter_plots", "latin", "completeness", "inference",
                         "musical_elements", "cvc_blending"} <= skills)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "changed.py"
            path.write_text("DOMAINS = generate_skills()\n")
            with self.assertRaisesRegex(ContractError, "adapter reconciliation"):
                literal_vocabulary(path, "DOMAINS")

    def test_unknown_prerequisite(self):
        self.deny("unknown prerequisite",
                  lambda b: b["objectives"][0].update(prerequisites=["missing"]))

    def test_prerequisite_cycle(self):
        self.deny("cycle", lambda b: b["objectives"][0].update(
            prerequisites=[b["objectives"][0]["id"]]))

    def test_orphan_objective(self):
        def mutate(b):
            other = deepcopy(b["objectives"][0])
            other["id"] = "fixture-unused"
            b["objectives"].append(other)
        self.deny("orphan objective", mutate)

    def test_prerequisite_order(self):
        def mutate(b):
            prerequisite = deepcopy(b["objectives"][0])
            prerequisite["id"] = "fixture-entry"
            b["objectives"].append(prerequisite)
            b["objectives"][0]["prerequisites"] = [prerequisite["id"]]
        self.deny("prerequisite order", mutate)

    def test_missing_permission(self):
        self.deny("permission blocked", lambda b: b["sources"][0]["permissions"]["copy"].update(
            decision="pending"))

    def test_no_training_by_default(self):
        self.deny("training not authorized", lambda b: b["sources"][0]["permissions"]["training"].update(
            decision="allowed"))

    def test_permission_needs_evidence(self):
        self.deny("permission evidence", lambda b: b["sources"][0]["permissions"]["copy"].update(
            evidence_refs=[]))

    def test_verbatim_not_relabelable(self):
        self.deny("verbatim requires verified public domain",
                  lambda b: b["lessons"][0]["source_refs"][0].update(verbatim=True))

    def test_licensed_requires_separate_pathway_not_a_string(self):
        def mutate(b):
            b["sources"][0].update(rights="licensed", licensed_pathway_ref="typed:approval")
        self.deny("separately authenticated pathway", mutate)

    def test_unverified_rights_cannot_stage(self):
        self.deny("not eligible", lambda b: b["sources"][0].update(rights="unverified"))

    def test_independent_evidence_required(self):
        self.deny("assessment coverage gap", lambda b: b["lessons"][0].update(
            assessments=[a for a in b["lessons"][0]["assessments"] if a["kind"] != "independent"]))

    def test_delayed_interval(self):
        self.deny("delayed evidence interval",
                  lambda b: b["lessons"][0]["assessments"][2].update(delay_days=0))

    def test_explicit_teaching_required(self):
        self.deny("missing teaching mode", lambda b: b["lessons"][0]["steps"].pop(0))

    def test_teacher_output_required(self):
        self.deny("array bounds", lambda b: b["lessons"][0]["outputs"].pop())

    def test_student_key_leakage(self):
        self.deny("key leakage", lambda b: b["lessons"][0]["outputs"][0]["sections"].append("Answer key"))

    def test_agent_review_needs_evidence(self):
        self.deny("independent academic evidence",
                  lambda b: b["lessons"][0].update(status="agent_reviewed"))

    def evidence(self):
        return {
            "id": "fixture-evidence", "target": ref(self.bundle["lessons"][0]),
            "author_run": "fixture-author", "reviewer_run": "fixture-reviewer",
            "reviewer_identity": "fixture-agent", "reviewer_version": "unavailable",
            "role": "agent_academic", "at": NOW, "scope": "Synthetic structure test only",
            "methods": ["Fixture test"], "artifacts": [deepcopy(ASSET)], "findings": [],
            "disagreements": [], "conditions": [], "decision": "agent_reviewed",
            "command": "fixture assertion; not a real academic review", "result": "synthetic only",
        }

    def test_separate_agent_record_is_not_human_gate(self):
        self.bundle["evidence"] = [self.evidence()]
        check(self.bundle, BASE)
        self.assertTrue(all(g["state"] == "pending" for g in self.bundle["gates"]))

    def test_self_review_denied(self):
        record = self.evidence()
        record["reviewer_run"] = record["author_run"]
        self.bundle["evidence"] = [record]
        with self.assertRaisesRegex(ContractError, "self review"):
            check(self.bundle, BASE)

    def test_stale_review_denied(self):
        self.bundle["evidence"] = [self.evidence()]
        self.deny("stale exact reference", lambda b: b["lessons"][0].update(title="Changed"))

    def test_string_only_human_approval_denied(self):
        self.deny("trusted workflow", lambda b: b["gates"][0].update(
            state="externally_recorded", receipt_ref="human:claimed-name"))

    def test_gate_cannot_disappear(self):
        self.deny("array bounds", lambda b: b["gates"].pop())

    def test_idempotency_binds_inputs_and_versions(self):
        before = idempotency(self.bundle["ledger"])
        self.bundle["ledger"]["versions"]["content"] = "different"
        self.assertNotEqual(before, idempotency(self.bundle["ledger"]))

    def test_wrong_idempotency_rejected(self):
        self.deny("wrong idempotency", lambda b: b["ledger"].update(idempotency_key="f" * 64),
                  rebind=False)

    def test_unknown_usage_stays_null(self):
        check(self.bundle, BASE)
        self.assertIsNone(self.bundle["ledger"]["usage"]["cost"])
        self.deny("unmeasured usage", lambda b: b["ledger"]["usage"].update(cost=0))

    def test_unknown_or_oversized_resource_limits(self):
        self.deny("wrong type", lambda b: b["ledger"]["limits"].update(memory_mib=None))
        self.bundle = example()
        self.deny("approved bound", lambda b: b["ledger"]["limits"].update(concurrency=2))

    def test_invalid_time_is_not_accepted_as_a_string(self):
        self.deny("invalid UTC timestamp",
                  lambda b: b["ledger"].update(updated_at="2026-99-99T12:00:00Z"))

    def test_reversed_timestamps(self):
        self.deny("out of order",
                  lambda b: b["ledger"].update(updated_at="2026-11-11T12:00:00Z"))

    def test_completed_job_needs_output_and_checks(self):
        self.deny("missing outputs", lambda b: b["ledger"].update(
            status="succeeded", finished_at=NOW))

    def test_repair_budget_and_cancellation_are_terminal(self):
        transition("failed", "queued", repair_attempts=3)
        for before, after, kwargs in [
            ("failed", "queued", {"repair_attempts": 4}),
            ("canceled", "running", {}),
            ("blocked", "queued", {}),
        ]:
            with self.subTest(before=before, after=after, kwargs=kwargs):
                with self.assertRaises(ContractError):
                    transition(before, after, **kwargs)
        transition("blocked", "queued", blocker_resolved=True)

    def test_canceled_checkpoint_needs_reason_and_time(self):
        self.deny("missing cancellation request", lambda b: b["ledger"].update(
            status="canceled", finished_at=NOW))

    def test_resume_and_stale_invalidation(self):
        ledger = self.bundle["ledger"]
        self.assertEqual(resume_decision(ledger, ledger["inputs"], ledger["versions"], BASE),
                         "verify_checkpoint_and_lease")
        self.assertEqual(resume_decision(ledger, [], ledger["versions"], BASE), "stale")
        ledger.update(status="succeeded", outputs=[deepcopy(ASSET)])
        self.assertEqual(resume_decision(ledger, ledger["inputs"], ledger["versions"], BASE), "reuse")
        ledger["outputs"][0]["sha256"] = "f" * 64
        with self.assertRaisesRegex(ContractError, "hash mismatch"):
            resume_decision(ledger, ledger["inputs"], ledger["versions"], BASE)
        ledger["status"] = "canceled"
        self.assertEqual(resume_decision(ledger, [], {}, BASE), "canceled")

    def test_transitive_invalidation(self):
        graph = {"lesson": ["source", "rubric"], "unit": ["lesson"], "grade": ["unit"]}
        self.assertEqual(invalidated({"source"}, graph), {"source", "lesson", "unit", "grade"})
        self.assertEqual(invalidated({"unrelated"}, graph), {"unrelated"})

    def test_path_traversal_and_missing_artifact(self):
        for path in ("../LICENSE", "/etc/passwd", "missing.txt"):
            with self.subTest(path=path):
                with self.assertRaises(ContractError):
                    checked_file(BASE, {**ASSET, "path": path})

    def test_symlink_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "escape").symlink_to(BASE / "pairs.txt")
            with self.assertRaisesRegex(ContractError, "escapes workspace"):
                checked_file(root, {**ASSET, "path": "escape"})

    def test_duplicate_json_key_nonfinite_and_size_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            for data in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":'):
                path.write_text(data)
                with self.subTest(data=data):
                    with self.assertRaises(ContractError):
                        read_bundle(path)
            path.write_bytes(b" " * (1048576 + 1))
            with self.assertRaisesRegex(ContractError, "too large"):
                read_bundle(path)

    def test_depth_and_collection_bounds(self):
        with self.assertRaisesRegex(ContractError, "depth"):
            validate([], {"type": "array"}, depth=33)
        with self.assertRaisesRegex(ContractError, "array bounds"):
            validate([0] * 257, {"type": "array", "items": {}})
        with self.assertRaisesRegex(ContractError, "below minimum"):
            validate(-1, {"type": "integer", "minimum": 0})
        with self.assertRaisesRegex(ContractError, "nonfinite"):
            validate(float("inf"), {"type": "number"})


if __name__ == "__main__":
    unittest.main()
