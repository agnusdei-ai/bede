"""The installers' receipt (scripts/setup_wizard/install_receipt.py).

docs/INSTALLATION_AUTHORIZATION_FLOW.md: only a receipt in state `verified`
ever enables child-data processing, and an attestation is never labeled
verified consent. These tests pin the installer half of that contract:

* declining creates nothing; a family receipt is always pending_verification;
* a school receipt is verified ONLY when the signed campus key, the documented
  delegation, the authorizer's role and the notice acceptance are all valid,
  and a campus key on its own never yields verified;
* the receipt hash is reproducible from the documented canonicalization (the
  API's validator is written against that rule, so the rule is restated here
  from scratch rather than by calling the module's own helper);
* a tampered notice, a tampered record, or a broken chain is detected;
* the real setup.sh produces the same receipt through the same module.

Ephemeral test-only Ed25519 keys; no real campus, learner or customer data.
"""
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from core import licensing

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "setup_wizard"))
import install_receipt as ir  # noqa: E402

FAMILY_NOTICE = (ROOT / "homeschool-api" / "data" / "consent_notice.txt").read_bytes()
SCHOOL_NOTICE = (ROOT / "homeschool-api" / "data" / "school_data_notice.txt").read_bytes()
LOCATION = "school-campus-001"
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
DELEGATION = {"reference": "Board minute 14", "issued_by": "School board", "dated": YESTERDAY}


@pytest.fixture
def signing_key(monkeypatch):
    private = ECC.generate(curve="Ed25519")
    monkeypatch.setattr(licensing, "PUBLIC_KEY_PEM", private.public_key().export_key(format="PEM"))
    return private


def sign(key, **changes):
    payload = {
        "id": str(uuid.uuid4()),
        "licensee": "Test Site License",
        "tier": "campus_location",
        "location_id": LOCATION,
        "learner_scope": "unlimited_at_location",
        "issued": date.today().isoformat(),
        "expires": (date.today() + timedelta(days=31)).isoformat(),
    }
    payload.update(changes)
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig = eddsa.new(key, "rfc8032").sign(blob)
    b64 = lambda v: base64.urlsafe_b64encode(v).rstrip(b"=").decode("ascii")  # noqa: E731
    return f"{b64(blob)}.{b64(sig)}"


def family(**over):
    args = dict(mode="family", notice_bytes=FAMILY_NOTICE, accepted=True,
                authorizer_name="Pat Parent", attested=True)
    args.update(over)
    return ir.build_receipt(**args)


def school(key, **over):
    args = dict(mode="school", notice_bytes=SCHOOL_NOTICE, accepted=True,
                authorizer_name="Sam Principal", capacity="administrator",
                delegation=dict(DELEGATION), license_key=sign(key), location_id=LOCATION)
    args.update(over)
    return ir.build_receipt(**args)


# ── declining and the family path ────────────────────────────────────────────
def test_declining_creates_no_receipt(tmp_path):
    with pytest.raises(ir.ReceiptError):
        ir.create_and_write(repo_dir=tmp_path, mode="family", notice_bytes=FAMILY_NOTICE,
                            accepted=False, authorizer_name="Pat Parent", attested=True)
    assert not (tmp_path / "install").exists()


def test_a_family_receipt_is_pending_and_records_an_attestation_not_consent():
    record, findings = family()
    assert record["state"] == "pending_verification"
    assert record["verification"] == {"method": None, "completed_at": None}
    assert record["authorizer"]["capacity"] == "parent_guardian"
    assert record["authorizer"]["attestation"] == ir.FAMILY_ATTESTATION
    assert record["delegation"] is None and record["campus"] is None
    assert findings == ["parental_verification_method_unavailable"]
    assert ir.validate_record(record, FAMILY_NOTICE) == []


def test_a_family_can_never_reach_verified_without_a_method():
    """Whatever the installer is given, a family receipt never says verified."""
    record, _ = family(license_key="anything", location_id=LOCATION,
                       delegation=dict(DELEGATION), capacity="administrator")
    assert record["state"] == "pending_verification"


def test_the_attestation_and_a_name_are_never_assumed():
    with pytest.raises(ir.ReceiptError):
        family(attested=False)
    with pytest.raises(ir.ReceiptError):
        family(authorizer_name="   ")


