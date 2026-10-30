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


def test_the_installers_hash_equals_the_apis_notice_hash(tmp_path):
    """The legacy acknowledgement the installer writes still carries the SAME
    hash the API computes, so a receipt built from it agrees with the API."""
    from core import consent

    env = _install(tmp_path)
    assert env["CONSENT_INSTALL_ACK_HASH"] == consent.notice_hash()


def test_the_installers_env_acknowledgement_alone_no_longer_unlocks(tmp_path):
    """Attestation is not verification: without a verified installation
    receipt (docs/INSTALLATION_AUTHORIZATION_FLOW.md) the env values cover nothing."""
    from core import consent
    from core.config import settings
    from tests import installation_helpers as h

    env = _install(tmp_path)
    import pytest as _p
    mp = _p.MonkeyPatch()
    try:
        h.no_receipt(mp)
        mp.setattr(settings, "consent_install_ack_hash", env["CONSENT_INSTALL_ACK_HASH"])
        mp.setattr(settings, "consent_install_ack_at", env["CONSENT_INSTALL_ACK_AT"])
        assert consent.install_ack_time() is None
    finally:
        mp.undo()


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


def test_the_apis_validator_reads_the_installers_real_receipt(tmp_path, monkeypatch):
    """Cross-lane: the file setup.sh actually wrote must load as a valid
    pending family receipt in core.installation_receipt, never `invalid`, and
    must not unlock processing."""
    from core import installation_receipt as ir
    from core.config import settings

    _install(tmp_path)
    receipt = tmp_path / "install" / "installation_receipt.json"
    monkeypatch.setattr(settings, "installation_receipt_path", str(receipt))
    monkeypatch.setattr(settings, "installation_receipt_append_path", str(tmp_path / "append.jsonl"))
    ir.invalidate()
    state = ir.current()
    assert state.state == "pending_verification", state
    assert state.chain_valid
    assert not state.processing_enabled
    ir.invalidate()
