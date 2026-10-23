"""Metrics preserve observed evidence rather than inventing PASS."""
import importlib.util
import unittest
from pathlib import Path
spec = importlib.util.spec_from_file_location("qa_metrics", Path(__file__).resolve().parents[1] / "metrics.py")
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)

class MetricsTests(unittest.TestCase):
    def test_empty_evidence_does_not_claim_pass(self):
        result = metrics.aggregate([])
        self.assertIsNone(result["first_pass_rate"])
        self.assertEqual(result["evaluated"], 0)

    def test_first_pass_differs_from_repaired_pass(self):
        report = {"results": [
            {"exit_code": 1, "category": "outdated_test",
             "diagnostic_excerpt": "AssertionError at line 31", "attempt": 1},
            {"exit_code": 0, "attempt": 2},
        ], "merge_status": "ready for external CI and security gates",
           "runner_seconds": 10}
        data = metrics.aggregate([report, report])
        self.assertEqual(data["pass_rate"], 1)
        self.assertEqual(data["first_pass_rate"], 0)
        self.assertEqual(data["repair_cycles"], 2)
        self.assertEqual(data["failure_categories"]["outdated_test"], 2)
        self.assertEqual(len(data["recurrences"]), 1)
        self.assertIsNone(data["github_billed_minutes"])

if __name__ == "__main__":
    unittest.main()
