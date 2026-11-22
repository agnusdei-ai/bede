"""Mock regression tests; no claim to subject-review correctness."""
import copy
import tempfile
from pathlib import Path
import unittest

from review_gate import SUBJECTS, digest, inspect


class ReviewGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in set().union(*SUBJECTS.values()) | {"reviews/report.md"}:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Mock evidence\n")
        self.records = [{
            "subject": subject, "agent_id": "test-reviewer",
            "agent_version": "not exposed by platform",
            "review_run": "review-run", "authoring_run": "author-run",
            "date": "2026-11-11", "scope": "Mock test scope",
            "methods": "Mock fixture", "evidence": "Mock report",
            "conditions": "Recorded scope only", "disagreements": "None recorded",
            "status": "agent-reviewed", "open_findings": [],
            "source_hashes": {name: digest(self.root / name) for name in names},
            "report": "reviews/report.md",
            "report_sha256": digest(self.root / "reviews/report.md"),
        } for subject, names in SUBJECTS.items()]

    def test_complete_fixture(self):
        self.assertEqual(inspect(self.records, self.root), ([], []))

    def test_no_human_identity_required(self):
        self.assertFalse(inspect(self.records, self.root)[0])

    def test_missing_subject(self):
        self.assertTrue(inspect(self.records[:-1], self.root)[0])

    def test_same_run_rejected(self):
        self.records[0]["review_run"] = "author-run"
        self.assertTrue(inspect(self.records, self.root)[0])

    def test_changed_source_invalidates_review(self):
        (self.root / "04-starter-lessons.md").write_text("Changed")
        self.assertTrue(inspect(self.records, self.root)[0])

    def test_missing_required_source(self):
        self.records[0]["source_hashes"].pop("04-starter-lessons.md")
        self.assertTrue(inspect(self.records, self.root)[0])

    def test_changed_report_invalidates_record(self):
        (self.root / "reviews/report.md").write_text("Changed")
        self.assertTrue(inspect(self.records, self.root)[0])

    def test_blocker_cannot_be_pass(self):
        self.records[0]["open_findings"] = ["Source support missing"]
        self.assertTrue(inspect(self.records, self.root)[0])

    def test_specific_defect_is_reported(self):
        self.records[0]["status"] = "blocked by specific defect"
        self.records[0]["open_findings"] = ["Missing edition rights evidence"]
        errors, blockers = inspect(self.records, self.root)
        self.assertEqual(errors, [])
        self.assertEqual(len(blockers), 1)

    def test_duplicate_review(self):
        self.records.append(copy.deepcopy(self.records[0]))
        self.assertTrue(inspect(self.records, self.root)[0])

    def test_out_of_scope_path(self):
        self.records[0]["report"] = "../outside.md"
        self.assertTrue(inspect(self.records, self.root)[0])

    def test_missing_metadata(self):
        del self.records[0]["agent_version"]
        self.assertTrue(inspect(self.records, self.root)[0])

    def test_fabricated_status_rejected(self):
        self.records[0]["status"] = "expert-certified"
        self.assertTrue(inspect(self.records, self.root)[0])


if __name__ == "__main__":
    unittest.main()