# ── receipt hash is reproducible ─────────────────────────────────────────────
def test_receipt_hash_follows_the_documented_canonicalization():
    record, _ = family(authorizer_name="Zoë Parent")  # non-ASCII on purpose
    body = {k: v for k, v in record.items() if k != "receipt_sha256"}
    expected = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert record["receipt_sha256"] == expected
    # key order and whitespace of the carrier do not matter; only the content
    shuffled = dict(reversed(list(body.items())))
    assert ir.compute_receipt_sha256(shuffled) == expected
    assert "Zoë" in json.dumps(body, ensure_ascii=False)


def test_any_edit_to_a_record_breaks_its_hash():
    record, _ = family()
    forged = json.loads(json.dumps(record))
    forged["state"] = "verified"
    assert "receipt_sha256_mismatch" in ir.validate_record(forged)


# ── notice tampering ─────────────────────────────────────────────────────────
def test_a_tampered_notice_is_detected_against_the_recorded_hash():
    record, _ = family()
    assert record["notice"]["sha256"] == hashlib.sha256(FAMILY_NOTICE).hexdigest()
    assert "notice_sha256_mismatch" in ir.validate_record(record, FAMILY_NOTICE + b"\nEdited.\n")


def test_a_notice_changed_after_it_was_shown_is_refused():
    shown = hashlib.sha256(FAMILY_NOTICE).hexdigest()
    with pytest.raises(ir.ReceiptError, match="changed after it was shown"):
        family(notice_bytes=FAMILY_NOTICE + b"\nEdited.\n", shown_notice_sha256=shown)


# ── school ───────────────────────────────────────────────────────────────────
def test_school_is_verified_only_with_key_delegation_role_and_acceptance(signing_key):
    record, findings = school(signing_key)
    assert findings == []
    assert record["state"] == "verified"
    assert record["verification"]["method"] == ir.SCHOOL_VERIFICATION_METHOD
    assert record["verification"]["completed_at"]
    assert record["campus"]["location_id"] == LOCATION
    assert record["delegation"] == DELEGATION
    assert record["authorizer"]["capacity"] == "administrator"
    assert ir.validate_record(record, SCHOOL_NOTICE) == []


def test_the_licence_key_itself_is_never_stored(signing_key):
    key = sign(signing_key)
    record, _ = school(signing_key, license_key=key)
    assert key not in json.dumps(record)
    assert record["campus"]["license_key_sha256"] == hashlib.sha256(key.encode()).hexdigest()


def test_a_campus_key_alone_never_yields_verified(signing_key):
    """The key proves the campus, not the person."""
    record, findings = school(signing_key, delegation=None, capacity="")
    assert record["state"] == "pending_verification"
    assert "delegation_incomplete" in findings
    assert "authorizer_role_missing_or_unrecognised" in findings


@pytest.mark.parametrize("delegation,capacity", [
    (None, "administrator"),
    ({"reference": "x", "issued_by": "", "dated": YESTERDAY}, "administrator"),
    ({"reference": "", "issued_by": "y", "dated": YESTERDAY}, "administrator"),
    ({"reference": "x", "issued_by": "y", "dated": ""}, "teacher"),
    ({"reference": "x", "issued_by": "y", "dated": "last spring"}, "teacher"),
    (dict(DELEGATION), ""),
    (dict(DELEGATION), "janitor"),
])
def test_each_missing_piece_alone_leaves_a_school_pending(signing_key, delegation, capacity):
    record, _ = school(signing_key, delegation=delegation, capacity=capacity)
    assert record["state"] == "pending_verification"
    assert record["verification"] == {"method": None, "completed_at": None}


def test_a_school_needs_the_notice_acceptance_and_a_name(signing_key):
    with pytest.raises(ir.ReceiptError):
        school(signing_key, accepted=False)
    with pytest.raises(ir.ReceiptError):
        school(signing_key, authorizer_name="")


def test_a_delegation_dated_in_the_future_is_invalid(signing_key):
    future = (date.today() + timedelta(days=2)).isoformat()
    record, findings = school(signing_key, delegation={**DELEGATION, "dated": future})
    assert record["state"] == "invalid"
    assert "delegation_dated_in_the_future" in findings


