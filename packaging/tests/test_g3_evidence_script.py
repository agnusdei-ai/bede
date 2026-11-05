"""The Mac G3 evidence collector (scripts/mac/collect-g3-evidence.sh).

The collector only ever runs on the owner's Mac, so these tests run its pieces
on a macOS runner (macos-installer-ui.yml), where /bin/bash is 3.2 and sed,
grep and base64 are the BSD ones: exactly what the owner's Mac has. They also
run on Linux.

They check the parts that can be checked without Docker or a Touch ID tap:
the secret scan that guards the evidence pack, the license reading that
supplies the campus ID, the lockfile filter that makes the Touch ID check
installable on a Mac, and that every fact the script relies on in another
file (the wizard's form fields, the bundle's name, Verify-Bede's PASS line)
is still true there. That last group exists because the script copies those
facts by value, and a rename in the wizard would otherwise break the owner's
run with nothing failing in CI.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "mac" / "collect-g3-evidence.sh"
BASH = shutil.which("bash") or "/bin/bash"


def lib(snippet: str, **env: str) -> subprocess.CompletedProcess:
    """Run a snippet with the script's functions loaded and nothing executed."""
    return subprocess.run(
        [BASH, "-c", f'G3_LIB_ONLY=1; source "{SCRIPT}"; {snippet}'],
        capture_output=True, text=True, env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", **env},
    )


