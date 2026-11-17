"""QA reporting, deterministic bounded repair and dependency contracts."""
import importlib.util
import json
import subprocess
import tempfile
import time
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

    def test_pytest_failure_is_not_mislabeled_dependency_lock(self):
        log = (
            "FAILED tests/test_contract.py::test_runs - AssertionError:\n"
            "assert 'pytest tests/' in 'lockfile-freshness step output'"
        )
        self.assertEqual(runner.categorize(log), "outdated_test")

    def test_error_excerpts_stay_in_run_evidence(self):
        fake = type("Completed", (), {
            "stdout": "FAILED tests/test_contract.py::test_runs - AssertionError",
            "stderr": "", "returncode": 1,
        })()
        with patch.object(runner.subprocess, "run", return_value=fake):
            result = runner.run_command(["python", "-m", "pytest", "tests/", "-q"], Path("."), 30)
        self.assertIn("FAILED tests/test_contract.py", result["diagnostic_excerpt"])
        self.assertEqual(result["category"], "outdated_test")

    # A timeout is its own outcome (#851: a passing suite was killed at the
    # 900 s limit and reported as "test_flakiness"). These run a real
    # subprocess, so they exercise the same path the CI step takes.
    SLOW = ["python3", "-c", "import sys, time; print('partial-line-before-limit', flush=True); time.sleep(30)"]

    def test_a_timeout_is_reported_as_a_timeout_and_keeps_the_partial_output(self):
        result = runner.run_command(self.SLOW, Path("."), timeout=2)
        self.assertEqual(result["exit_code"], 124)
        self.assertEqual(result["category"], "timeout")
        self.assertIn("partial-line-before-limit", result["diagnostic_excerpt"])
        self.assertIn("stopped at its 2 s limit", result["diagnostic_excerpt"])
        self.assertLess(result["duration_seconds"], 20)

    def test_a_long_command_posts_a_warning_while_it_runs(self):
        import contextlib, io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            runner.run_command(self.SLOW, Path("."), timeout=3, warn_after=1)
        self.assertIn("::warning title=QA runtime::", out.getvalue())
        self.assertIn("has run 1 s of its 3 s limit", out.getvalue())

    def test_a_quick_command_posts_no_warning(self):
        import contextlib, io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = runner.run_command(["python3", "-c", "pass"], Path("."), timeout=30, warn_after=1)
            time.sleep(1.5)  # past the warning point: the timer must have been cancelled
        self.assertEqual(result["exit_code"], 0)
        self.assertNotIn("::warning", out.getvalue())

    def test_main_labels_a_timeout_as_one_and_still_fails(self):
        with tempfile.TemporaryDirectory() as td:
            plan = {"version": 1, "head": "x", "merge_base": "y", "input_sha256": "z",
                    "changed_modules": [], "mandatory_external_gates": [],
                    "scopes": {"backend": {"full": True, "reasons": [], "tests": []}},
                    "commands": [{"scope": "backend", "cwd": ".",
                                  "argv": ["python", "-m", "pytest", "--version"]}]}
            (Path(td) / "plan.json").write_text(json.dumps(plan))
            timeout_result = {"command": plan["commands"][0]["argv"], "cwd": td, "exit_code": 124,
                              "duration_seconds": 2.0, "category": "timeout",
                              "diagnostic_excerpt": "QA timeout: the command was stopped at its 2 s limit"}
            import contextlib, io, sys
            out, err = io.StringIO(), io.StringIO()
            argv = ["runner.py", "--plan", str(Path(td) / "plan.json"), "--scope", "backend",
                    "--repo", td, "--report", str(Path(td) / "r.json"), "--timeout", "2"]
            with patch.object(runner, "run_command", return_value=timeout_result), \
                    patch.object(sys, "argv", argv), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = runner.main()
        self.assertEqual(code, 1)
        self.assertIn("::error title=QA timeout::", out.getvalue())
        self.assertIn("QA FAIL [timeout]", err.getvalue())
        self.assertNotIn("test_flakiness", err.getvalue())

    def test_the_default_warning_is_half_the_limit(self):
        with tempfile.TemporaryDirectory() as td:
            plan = {"version": 1, "scopes": {"backend": {"full": True, "reasons": [], "tests": []}},
                    "commands": [{"scope": "backend", "cwd": ".", "argv": ["python", "-m", "pytest"]}],
                    "changed_modules": [], "mandatory_external_gates": []}
            (Path(td) / "plan.json").write_text(json.dumps(plan))
            import sys
            argv = ["runner.py", "--plan", str(Path(td) / "plan.json"), "--scope", "backend",
                    "--repo", td, "--report", str(Path(td) / "r.json"), "--timeout", "1800"]
            seen = {}
            def fake_execute(root, plan, scope, timeout, repair, warn_after=None, **kw):
                seen["warn_after"] = warn_after
                return {"merge_status": "ready", "results": [], "runner_seconds": 0}
            with patch.object(runner, "execute", side_effect=fake_execute), patch.object(sys, "argv", argv):
                runner.main()
        self.assertEqual(seen["warn_after"], 900)

    def test_secret_masking(self):
        self.assertNotIn("my-real-secret", runner.sanitize("OPENAI_API_KEY=my-real-secret"))
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