@pytest.mark.parametrize("mutate,reason", [
    (lambda k: {"license_key": sign(k, location_id="another-campus-9")}, "campus_key_location_mismatch"),
    (lambda k: {"location_id": "another-campus-9"}, "campus_key_location_mismatch"),
    (lambda k: {"location_id": ""}, "campus_key_location_mismatch"),
    (lambda k: {"license_key": sign(k, issued=(date.today() - timedelta(days=60)).isoformat(),
                                    expires=(date.today() - timedelta(days=1)).isoformat())},
     "campus_key_expired"),
    (lambda k: {"license_key": sign(k, tier="core", seats=5, learner_scope=None, location_id=None)},
     "campus_key_invalid"),
    (lambda k: {"license_key": "not-a-key"}, "campus_key_invalid"),
])
def test_a_bad_campus_key_is_invalid_even_with_a_perfect_delegation(signing_key, mutate, reason):
    record, findings = school(signing_key, **mutate(signing_key))
    assert record["state"] == "invalid"
    assert any(f.startswith(reason) for f in findings), findings


def test_a_key_signed_by_someone_else_is_invalid(signing_key):
    stranger = ECC.generate(curve="Ed25519")
    record, findings = school(signing_key, license_key=sign(stranger))
    assert record["state"] == "invalid"
    assert any(f.startswith("campus_key_invalid") for f in findings)


def test_an_unsigned_decoded_payload_is_never_trusted(signing_key):
    """The wizard's old preflight decodes the payload without checking the
    signature; the receipt must not."""
    payload = base64.urlsafe_b64encode(json.dumps({
        "id": "x", "licensee": "x", "tier": "campus_location", "location_id": LOCATION,
        "learner_scope": "unlimited_at_location", "issued": date.today().isoformat(),
        "expires": (date.today() + timedelta(days=9)).isoformat(),
    }).encode()).decode().rstrip("=")
    record, _ = school(signing_key, license_key=payload + ".unsigned")
    assert record["state"] == "invalid"


def test_when_the_verifier_is_unavailable_nothing_is_verified(signing_key, monkeypatch):
    def unavailable():
        raise ir.VerifierUnavailable("no verifier")
    monkeypatch.setattr(ir, "_load_licensing", unavailable)
    with pytest.raises(ir.VerifierUnavailable):
        school(signing_key)


def test_an_invalid_school_receipt_is_reported_but_never_written(signing_key, tmp_path):
    record, _ = ir.create_and_write(
        repo_dir=tmp_path, mode="school", notice_bytes=SCHOOL_NOTICE, accepted=True,
        authorizer_name="Sam Principal", capacity="administrator", delegation=dict(DELEGATION),
        license_key=sign(signing_key), location_id="another-campus-9")
    assert record["state"] == "invalid"
    assert not ir.receipt_path(tmp_path).exists()


# ── file format and chain ────────────────────────────────────────────────────
def test_the_file_is_canonical_jsonl_readable_by_the_api_container(tmp_path):
    record, _ = ir.create_and_write(repo_dir=tmp_path, mode="family", notice_bytes=FAMILY_NOTICE,
                                    accepted=True, authorizer_name="Pat Parent", attested=True)
    path = ir.receipt_path(tmp_path)
    assert path == tmp_path / "install" / "installation_receipt.json"
    raw = path.read_bytes()
    assert raw == ir.canonical_bytes(record) + b"\n"
    assert oct(path.stat().st_mode & 0o777) == "0o644"


def test_a_later_receipt_chains_to_the_earlier_one_without_editing_it(tmp_path):
    kw = dict(repo_dir=tmp_path, mode="family", notice_bytes=FAMILY_NOTICE, accepted=True,
              authorizer_name="Pat Parent", attested=True)
    first, _ = ir.create_and_write(**kw)
    before = ir.receipt_path(tmp_path).read_bytes()
    second, _ = ir.create_and_write(**kw)
    assert second["prior_receipt_sha256"] == first["receipt_sha256"]
    assert ir.receipt_path(tmp_path).read_bytes().startswith(before)  # append-only
    assert ir.validate_chain(ir.read_chain(ir.receipt_path(tmp_path))) == []


