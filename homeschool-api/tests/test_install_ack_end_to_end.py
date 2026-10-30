"""The installer and the API agree on the install-time acknowledgement.

The installer tests prove setup.sh writes sha256(notice bytes); the API tests
prove core/consent.py accepts a hash equal to notice_hash(). Neither proves the
two are the SAME value, which is the only thing that matters to a family: if
they drift, every fresh install silently gets no consent and tutoring is
refused. This runs the REAL setup.sh, reads the .env it produced, and hands
exactly those values to the API's validator.
"""
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
NOTICE = ROOT / "homeschool-api" / "data" / "consent_notice.txt"

# provider 1, api key, local db (default), parent password, child pin, licence
ANSWERS = "1\nsk-ant-test\n\nparentpass123\n805274199\nlicense-value\n"


def _install(tmp_path: Path) -> dict:
    shutil.copy(ROOT / "setup.sh", tmp_path / "setup.sh")
    (tmp_path / "homeschool-api" / "data").mkdir(parents=True)
    shutil.copy(NOTICE, tmp_path / "homeschool-api" / "data" / "consent_notice.txt")
    (tmp_path / "scripts" / "setup_wizard").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "setup_wizard" / "install_receipt.py",
                tmp_path / "scripts" / "setup_wizard" / "install_receipt.py")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name in ("docker", "curl"):
        (stubs / name).write_text("#!/bin/sh\nexit 0\n")
        (stubs / name).chmod(0o755)
    env = {**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}"}
    result = subprocess.run(
        ["bash", "setup.sh", "--accept-consent-notice", "--mode", "family",
         "--authorizer-name", "Pat Parent", "--attest-parent-guardian"],
        cwd=tmp_path, input=ANSWERS, text=True, capture_output=True, env=env, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    values = {"_receipt": (tmp_path / "install" / "installation_receipt.json").read_text()}
    for line in (tmp_path / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def test_the_installers_acknowledgement_is_valid_to_the_api(tmp_path):
    from core import consent
    from core.config import settings

    env = _install(tmp_path)
    assert env["CONSENT_INSTALL_ACK_HASH"] == consent.notice_hash()

    with patch.object(settings, "consent_install_ack_hash", env["CONSENT_INSTALL_ACK_HASH"]), \
         patch.object(settings, "consent_install_ack_at", env["CONSENT_INSTALL_ACK_AT"]):
        assert consent.install_ack_time() is not None


def test_an_edited_notice_invalidates_the_installers_acknowledgement(tmp_path):
    """A notice changed after install is a new notice: the old ack must not count."""
    from core import consent
    from core.config import settings

    env = _install(tmp_path)
    with patch.object(settings, "consent_install_ack_hash", env["CONSENT_INSTALL_ACK_HASH"]), \
         patch.object(settings, "consent_install_ack_at", env["CONSENT_INSTALL_ACK_AT"]), \
         patch.object(consent, "notice_hash", return_value="0" * 64):
        assert consent.install_ack_time() is None


def test_the_installer_receipt_records_the_same_notice_hash_as_the_ack(tmp_path):
    """The .env acknowledgement and the receipt are two records of one
    acceptance: they must name the same notice bytes, and the API's own
    notice_hash() must agree with both."""
    import json
    from core import consent

    env = _install(tmp_path)
    record = json.loads(env["_receipt"])
    assert record["notice"]["sha256"] == env["CONSENT_INSTALL_ACK_HASH"] == consent.notice_hash()
    assert record["notice"]["version"] == consent.NOTICE_VERSION
    assert record["state"] == "pending_verification"