def license_key(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    body = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return body + ".c2lnbmF0dXJl"


class ScriptShape(unittest.TestCase):
    def test_parses(self):
        self.assertEqual(subprocess.run([BASH, "-n", str(SCRIPT)]).returncode, 0)

    def test_uses_nothing_newer_than_macos_bash_3_2(self):
        # Comments are dropped first: the header names these constructs in
        # order to rule them out, and a scan of it would fail on the rule.
        source = "\n".join(line for line in SCRIPT.read_text().splitlines()
                           if not line.lstrip().startswith("#"))
        for pattern in (r"declare -A", r"\bmapfile\b", r"\breadarray\b", r"\$\{[a-zA-Z_]+,,\}",
                        r"\$\{[a-zA-Z_]+\^\^\}", r"\bcoproc\b", r"\|&"):
            self.assertIsNone(re.search(pattern, source), pattern)

    def test_never_records_identifying_host_details(self):
        source = SCRIPT.read_text()
        for call in ("IOPlatformSerialNumber", "system_profiler", "scutil", "whoami", "hostname", "ioreg"):
            self.assertNotIn(call, source)

    def test_help_and_missing_arguments_are_safe(self):
        self.assertEqual(subprocess.run([BASH, str(SCRIPT), "--help"], capture_output=True).returncode, 0)
        blocked = subprocess.run([BASH, str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("--license-file is required", blocked.stderr)


class LicenseReading(unittest.TestCase):
    def test_reads_the_campus_and_tier_from_an_unpadded_base64url_key(self):
        for location in ("site-2026-01", "campus_a"):  # lengths that need 1 and 2 padding characters
            key = license_key({"expires": "2027-01-01", "licensee": "School Location 01",
                               "location_id": location, "tier": "campus_location"})
            got = lib(f'license_field "{key}" location_id; echo; license_field "{key}" tier')
            self.assertEqual(got.stdout.split(), [location, "campus_location"], got.stderr)

    def test_reads_the_key_from_issue_license_output_or_a_bare_key_file(self):
        key = license_key({"location_id": "site-2026-01", "tier": "campus_location"})
        with tempfile.TemporaryDirectory() as tmp:
            full = Path(tmp) / "full.txt"
            full.write_text("Licensee:  G3 test campus\nTier:      campus_location\n"
                            "Location:  site-2026-01\n\nLICENSE_KEY=" + key + "\n")
            bare = Path(tmp) / "bare.txt"
            bare.write_text(key + "\n")
            for f in (full, bare):
                self.assertEqual(lib(f'read_license_key "{f}"').stdout, key)

    def test_issue_license_still_prints_the_key_on_a_license_key_line(self):
        issue = (ROOT / "homeschool-api" / "scripts" / "issue_license.py").read_text()
        self.assertIn('print("LICENSE_KEY=" + license_str)', issue)

    def test_a_malformed_key_reads_as_empty_rather_than_failing(self):
        got = lib('license_field "not-a-key" location_id')
        self.assertEqual(got.stdout.strip(), "")


class SecretScan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "host.txt").write_text("captured 2026-11-05 size 4182736 bytes\n")

    def scan(self, values: str) -> int:
        return lib(f'secret_scan "$VALUES" "{self.dir}"', VALUES=values).returncode

    def test_clean_evidence_passes(self):
        self.assertEqual(self.scan("g3-0123456789abcdef0123456789abcdef\n418273"), 0)

    def test_a_planted_password_fails(self):
        (self.dir / "verify.txt").write_text("admin g3-0123456789abcdef0123456789abcdef\n")
        self.assertNotEqual(self.scan("g3-0123456789abcdef0123456789abcdef"), 0)

    def test_a_planted_pin_fails_as_a_whole_word(self):
        (self.dir / "note.txt").write_text("pin 418273 used\n")
        self.assertNotEqual(self.scan("418273"), 0)

    def test_pin_digits_inside_a_larger_number_do_not_count(self):
        (self.dir / "sizes.txt").write_text("4182736\n")
        self.assertEqual(self.scan("418273"), 0)

    def test_a_private_key_block_fails_even_when_not_listed(self):
        (self.dir / "ca.txt").write_text("-----BEGIN EC PRIVATE KEY-----\nabc\n")
        self.assertNotEqual(self.scan(""), 0)


class MacLockfile(unittest.TestCase):
    def test_drops_only_the_linux_gpu_packages_and_keeps_hashes(self):
        lock = ROOT / "homeschool-api" / "requirements-dev.lock.txt"
        got = lib(f'mac_lock "{lock}"')
        self.assertEqual(got.returncode, 0, got.stderr)
        kept = [line.split("==")[0] for line in got.stdout.splitlines() if re.match(r"[A-Za-z0-9]", line)]
        original = [line.split("==")[0] for line in lock.read_text().splitlines() if re.match(r"[A-Za-z0-9]", line)]
        dropped = set(original) - set(kept)
        self.assertTrue(dropped, "nothing was dropped")
        self.assertTrue(all(re.match(r"(nvidia-|cuda-|triton)", name) for name in dropped), dropped)
        self.assertEqual([n for n in kept if re.match(r"(nvidia-|cuda-|triton)", n)], [],
                         "a Linux-only GPU package would make the Mac install fail")
        self.assertIn("torch", kept)
        self.assertIn("pypdfium2", kept)
        self.assertGreater(got.stdout.count("--hash=sha256:"), 100)


class FactsTheScriptCopies(unittest.TestCase):
    """Each fact here is written in the script by value and owned by another file."""

    def setUp(self):
        self.script = SCRIPT.read_text()

    def test_wizard_form_fields_still_exist(self):
        wizard = (ROOT / "scripts" / "setup_wizard" / "wizard.py").read_text()
        for field in ("provider", "local_base_url", "db_choice", "parent_password", "child_pin",
                      "license_key", "location_id"):
            self.assertIn(f"{field}=", self.script)
            self.assertIn(f'"{field}"', wizard)
        self.assertIn('"local": "local_base_url"', wizard)
        self.assertIn('name="child_pin" value="{SUGGESTED_CHILD_PIN}"', wizard)
        self.assertIn('"/consent"', wizard)
        self.assertIn("agree=yes", self.script)

    def test_the_offline_bundle_artifact_name_matches_the_workflow(self):
        workflow = (ROOT / ".github" / "workflows" / "build-bede-operator.yml").read_text()
        self.assertIn('ARTIFACT_PREFIX="bede-offline-linux"', self.script)
        self.assertIn("name: bede-offline-linux-${{ matrix.arch }}-", workflow)
        self.assertIn("bede-operator-${SOURCE_SHA}-${{ matrix.arch }}.tar.gz.sha256", workflow)

    def test_verify_bede_still_prints_the_line_the_script_reads(self):
        verify = (ROOT / "packaging" / "bundle" / "Verify-Bede.command").read_text()
        self.assertIn('echo "PASS: HTTPS health verified against this instance\'s CA"', verify)
        self.assertIn("^PASS: HTTPS health verified", self.script)

    def test_compose_project_naming_matches_the_installer(self):
        start = (ROOT / "packaging" / "bundle" / "start.sh").read_text()
        self.assertIn('COMPOSE_PROJECT_NAME="bede_campus_${BEDE_CAMPUS_ID//-/_}"', start)
        self.assertIn("bede_campus_$(printf '%s' \"$CAMPUS_ID\" | tr '-' '_')", self.script)

    def test_the_touch_id_check_reads_the_output_folder_the_script_sets(self):
        check = (ROOT / "scripts" / "qualification" / "mac_check.py").read_text()
        self.assertIn('os.environ.get("QUAL_OUT_DIR"', check)
        self.assertIn('"QUAL_DB_ADMIN_URL"', check)
        self.assertIn("QUAL_OUT_DIR=", self.script)


if __name__ == "__main__":
    unittest.main()
