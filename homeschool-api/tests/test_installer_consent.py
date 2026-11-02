"""Install-time parental consent in the terminal installer (setup.sh).

A self-hosting family consents BEFORE anything is collected, written or
started. These tests run the REAL setup.sh in a throwaway directory with
stub `docker`/`curl` so no stack is started, and assert:

* declining exits non-zero and writes no .env;
* an unattended run without --accept-consent-notice stops (never silently
  skips consent);
* accepting (piped "y", or the explicit flag) writes both acknowledgement
  lines, the hash being the SHA-256 of the real notice file's bytes.

The wizard's half is covered in scripts/setup_wizard/test_wizard.py.
"""
import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NOTICE = ROOT / "homeschool-api" / "data" / "consent_notice.txt"

# provider 1, api key, local db (default), parent password, child pin, licence
ANSWERS = "1\nsk-ant-test\n\nparentpass123\n805274199\nlicense-value\n"


@pytest.fixture
def sandbox(tmp_path):
    shutil.copy(ROOT / "setup.sh", tmp_path / "setup.sh")
    (tmp_path / "homeschool-api" / "data").mkdir(parents=True)
    shutil.copy(NOTICE, tmp_path / "homeschool-api" / "data" / "consent_notice.txt")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name in ("docker", "curl"):
        f = stubs / name
        f.write_text("#!/bin/sh\nexit 0\n")
        f.chmod(0o755)
    return tmp_path


def _run(sandbox, stdin, *args):
    env = {**os.environ, "PATH": f"{sandbox / 'stubs'}:{os.environ['PATH']}"}
    return subprocess.run(
        ["bash", "setup.sh", *args],
        cwd=sandbox, input=stdin, text=True, capture_output=True, env=env, timeout=60,
    )


def _expected_hash():
    return hashlib.sha256(NOTICE.read_bytes()).hexdigest()


def test_declining_exits_nonzero_and_writes_no_env(sandbox):
    r = _run(sandbox, "n\n" + ANSWERS)
    assert r.returncode != 0
    assert "Installation not completed" in r.stdout
    assert not (sandbox / ".env").exists()


def test_default_answer_is_no(sandbox):
    r = _run(sandbox, "\n" + ANSWERS)
    assert r.returncode != 0
    assert not (sandbox / ".env").exists()


def test_unattended_without_flag_stops_rather_than_skipping(sandbox):
    r = _run(sandbox, "")
    assert r.returncode != 0
    assert "Installation not completed" in r.stdout
    assert "--accept-consent-notice" in r.stdout
    assert not (sandbox / ".env").exists()


def test_accepting_writes_both_ack_lines_with_the_real_hash(sandbox):
    r = _run(sandbox, "y\n" + ANSWERS)
    assert r.returncode == 0, r.stdout + r.stderr
    env = (sandbox / ".env").read_text()
    assert f"CONSENT_INSTALL_ACK_HASH={_expected_hash()}\n" in env
    assert re.search(r"^CONSENT_INSTALL_ACK_AT=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", env, re.M)


def test_flag_is_explicit_consent_and_still_writes_the_ack(sandbox):
    r = _run(sandbox, ANSWERS, "--accept-consent-notice")
    assert r.returncode == 0, r.stdout + r.stderr
    env = (sandbox / ".env").read_text()
    assert f"CONSENT_INSTALL_ACK_HASH={_expected_hash()}\n" in env
    assert "CONSENT_INSTALL_ACK_AT=" in env


def test_the_notice_is_shown_before_any_prompt(sandbox):
    r = _run(sandbox, "n\n")
    assert "Parental Notice and Consent" in r.stdout
    assert NOTICE.read_text().splitlines()[0] in r.stdout
    assert "AI provider" not in r.stdout


def test_hash_follows_the_file_not_a_constant(sandbox):
    """Editing the notice changes the recorded hash (nothing is hardcoded)."""
    notice = sandbox / "homeschool-api" / "data" / "consent_notice.txt"
    notice.write_bytes(notice.read_bytes() + b"\nExtra line.\n")
    r = _run(sandbox, ANSWERS, "--accept-consent-notice")
    assert r.returncode == 0, r.stdout + r.stderr
    env = (sandbox / ".env").read_text()
    assert f"CONSENT_INSTALL_ACK_HASH={hashlib.sha256(notice.read_bytes()).hexdigest()}\n" in env
    assert _expected_hash() not in env


def test_launchers_stop_on_a_declined_wizard_even_if_an_old_env_exists():
    """A declined notice makes the wizard exit non-zero. The launchers must
    stop on that status itself; checking only for a .env would start Bede on a
    previous configuration after the family declined."""
    common = (ROOT / "scripts" / "setup-gui-common.sh").read_text()
    assert "WIZARD_STATUS=$?" in common
    assert 'if [[ "$WIZARD_STATUS" -ne 0 ]]' in common
    bat = (ROOT / "setup-gui.bat").read_text()
    run = bat.index("docker run --rm -p 127.0.0.1:8765:8765")
    assert bat.index("if errorlevel 1", run) < bat.index("if not exist .env", run)
