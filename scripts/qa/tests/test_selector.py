"""Dependency graph, policy boundary, diff parsing and fail-closed tests."""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("selector", Path(__file__).resolve().parents[1] / "selector.py")
selector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(selector)


class SelectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "homeschool-api/services").mkdir(parents=True)
        (self.root / "homeschool-api/tests").mkdir(parents=True)
        (self.root / "homeschool-api/services/example.py").write_text("def value(): return 1\n")
        (self.root / "homeschool-api/tests/test_example.py").write_text(
            "from services.example import value\n"
            "def test_value(): assert value() == 1\n")
        (self.root / "homeschool-tutor/src").mkdir(parents=True)
        (self.root / "homeschool-tutor/src/Widget.tsx").write_text(
            "export const Widget = () => null;\n")
        (self.root / "homeschool-tutor/src/Widget.test.tsx").write_text(
            "import { Widget } from './Widget'\n")
        # All three workspace roots exist in the real monorepo. A missing
        # workspace correctly fails closed, so the synthetic fixture must
        # model the unaffected license-server root as present.
        (self.root / "license-server").mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "ci@example.invalid"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "CI"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.root, check=True)
        self.base = selector.git(self.root, "rev-parse", "HEAD")

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, name: str, body: str):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "change"], cwd=self.root, check=True)

    def test_unchanged_importers_discover_changed_python_unit(self):
        plan = selector.select(self.root, ["homeschool-api/services/example.py"])
        self.assertFalse(plan["scopes"]["backend"]["full"])
        self.assertEqual(plan["scopes"]["backend"]["tests"], ["tests/test_example.py"])
        self.assertEqual(plan["commands"][0]["argv"][-2:], ["tests/test_example.py", "-q"])

    def test_ts_importers_discover_affected_component_tests(self):
        plan = selector.select(self.root, ["homeschool-tutor/src/Widget.tsx"])
        self.assertEqual(plan["scopes"]["homeschool-tutor"]["tests"], ["src/Widget.test.tsx"])
        self.assertFalse(plan["scopes"]["homeschool-tutor"]["full"])

    def test_unmapped_source_fails_closed(self):
        plan = selector.select(self.root, ["unknown-engine/x.go"])
        self.assertTrue(all(x["full"] for x in plan["scopes"].values()))
        self.assertTrue(plan["critical"])

    def test_auth_boundary_always_expands(self):
        plan = selector.select(self.root, ["homeschool-api/core/campus_policy.py"])
        self.assertTrue(plan["scopes"]["backend"]["full"])
        self.assertTrue(plan["critical"])

    def test_backend_voice_contract_runs_both_consuming_clients(self):
        plan = selector.select(self.root, [
            "homeschool-api/services/streaming_transcription.py"
        ])
        self.assertTrue(plan["critical"])
        self.assertTrue(plan["scopes"]["homeschool-tutor"]["full"])
        self.assertTrue(plan["scopes"]["demo"]["full"])
        self.assertFalse(plan["scopes"]["license-server"]["full"])
        self.assertIn(
            ["npm", "test"],
            [c["argv"] for c in plan["commands"] if c["scope"] == "demo"],
        )

    def test_shared_api_contract_broadens_frontend_and_backend(self):
        plan = selector.select(self.root, ["demo/src/api.ts"])
        self.assertTrue(all(x["full"] for x in plan["scopes"].values()))

    def test_missing_import_mapping_fails_closed(self):
        plan = selector.select(self.root, ["homeschool-api/services/unmapped.py"])
        self.assertTrue(plan["scopes"]["backend"]["full"])

    def test_docs_contract_maps_to_specific_test(self):
        plan = selector.select(self.root, ["docs/DECISIONS.md"])
        self.assertIn("tests/test_decision_register.py", plan["scopes"]["backend"]["tests"])

    def test_site_aeo_contracts_run_targeted_backend_guard(self):
        # The legacy workflow treats these as backend-relevant; the
        # selector must map them to the actual AEO assertions, not skip.
        for path in ("site/sitemap.xml", "site/robots.txt", "site/llms.txt",
                     "site/schools/index.html", "site/schools/assets.css"):
            with self.subTest(path=path):
                plan = selector.select(self.root, [path])
                backend = plan["scopes"]["backend"]
                self.assertEqual(backend["tests"], ["tests/test_site_aeo.py"])
                self.assertFalse(backend["full"])
                self.assertFalse(plan["critical"])

    def test_rename_includes_old_and_new_paths(self):
        old = self.root / "homeschool-api/services/example.py"
        new = self.root / "homeschool-api/services/renamed.py"
        old.rename(new)
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "rename"], cwd=self.root, check=True)
        fork, names = selector.changed_files(self.root, self.base, "HEAD")
        self.assertEqual(fork, self.base)
        self.assertIn("homeschool-api/services/example.py", names)
        self.assertIn("homeschool-api/services/renamed.py", names)

    def test_branch_diffs_use_merge_base(self):
        self.commit("homeschool-api/services/example.py", "def value(): return 2\n")
        _, names = selector.changed_files(self.root, self.base, "HEAD")
        self.assertEqual(names, ["homeschool-api/services/example.py"])

    def test_dynamic_import_broadens_scope(self):
        (self.root / "homeschool-tutor/src/Widget.tsx").write_text("import('./other')\n")
        plan = selector.select(self.root, ["homeschool-tutor/src/Widget.tsx"])
        self.assertTrue(plan["scopes"]["homeschool-tutor"]["full"])

    def test_empty_diff_does_not_create_vacuous_pass(self):
        plan = selector.select(self.root, [])
        self.assertTrue(all(x["full"] for x in plan["scopes"].values()))


if __name__ == "__main__":
    unittest.main()
