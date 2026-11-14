"""Offline sample acceptance tests; no sockets, credentials, or learner data."""
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from boundary import ROOT, Error, contract as c, tools
from fixture import example, write_fixture
from ledger import Ledger
from render import artifacts
from run import binding, collect, execute, verify_outputs
from validation import validate_bundle


class Crash(BaseException):
    pass


class FactoryTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, BEDE_CURRICULUM_FACTORY_ENABLED="1",
                              BEDE_FACTORY_MODE="development")
        self.env.start()
        parent = ROOT / "generated-artifacts/curriculum-factory"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.root = Path(self.temp.name)
        write_fixture(self.root / "inputs")
        self.manifest = self.root / "inputs/bundle.json"
        self.ledger = Ledger(self.root / "store")

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()
        self.env.stop()

    def save(self, bundle):
        self.manifest.write_bytes(c.canonical(bundle))

    def run_job(self, **kwargs):
        return execute(self.ledger, self.manifest, "sample-acceptance", **kwargs)

    def rebind(self, b):
        b["lessons"][0]["source_refs"][0]["source"] = c.ref(b["sources"][0])
        b["units"][0]["lesson_refs"] = [c.ref(l) for l in b["lessons"]]
        b["grade"]["unit_refs"] = [c.ref(u) for u in b["units"]]
        for gate in b["gates"]:
            gate["target"] = c.ref(b["grade"])

    def test_valid_structure_and_existing_skill_service(self):
        b, _ = collect(self.manifest)
        validate_bundle(b, self.manifest.parent)
        result = self.run_job()
        self.assertEqual(result["status"], "succeeded")
        self.assertIn("pending", result["approvals"])
        self.assertIsNone(result["usage"]["tokens"])
        self.assertIsNone(result["usage"]["cost"])
        self.assertFalse(json.loads((self.ledger.root/result["key"]/"build.json").read_bytes())
                         ["human_approval"])

    def test_structure_prerequisites_rights_citations_and_teaching_fail(self):
        cases = (
            ("missing", lambda b: b["lessons"][0].pop("access")),
            ("duplicate", lambda b: b["objectives"].append(deepcopy(b["objectives"][0]))),
            ("cycle", lambda b: b["objectives"][0].update(prerequisites=["coordinate"])),
            ("unknown", lambda b: b["lessons"][0].update(prerequisites=["missing"])),
            ("order", lambda b: b["lessons"][0].update(prerequisites=["coordinate"])),
            ("rights", lambda b: b["sources"][0].update(rights="unverified")),
            ("licensed", lambda b: b["sources"][0].update(rights="licensed")),
            ("verbatim", lambda b: b["lessons"][0]["source_refs"][0].update(verbatim=True)),
            ("permission", lambda b: b["sources"][0]["permissions"]["copy"].update(decision="pending")),
            ("rights evidence", lambda b: b["sources"][0].update(rights_evidence_refs=[])),
            ("training", lambda b: b["sources"][0]["permissions"]["training"].update(decision="allowed")),
            ("citation", lambda b: b["lessons"][0]["source_refs"][0]["source"].update(id="missing")),
            ("assessment", lambda b: b["lessons"][0]["assessments"].pop()),
            ("teaching", lambda b: b["lessons"][0]["steps"].pop()),
            ("unknown skill", lambda b: b["lessons"][0].update(skill_ids=["invented"])),
            ("complete grade", lambda b: b["grade"].update(complete=True)),
            ("student key", lambda b: b["lessons"][0]["outputs"][0].update(sections=["Answer key"])),
        )
        for name, mutate in cases:
            with self.subTest(name=name):
                b = example()
                mutate(b)
                if name != "citation":
                    self.rebind(b)
                with self.assertRaises((Error, ValueError)):
                    validate_bundle(b, self.manifest.parent)

    def test_citation_stale_hash_and_source_hash(self):
        b = example()
        b["sources"][0]["title"] = "Changed title"
        with self.assertRaisesRegex(Error, "stale exact reference"):
            validate_bundle(b, self.manifest.parent)
        self.manifest.parent.joinpath("pairs.txt").write_text("tampered")
        with self.assertRaisesRegex(Error, "artifact (size|hash) mismatch"):
            self.run_job()
        job = json.loads(self.ledger.db.execute("SELECT snapshot FROM jobs").fetchone()[0])
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["failure_cluster"], "validation")

    def test_existing_curation_hazard_and_faith_guards(self):
        for text in ("Use a knife.", "faith_score"):
            b = example()
            b["lessons"][0]["steps"][0]["instruction"] = text
            self.rebind(b)
            with self.subTest(text=text), self.assertRaisesRegex(Error, "content curation"):
                validate_bundle(b, self.manifest.parent)

    def test_string_human_approval_and_self_agent_review_rejected(self):
        b = example()
        b["gates"][0].update(state="externally_recorded", receipt_ref="human:somebody")
        with self.assertRaisesRegex(Error, "trusted workflow"):
            validate_bundle(b, self.manifest.parent)
        b = example()
        b["evidence"] = [dict(
            id="review", target=c.ref(b["lessons"][0]), author_run="same", reviewer_run="same",
            reviewer_identity="sample", reviewer_version="unavailable", role="agent_academic",
            at="2026-11-12T12:00:00Z", scope="Sample only", methods=["fixture"],
            artifacts=[deepcopy(b["sources"][0]["asset"])], findings=[], disagreements=[],
            conditions=[], decision="agent_reviewed", command="fixture", result="sample")]
        with self.assertRaisesRegex(Error, "self review"):
            validate_bundle(b, self.manifest.parent)

    def test_deterministic_exports_archive_and_no_key_leak(self):
        b = example()
        b["lessons"][0]["assessments"][0]["key_rubric"] = "SECRET_TEACHER_SENTINEL"
        b["lessons"][0]["steps"][1]["instruction"] = "WORKED_SOLUTION_SENTINEL"
        first = artifacts(b, "a"*64, {"version": "test"})
        self.assertEqual(first, artifacts(deepcopy(b), "a"*64, {"version": "test"}))
        for sentinel in (b"SECRET_TEACHER_SENTINEL", b"WORKED_SOLUTION_SENTINEL"):
            self.assertNotIn(sentinel, first["student.html"])
            self.assertIn(sentinel, first["teacher.html"])
        archive = zipfile.ZipFile(io.BytesIO(first["review.zip"]))
        self.assertEqual(archive.namelist(), sorted(archive.namelist()))
        self.assertTrue(all(i.date_time == (1980, 1, 1, 0, 0, 0) for i in archive.infolist()))
        build = json.loads(first["build.json"])
        for name, checksum in build["outputs"].items():
            self.assertEqual(hashlib.sha256(first[name]).hexdigest(), checksum)
        self.assertIn(b"Source attribution", first["student.html"])

    def test_escaping_and_content_never_executes(self):
        b = example()
        attack = '<script>alert("XSS")</script><img src=x onerror=alert(1)>{{7*7}} javascript:evil'
        b["lessons"][0]["title"] = attack
        files = artifacts(b, "b"*64)
        class Tags(HTMLParser):
            seen = []
            def handle_starttag(self, tag, attrs):
                self.seen.append(tag)
        for name in ("student.html", "teacher.html"):
            parser = Tags()
            parser.seen = []
            parser.feed(files[name].decode())
            self.assertNotIn("script", parser.seen)
            self.assertNotIn("img", parser.seen)
            self.assertIn(b"&lt;script&gt;", files[name])
            self.assertIn(b"{{7*7}}", files[name])
            self.assertIn(b"default-src", files[name])

    def test_default_off_mode_and_output_isolation(self):
        for changes in (
            {"BEDE_CURRICULUM_FACTORY_ENABLED": ""},
            {"BEDE_FACTORY_MODE": "production"}, {"BEDE_FACTORY_MODE": ""},
        ):
            with self.subTest(changes=changes), patch.dict(os.environ, changes):
                with self.assertRaisesRegex(Error, "disabled"):
                    Ledger(self.root/"must-not-exist")
                self.assertFalse((self.root/"must-not-exist").exists())
        with self.assertRaisesRegex(Error, "isolated workspace"):
            Ledger(ROOT/"site/forbidden-output")
        from services.curriculum.flag import curriculum_engine_enabled
        with patch.dict(os.environ, {"CURRICULUM_ENGINE_ENABLED": ""}):
            self.run_job()
            self.assertFalse(curriculum_engine_enabled())

    def test_json_parsing_duplicate_nonfinite_code_and_bounds(self):
        for index, value in enumerate(('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{{7*7}}',
                                      '__import__("os").system("false")', '{"x":')):
            self.manifest.write_text(value)
            with self.subTest(value=value), self.assertRaises((Error, ValueError)):
                execute(self.ledger, self.manifest, f"independent-json-case-{index}")
        self.manifest.write_bytes(b" "*(1024*1024+1))
        with self.assertRaisesRegex(Error, "1 MiB"):
            execute(self.ledger, self.manifest, "independent-json-size-case")

    def test_path_traversal_symlink_and_missing_inputs(self):
        for name in ("../escape.txt", "/etc/passwd", "missing"):
            b = example()
            b["sources"][0]["asset"]["path"] = name
            self.save(b)
            with self.subTest(name=name), self.assertRaises((Error, OSError)):
                self.run_job()
        link = self.manifest.parent/"link"
        link.symlink_to(self.manifest.parent/"pairs.txt")
        b = example()
        b["sources"][0]["asset"]["path"] = "link"
        self.save(b)
        with self.assertRaisesRegex(Error, "Symlinks"):
            self.run_job()
        with self.assertRaisesRegex(Error, "Symlinks"):
            Ledger(link)

    def test_resume_reuses_no_duplicate_outputs_or_events(self):
        first = self.run_job()
        events = self.ledger.db.execute("SELECT count(*) FROM events").fetchone()[0]
        self.assertEqual(first, self.run_job())
        self.assertEqual(events, self.ledger.db.execute("SELECT count(*) FROM events").fetchone()[0])
        self.assertEqual([first["key"]], [p.name for p in self.ledger.root.iterdir()
                                         if p.is_dir() and not p.name.startswith(".")])
        self.ledger.audit()

    def test_missing_and_tampered_output_blocks_reuse(self):
        for mutate in ("remove", "replace"):
            with self.subTest(mutate=mutate):
                task = f"output-{mutate}"
                job = execute(self.ledger, self.manifest, task)
                path = self.ledger.root/job["key"]/"student.html"
                if mutate == "remove":
                    path.unlink()
                else:
                    path.write_bytes(b"corrupt")
                with self.assertRaises(Error):
                    execute(self.ledger, self.manifest, task)
                self.assertEqual(self.ledger.get(job["key"])["status"], "blocked")

    def test_source_support_rubric_and_tool_changes_invalidate(self):
        for change in ("source", "support", "rubric", "tool"):
            with self.subTest(change=change):
                write_fixture(self.manifest.parent)
                first = execute(self.ledger, self.manifest, "change-"+change)
                if change == "source":
                    self.manifest.parent.joinpath("pairs.txt").write_bytes(b"bad")
                    with self.assertRaises(Error):
                        execute(self.ledger, self.manifest, "change-"+change)
                elif change == "tool":
                    with patch("run.tools", return_value={**tools(), "version": "changed"}):
                        second = execute(self.ledger, self.manifest, "change-"+change)
                    self.assertNotEqual(first["key"], second["key"])
                else:
                    b = example()
                    if change == "support":
                        b["lessons"][0]["access"]["supports"].append("Alternative drawing")
                    else:
                        b["lessons"][0]["assessments"][0]["key_rubric"] += " Revised."
                    self.rebind(b)
                    self.save(b)
                    second = execute(self.ledger, self.manifest, "change-"+change)
                    self.assertNotEqual(first["key"], second["key"])
                self.assertEqual(self.ledger.get(first["key"])["status"], "stale")

    def test_change_during_build_fails_before_commit(self):
        def change(phase, _):
            if phase == "after_rename":
                self.manifest.parent.joinpath("pairs.txt").write_bytes(b"changed")
        with self.assertRaisesRegex(Error, "changed during build"):
            self.run_job(hook=change)

    def test_crash_before_after_rename_and_after_commit(self):
        for crash_phase in ("write", "before_rename", "after_rename", "before_commit", "after_commit"):
            with self.subTest(phase=crash_phase):
                def crash(phase, _):
                    if phase == crash_phase:
                        raise Crash()
                task = "crash-"+crash_phase
                with self.assertRaises(Crash):
                    execute(self.ledger, self.manifest, task, hook=crash)
                result = execute(self.ledger, self.manifest, task)
                self.assertEqual(result["status"], "succeeded")
                verify_outputs(self.ledger, result)
                self.ledger.audit()
                self.assertEqual(result, execute(self.ledger, self.manifest, task))

    def test_cancellation_at_each_phase_is_terminal_and_preserved(self):
        for cancel_phase in ("validation", "render", "write", "before_rename",
                             "after_rename", "before_commit"):
            with self.subTest(phase=cancel_phase):
                key = None
                def cancel(phase, job):
                    nonlocal key
                    key = job["key"]
                    if phase == cancel_phase:
                        other = Ledger(self.ledger.root)
                        try:
                            other.cancel(key, "Sample cancellation test")
                        finally:
                            other.close()
                with self.assertRaisesRegex(Error, "Canceled"):
                    execute(self.ledger, self.manifest, "cancel-"+cancel_phase, hook=cancel)
                job = self.ledger.get(key)
                self.assertEqual(job["status"], "canceled")
                self.assertEqual(job["outputs"], {})
                with self.assertRaisesRegex(Error, "canceled"):
                    execute(self.ledger, self.manifest, "cancel-"+cancel_phase)

    def test_initial_failure_plus_three_repairs_then_exhaustion(self):
        def fail(phase, _):
            if phase == "render":
                raise Error("Fixed failure family")
        for attempt in range(4):
            with self.assertRaisesRegex(Error, "Fixed failure family"):
                self.run_job(hook=fail)
        with self.assertRaisesRegex(Error, "three repairs"):
            self.run_job(hook=fail)
        job = json.loads(self.ledger.db.execute("SELECT snapshot FROM jobs").fetchone()[0])
        self.assertEqual(job["repairs"]["render"], 3)
        self.assertEqual(job["status"], "blocked")
        failed_events = self.ledger.db.execute(
            "SELECT payload FROM events WHERE json_extract(payload,'$.action')='failure'").fetchall()
        self.assertEqual(len(failed_events), 4)

    def test_repair_budget_cannot_reset_by_changing_manifest_bytes(self):
        def fail(phase, _):
            if phase == "render":
                raise Error("Same failure family")
        for attempt in range(4):
            b = example()
            b["lessons"][0]["title"] += f" revision {attempt}"
            self.rebind(b)
            self.save(b)
            with self.assertRaisesRegex(Error, "Same failure family"):
                self.run_job(hook=fail)
        b["lessons"][0]["title"] += " another revision"
        self.rebind(b)
        self.save(b)
        with self.assertRaisesRegex(Error, "three repairs"):
            self.run_job(hook=fail)

    def test_os_worker_lock_and_epoch_fencing(self):
        other = Ledger(self.ledger.root)
        try:
            with self.ledger.worker(), self.assertRaisesRegex(Error, "worker"):
                with other.worker():
                    self.fail("Second worker entered")
            code = (
                "import sys; from ledger import Ledger; from boundary import Error; "
                "l=Ledger(sys.argv[1]); "
                "\ntry:\n with l.worker(): sys.exit(9)\nexcept Error: sys.exit(0)"
            )
            with self.ledger.worker():
                child = subprocess.run([sys.executable, "-c", code, str(self.ledger.root)],
                                       cwd=Path(__file__).parent, capture_output=True, timeout=10)
                self.assertEqual(child.returncode, 0, child.stderr.decode())
            def stale(phase, job):
                if phase == "render":
                    with self.assertRaisesRegex(Error, "fenced"):
                        other.mutate(job["key"], job["epoch"]-1, "bad", status="succeeded")
            self.run_job(hook=stale)
        finally:
            other.close()

    def test_real_process_exit_before_after_rename_and_commit(self):
        code = (
            "import os,sys; from pathlib import Path; from ledger import Ledger; "
            "from run import execute; l=Ledger(sys.argv[1]); "
            "execute(l,Path(sys.argv[2]),sys.argv[3],"
            "hook=lambda phase,job: os._exit(77) if phase==sys.argv[4] else None)"
        )
        for phase in ("before_rename", "after_rename", "after_commit"):
            with self.subTest(phase=phase):
                task = "real-crash-"+phase
                child = subprocess.run(
                    [sys.executable, "-c", code, str(self.ledger.root),
                     str(self.manifest), task, phase],
                    cwd=Path(__file__).parent, capture_output=True, timeout=10)
                self.assertEqual(child.returncode, 77, child.stderr.decode())
                result = execute(self.ledger, self.manifest, task)
                self.assertEqual(result["status"], "succeeded")
                verify_outputs(self.ledger, result)
                self.ledger.audit()

    def test_ledger_append_only_chain_and_checkpoint_tampering(self):
        job = self.run_job()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            self.ledger.db.execute("DELETE FROM events")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
            self.ledger.db.execute("UPDATE events SET hash='bad'")
        self.ledger.db.execute("UPDATE jobs SET snapshot='{}' WHERE key=?", (job["key"],))
        with self.assertRaisesRegex(Error, "checkpoint"):
            self.ledger.audit()

    def test_binding_checks_current_content_and_current_output(self):
        job = self.run_job()
        target, _, _ = binding(self.ledger, job, "pairs")
        self.assertEqual(target["factory_key"], job["key"])
        b = example()
        b["lessons"][0]["assessments"][0]["key_rubric"] += " Changed."
        self.rebind(b)
        self.save(b)
        with self.assertRaisesRegex(Error, "stale"):
            binding(self.ledger, job, "pairs")


if __name__ == "__main__":
    unittest.main()
