"""QA reporting, deterministic bounded repair and dependency contracts."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


runner = load("runner")
deps = load("validate_dependencies")


class ReliabilityTests(unittest.TestCase):
    def test_command_allowlist_rejects_arbitrary_commands(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "demo").mkdir()
            p = {"version": 1, "head": "sha", "changed_modules": ["demo/src/App.tsx"],
                 "scopes": {"demo": {"tests": ["src/App.test.tsx"], "full": False, "reasons": []}},
                 "commands": [{"scope": "demo", "cwd": "demo", "argv": ["bash", "-c", "echo unsafe"]}],
                 "mandatory_external_gates": []}
            with self.assertRaises(ValueError):
                runner.execute(root, p, "demo", 1)

    def test_missing_test_commands_do_not_report_green(self):
        with tempfile.TemporaryDirectory() as td:
            p = {"head": "a", "changed_modules": ["demo/src/App.tsx"],
                 "scopes": {"demo": {"tests": ["src/App.test.tsx"], "full": False, "reasons": []}},
                 "commands": [], "mandatory_external_gates": []}
            with self.assertRaises(ValueError):
                runner.execute(Path(td), p, "demo", 1)

    def test_bounded_retries_are_enforced(self):
        with self.assertRaises(ValueError):
            runner.execute(Path("."), {}, "demo", 1, max_attempts=3)

    def test_semantic_failures_are_not_blindly_rerun(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "demo").mkdir()
            p = {"head": "a", "changed_modules": ["demo/src/App.tsx"],
                 "scopes": {"demo": {"tests": ["src/App.test.tsx"], "full": False, "reasons": []}},
                 "commands": [{"scope": "demo", "cwd": "demo", "argv": ["npx", "vitest", "run", "src/App.test.tsx"]}],
                 "mandatory_external_gates": []}
            failure = {"exit_code": 1, "duration_seconds": 1, "diagnostic_excerpt": "AssertionError",
                       "category": "outdated_test", "command": p["commands"][0]["argv"], "cwd": td}
            with patch.object(runner, "run_command", return_value=failure) as call:
                result = runner.execute(root, p, "demo", 1, repair=True)
            self.assertEqual(call.call_count, 1)
            self.assertEqual(result["merge_status"], "blocked")

    def test_secret_masking(self):
        self.assertNotIn("my-real-secret", runner.sanitize("EXPERIMENT_LLM_API_KEY=my-real-secret"))
        self.assertEqual(runner.categorize("GHSA-XXXX blocked"), "security_audit")

    def test_manifest_mismatch_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for p in deps.PACKAGES:
                (root / p).mkdir()
                (root / p / "package.json").write_text(json.dumps({
                    "name": p, "version": "1", "engines": {"node": ">=22"},
                    "dependencies": {"a": "^1"}}))
                (root / p / "package-lock.json").write_text(json.dumps({
                    "name": p, "lockfileVersion": 3,
                    "packages": {"": {"name": p, "version": "1", "dependencies": {"a": "^2"}}}}))
            self.assertTrue(any("differs" in e for e in deps.validate(root)))


if __name__ == "__main__":
    unittest.main()