def test_a_damaged_chain_is_refused_not_extended(tmp_path):
    kw = dict(repo_dir=tmp_path, mode="family", notice_bytes=FAMILY_NOTICE, accepted=True,
              authorizer_name="Pat Parent", attested=True)
    ir.create_and_write(**kw)
    path = ir.receipt_path(tmp_path)
    path.write_text(path.read_text().replace("pending_verification", "verified"))
    with pytest.raises(ir.ReceiptError, match="damaged"):
        ir.create_and_write(**kw)


def test_a_verified_record_without_its_evidence_is_not_valid():
    record, _ = family()
    forged = {**record, "state": "verified"}
    forged = ir.seal(forged)  # even re-sealed, the evidence is missing
    assert "verified_without_verification" in ir.validate_record(forged)


# ── the real setup.sh produces the same thing ────────────────────────────────
@pytest.fixture
def sandbox(tmp_path):
    shutil.copy(ROOT / "setup.sh", tmp_path / "setup.sh")
    data = tmp_path / "homeschool-api" / "data"
    data.mkdir(parents=True)
    shutil.copy(ROOT / "homeschool-api" / "data" / "consent_notice.txt", data)
    shutil.copy(ROOT / "homeschool-api" / "data" / "school_data_notice.txt", data)
    tool = tmp_path / "scripts" / "setup_wizard"
    tool.mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "setup_wizard" / "install_receipt.py", tool)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name in ("docker", "curl"):
        (stubs / name).write_text("#!/bin/sh\nexit 0\n")
        (stubs / name).chmod(0o755)
    # setup.sh's `python3` must be the interpreter that has pycryptodome.
    (stubs / "python3").write_text(f"#!/bin/sh\nexec '{sys.executable}' \"$@\"\n")
    (stubs / "python3").chmod(0o755)
    return tmp_path


ANSWERS = "1\nsk-ant-test\n\nparentpass123\n805274199\nlicense-value\n"
FAMILY_FLAGS = ["--accept-consent-notice", "--mode", "family", "--authorizer-name", "Pat Parent",
                "--attest-parent-guardian"]


def run_setup(sandbox, stdin, *args, extra_env=None):
    env = {**os.environ, "PATH": f"{sandbox / 'stubs'}:{os.environ['PATH']}", **(extra_env or {})}
    return subprocess.run(["bash", "setup.sh", *args], cwd=sandbox, input=stdin, text=True,
                          capture_output=True, env=env, timeout=60)


def receipts(sandbox):
    return ir.read_chain(sandbox / "install" / "installation_receipt.json")


def test_setup_sh_family_install_records_a_pending_receipt(sandbox):
    r = run_setup(sandbox, ANSWERS, *FAMILY_FLAGS)
    assert r.returncode == 0, r.stdout + r.stderr
    (record,) = receipts(sandbox)
    assert record["state"] == "pending_verification" and record["mode"] == "family"
    assert record["authorizer"]["name"] == "Pat Parent"
    assert record["installer"]["name"] == "setup.sh"
    assert ir.validate_record(record, FAMILY_NOTICE) == []
    assert "pending_verification" in r.stdout


def test_setup_sh_interactive_family_install_records_name_and_attestation(sandbox):
    r = run_setup(sandbox, "1\ny\nPat Parent\ny\n" + ANSWERS)
    assert r.returncode == 0, r.stdout + r.stderr
    (record,) = receipts(sandbox)
    assert record["authorizer"]["name"] == "Pat Parent"
    assert record["authorizer"]["capacity"] == "parent_guardian"


@pytest.mark.parametrize("drop", ["--authorizer-name", "--attest-parent-guardian", "--mode"])
def test_the_accept_flag_never_attests_for_you(sandbox, drop):
    args, skip = [], False
    for a in FAMILY_FLAGS:
        if skip:
            skip = False
            continue
        if a == drop:
            skip = a in ("--authorizer-name", "--mode")
            continue
        args.append(a)
    r = run_setup(sandbox, ANSWERS, *args)
    assert r.returncode != 0
    assert "Installation not completed" in r.stdout + r.stderr
    assert not (sandbox / ".env").exists()
    assert not (sandbox / "install").exists()


