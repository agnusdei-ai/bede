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
        for field in ("provider", "local_base_url", "local_model", "db_choice", "parent_password", "child_pin",
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


# RFC 8032 section 7.1, TEST 1 (empty message): checks the collector's own
# standard-library Ed25519 verifier against the published vector.
RFC8032_PUB = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
RFC8032_SIG = ("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555"
               "fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")


def pem_source(pub_hex: str) -> str:
    der = bytes.fromhex("302a300506032b6570032100" + pub_hex)
    return ('PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----\n'
            + base64.b64encode(der).decode() + '\n-----END PUBLIC KEY-----"""\n')


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class SessionLicenceCheck(unittest.TestCase):
    """The licence is checked on the Mac against the candidate's own key,
    with nothing but the standard library, and the key is never printed."""

    def run_check(self, key: str, pub_hex: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "licensing.py"
            src.write_text(pem_source(pub_hex))
            # The script runs under set -e, so the status is read without letting a
            # non-zero return end the shell first.
            return lib(f'rc=0; sess_license_check "{key}" "{src}" || rc=$?; echo "rc=$rc"')

    def test_accepts_the_rfc_8032_vector_and_rejects_a_changed_one(self):
        good = "." + b64u(bytes.fromhex(RFC8032_SIG))
        out = self.run_check(good, RFC8032_PUB)
        self.assertIn("verified=yes", out.stdout, out.stderr)
        self.assertIn("rc=0", out.stdout)
        flipped = bytearray(bytes.fromhex(RFC8032_SIG)); flipped[0] ^= 1
        out = self.run_check("." + b64u(bytes(flipped)), RFC8032_PUB)
        self.assertIn("verified=no", out.stdout)
        self.assertIn("rc=1", out.stdout)

    def test_a_real_signed_licence_verifies_only_against_its_own_key(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        except ImportError:
            self.skipTest("cryptography not installed")
        signer, other = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
        payload = json.dumps({"tier": "core", "issued": "2026-11-01", "expires": "2027-11-01",
                              "seats": 6, "licensee": "Sample family"}).encode()
        key = b64u(payload) + "." + b64u(signer.sign(payload))
        pub = lambda k: k.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        out = self.run_check(key, pub(signer))
        self.assertIn("verified=yes", out.stdout, out.stderr)
        self.assertIn("tier=core", out.stdout)
        self.assertIn("expires=2027-11-01", out.stdout)
        self.assertNotIn(key, out.stdout)  # the key itself is never echoed
        self.assertNotIn("Sample family", out.stdout)  # nor the licensee
        self.assertIn("verified=no", self.run_check(key, pub(other)).stdout)


class SessionRecord(unittest.TestCase):
    """results.tsv is append-only: a retest adds an attempt, never erases one."""

    def rec(self, tmp: str, body: str) -> subprocess.CompletedProcess:
        return lib(f'SESSION_RESULTS="{tmp}/r.tsv"; touch "$SESSION_RESULTS"; {body}')

    def test_a_retest_keeps_the_failed_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.rec(tmp, 'SESS_CANDIDATE=aaa; SESS_DMG_SHA=d1; '
                           'sess_rec lesson OWNER FAIL "first try" >/dev/null; '
                           'sess_rec lesson OWNER PASS "after the fix" >/dev/null; sess_last lesson OWNER')
            self.assertEqual(out.stdout.strip(), "PASS", out.stderr)
            rows = [r.split("\t") for r in Path(tmp, "r.tsv").read_text().splitlines()]
            self.assertEqual([(r[1], r[6]) for r in rows], [("1", "FAIL"), ("2", "PASS")])

    def test_an_owner_answer_is_never_an_automated_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.rec(tmp, 'SESS_CANDIDATE=aaa; SESS_DMG_SHA=d1; '
                           'sess_rec voice OWNER PASS heard >/dev/null; echo "[$(sess_last voice AUTOMATED)]"')
            self.assertEqual(out.stdout.strip(), "[]")

    def test_a_new_candidate_keeps_host_facts_and_reruns_everything_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.rec(tmp, 'SESS_CANDIDATE=old; SESS_DMG_SHA=d1; '
                           'sess_rec host AUTOMATED PASS facts >/dev/null; sess_rec install OWNER PASS ok >/dev/null; '
                           'SESS_CANDIDATE=new; SESS_DMG_SHA=d2; echo "last=[$(sess_last install OWNER)]"; sess_stale_report')
            self.assertIn("last=[]", out.stdout)
            self.assertIn("install", out.stdout)
            self.assertNotIn("host", out.stdout.replace("last=[]", ""))


class SessionPreflightIsReadOnly(unittest.TestCase):
    """Nothing in the session installs, pulls or starts anything; the owner
    does each physical step and approves each download and paid call."""

    def section(self) -> str:
        text = SCRIPT.read_text()
        start = text.index("# ── Guided Mac acceptance session")
        return text[start:text.index("# Stop here when sourced for tests.")]

    def test_no_install_download_or_service_command(self):
        code = "\n".join(l for l in self.section().splitlines() if not l.lstrip().startswith("#"))
        for forbidden in ("docker pull", "docker compose up", "docker compose down", "docker run",
                          "ollama pull", "ollama run", "brew install", "installer -pkg",
                          "launchctl", "/tutor/speak", "/tutor/chat"):
            self.assertNotIn(forbidden, code, forbidden)
        self.assertIsNone(re.search(r"\|\s*(sudo\s+)?(ba)?sh\b", code), "piping into a shell")

    def test_each_approval_is_a_flag_not_a_keypress(self):
        code = self.section()
        for flag in ("--approve-downloads", "--approve-voice", "--voice-max-usd", "--openai-project", "--go"):
            self.assertIn(flag, code)
        self.assertIn('[ "$APPROVE_DL" != 1 ]', code)
        self.assertIn('[ "$APPROVE_VOICE" != 1 ]', code)

    def test_never_reads_an_env_file_or_keeps_the_licence(self):
        code = self.section()
        self.assertNotIn("/.env", code)
        self.assertNotIn("env_value", code)
        self.assertIn("LICENSE_KEY_IN=", code)  # passed to the checker's environment only

    def test_image_references_keep_registry_ports(self):
        out = lib('sess_image_ref "ghcr.io/a/bede-api:1.2 sha256:abc"; echo; '
                  'sess_image_ref "localhost:5000/x sha256:def"')
        self.assertEqual(out.stdout.split(), ["ghcr.io/a/bede-api@sha256:abc", "localhost:5000/x@sha256:def"])

    def test_refuses_to_run_anywhere_but_a_mac(self):
        if subprocess.run(["uname", "-s"], capture_output=True, text=True).stdout.strip() == "Darwin":
            self.skipTest("on a Mac")
        out = subprocess.run([BASH, str(SCRIPT), "--session", "--candidate", "a" * 40],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 2)
        self.assertIn("run this on the Mac", out.stderr)


class SessionPreflightRuns(unittest.TestCase):
    """The preflight end to end, with stand-ins for macOS's tools and every
    network call refused: it must stop before changing anything, exit 2,
    and leave a private summary that holds no licence key. This is the
    invocation half: set -e turns a failed lookup inside an assignment into
    a silent exit, which a syntax check cannot see (it shipped once)."""

    def test_stops_cleanly_and_privately_on_unresolved_prerequisites(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp); bin_ = t / "bin"; bin_.mkdir(); home = t / "home"; home.mkdir()
            stubs = {
                "uname": 'if [ "$1" = -s ]; then echo Darwin; else /usr/bin/uname "$@"; fi',
                "sw_vers": "echo 15.1", "sysctl": "echo 25769803776",
                "defaults": "exit 1", "docker": "exit 1", "hdiutil": "exit 1", "curl": "exit 7",
            }
            for name, body in stubs.items():
                (bin_ / name).write_text("#!/bin/sh\n" + body + "\n"); (bin_ / name).chmod(0o755)
            dmg = t / "Bede.dmg"; dmg.write_text("not a real image")
            (t / "Bede.dmg.sha256").write_text("0" * 64 + "  Bede.dmg\n")
            key = license_key({"tier": "core", "issued": "2026-11-01", "expires": "2027-11-01", "seats": 6})
            lic = t / "lic.txt"; lic.write_text("LICENSE_KEY=" + key + "\n")
            out = subprocess.run(
                [BASH, str(SCRIPT), "--session", "--candidate", "a" * 40, "--dmg", str(dmg),
                 "--license-file", str(lic), "--voice", "none"],
                capture_output=True, text=True, timeout=120,
                env={"HOME": str(home), "PATH": f"{bin_}:/usr/bin:/bin"})
            self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
            self.assertIn("STOPPED before anything changed", out.stdout)
            ev = home / "Bede-Acceptance" / ("a" * 40) / "evidence"
            summary = (ev / "SUMMARY.md").read_text()
            self.assertIn("| artifact | AUTOMATED | FAIL |", summary)
            self.assertIn("| voice | OWNER | NOT RUN |", summary)
            for f in ev.iterdir():
                self.assertEqual(f.stat().st_mode & 0o077, 0, f.name)
                self.assertNotIn(key, f.read_text(errors="replace"), f.name)


if __name__ == "__main__":
    unittest.main()