@pytest.mark.parametrize("stdin", [
    "1\nn\nPat\ny\n",              # declines the notice
    "1\ny\nPat Parent\nn\n",       # accepts but will not attest
    "1\ny\n\ny\n",                 # no name
])
def test_declining_or_withholding_the_attestation_leaves_nothing(sandbox, stdin):
    r = run_setup(sandbox, stdin + ANSWERS)
    assert r.returncode != 0
    assert not (sandbox / ".env").exists()
    assert not (sandbox / "install").exists()


def test_setup_sh_refuses_a_notice_edited_after_it_was_shown(sandbox):
    """The receipt tool re-hashes the file against the hash taken at display."""
    stubs = sandbox / "stubs"
    # `openssl rand` runs after the notice is displayed and hashed but before
    # the receipt is written; use it to edit the notice in between.
    notice = sandbox / "homeschool-api" / "data" / "consent_notice.txt"
    real_openssl = shutil.which("openssl")
    (stubs / "openssl").write_text(
        f"#!/bin/sh\nprintf '\\nEdited.\\n' >> '{notice}'\nexec '{real_openssl}' \"$@\"\n")
    (stubs / "openssl").chmod(0o755)
    r = run_setup(sandbox, ANSWERS, *FAMILY_FLAGS)
    assert r.returncode != 0
    assert "changed after it was shown" in r.stdout + r.stderr
    assert not (sandbox / ".env").exists()


def _school_env(sandbox, key):
    """Make the receipt tool's python trust the throwaway key (test-only)."""
    pem = sandbox / "test-public.pem"
    pem.write_text(key.public_key().export_key(format="PEM"))
    hook = sandbox / "pyhook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT / 'homeschool-api')!r})\n"
        "from core import licensing\n"
        f"licensing.PUBLIC_KEY_PEM = open({str(pem)!r}).read()\n")
    return {"PYTHONPATH": str(hook)}


SCHOOL_FLAGS = ["--accept-consent-notice", "--mode", "school", "--authorizer-name", "Sam Principal",
                "--authorizer-role", "administrator", "--location-id", LOCATION]
DELEGATION_FLAGS = ["--delegation-reference", "Board minute 14", "--delegation-issued-by",
                    "School board", "--delegation-dated", YESTERDAY]


def school_answers(key):
    return "1\nsk-ant-test\n\nparentpass123\n805274199\n" + sign(key) + "\n"


def test_setup_sh_school_install_is_verified_with_key_and_delegation(sandbox, signing_key):
    r = run_setup(sandbox, school_answers(signing_key), *SCHOOL_FLAGS, *DELEGATION_FLAGS,
                  extra_env=_school_env(sandbox, signing_key))
    assert r.returncode == 0, r.stdout + r.stderr
    (record,) = receipts(sandbox)
    assert record["state"] == "verified" and record["mode"] == "school"
    assert record["notice"]["file"] == "school_data_notice.txt"
    assert record["notice"]["sha256"] == hashlib.sha256(SCHOOL_NOTICE).hexdigest()
    # a school accepts its own notice; the family acknowledgement is not written
    assert "CONSENT_INSTALL_ACK_HASH" not in (sandbox / ".env").read_text()


def test_setup_sh_school_with_only_a_campus_key_is_pending(sandbox, signing_key):
    r = run_setup(sandbox, school_answers(signing_key), *SCHOOL_FLAGS,
                  extra_env=_school_env(sandbox, signing_key))
    assert r.returncode == 0, r.stdout + r.stderr
    (record,) = receipts(sandbox)
    assert record["state"] == "pending_verification"
    assert record["campus"]["license_key_sha256"]
    assert record["verification"]["method"] is None


def test_setup_sh_school_with_a_wrong_location_installs_nothing(sandbox, signing_key):
    flags = [a if a != LOCATION else "other-campus-77" for a in SCHOOL_FLAGS]
    r = run_setup(sandbox, school_answers(signing_key), *flags, *DELEGATION_FLAGS,
                  extra_env=_school_env(sandbox, signing_key))
    assert r.returncode != 0
    assert "campus_key_location_mismatch" in r.stdout + r.stderr
    assert not (sandbox / ".env").exists()
    assert not (sandbox / "install" / "installation_receipt.json").exists()
