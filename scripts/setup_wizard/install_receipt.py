#!/usr/bin/env python3
"""
Installation receipt (``bede.installation_receipt.v1``) -- the installers' half
of docs/INSTALLATION_AUTHORIZATION_FLOW.md.

Every installer (setup.sh, the browser wizard, and the native launchers that
run the wizard) records the adult's authorization as a local receipt BEFORE
writing any configuration. Only a receipt in state ``verified`` ever enables
child-data processing; everything this module can produce for a family is
``pending_verification`` until a reviewed parental-verification method exists
(docs/PARENTAL_VERIFICATION_PROPOSAL.md).

FILE FORMAT -- ``install/installation_receipt.json`` (relative to the repo
root, mounted read-only into the api container)
    JSON Lines: one canonical-JSON record per line, UTF-8, each line ending in
    "\\n". The file is append-only. The first line is the first record. A state
    change (or a re-installation after a notice change) APPENDS a new record
    whose ``prior_receipt_sha256`` is the previous record's ``receipt_sha256``;
    nothing already written is edited. A record with a non-null
    ``prior_receipt_sha256`` supersedes the one it names; the last line governs.
    The file is created mode 0644 (the api container's user reads it through a
    read-only bind mount) and contains the authorizer's NAME and capacity, never
    an identity document, a licence key, or a credential (only a SHA-256 of the
    campus key).

CANONICALIZATION AND ``receipt_sha256`` (the API's validator MUST match this)
    receipt_sha256 = sha256( canonical_bytes(record without "receipt_sha256") )
    canonical_bytes(x) = json.dumps(x, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode("utf-8")
    i.e. keys sorted at every nesting level, no whitespace, non-ASCII characters
    written as themselves (not \\uXXXX escapes), UTF-8 encoded; the hash is
    lowercase hex. The same function is the line serialization:
    the stored line is canonical_bytes(record WITH receipt_sha256) + b"\\n".
    ``null`` is JSON null; there are no floats. ``notice.sha256`` is the
    SHA-256 of the exact bytes of the notice file the adult was shown.

SCOPE
    The authorizer's name and a stated capacity are an ATTESTATION. This module
    never labels an attestation as verified consent, collects no identity
    document, and a campus licence key alone never yields ``verified``: the key
    proves the campus, not the person (a documented delegation and an explicit
    notice acceptance are also required).

Pure standard library, except that school mode verifies the Ed25519 signature
of the campus key with the SAME verifier the API uses
(homeschool-api/core/licensing.py ``verify_license``), which needs
pycryptodome. When that cannot be imported the key cannot be verified and the
installer stops (fail closed) -- it never falls back to trusting an unsigned
payload.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

SCHEMA = "bede.installation_receipt.v1"
RECEIPT_RELPATH = Path("install") / "installation_receipt.json"
INSTALLER_VERSION = "2026-10-30.1"

MODES = ("family", "school")
STATES = ("pending_verification", "verified", "invalid", "withdrawn", "superseded")
FAMILY_CAPACITIES = ("parent_guardian",)
SCHOOL_CAPACITIES = ("administrator", "teacher")
INSTALLER_NAMES = ("setup.sh", "wizard", "windows", "unix")

NOTICE_FILES = {"family": "consent_notice.txt", "school": "school_data_notice.txt"}

FAMILY_ATTESTATION = (
    "I am the parent or legal guardian of each child who will use Bede and the "
    "custodian of their personal information, and I have read and accept this Notice."
)
SCHOOL_ATTESTATION = (
    "I am an administrator or teacher of the School with the authority to authorize "
    "the storage of student information as set out in this Notice, and I have read "
    "and accept this Notice."
)
SCHOOL_VERIFICATION_METHOD = "signed_campus_key_and_documented_delegation"

_MAX_TEXT = 200
_LOCATION_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{2,63}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ReceiptError(Exception):
    """The receipt cannot be produced (declined, unreadable chain, bad input)."""


class VerifierUnavailable(ReceiptError):
    """The signed campus-key verifier cannot run here (fail closed)."""


# ── canonical form ───────────────────────────────────────────────────────────
def canonical_bytes(obj) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def compute_receipt_sha256(record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "receipt_sha256"}
    return hashlib.sha256(canonical_bytes(body)).hexdigest()


def seal(record: dict) -> dict:
    sealed = {k: v for k, v in record.items() if k != "receipt_sha256"}
    sealed["receipt_sha256"] = compute_receipt_sha256(sealed)
    return sealed


# ── notices ──────────────────────────────────────────────────────────────────
def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def default_notice_path(mode: str) -> Path:
    name = NOTICE_FILES[mode]
    in_image = Path("/app") / name
    if in_image.is_file():
        return in_image
    return _repo_root() / "homeschool-api" / "data" / name


def notice_version(notice: bytes) -> str:
    first = notice.decode("utf-8").splitlines()[0] if notice else ""
    prefix = "Notice version:"
    if not first.startswith(prefix) or not first[len(prefix):].strip():
        raise ReceiptError("the notice must begin with 'Notice version: <X>'")
    return first[len(prefix):].strip()


# ── campus key ───────────────────────────────────────────────────────────────
def _load_licensing():
    for base in ("/app/homeschool-api", str(_repo_root() / "homeschool-api")):
        if os.path.isdir(base) and base not in sys.path:
            sys.path.insert(0, base)
    try:
        from core import licensing
    except ImportError as exc:  # pycryptodome (Crypto) or the module missing
        raise VerifierUnavailable(
            "The campus licence key cannot be verified on this computer (the signed "
            "licence verifier is unavailable: %s). Nothing was installed." % exc
        ) from exc
    return licensing


def check_campus_key(license_key: str, location_id: str):
    """Return (ok, reason). Signature, tier, expiry and location are all checked
    with core/licensing.py -- the API's own verifier -- never an unsigned decode."""
    licensing = _load_licensing()
    try:
        info = licensing.verify_license(license_key)
    except licensing.InvalidLicenseError as exc:
        return False, "campus_key_invalid: %s" % exc
    if info.tier != "campus_location" or not info.unlimited_learners:
        return False, "campus_key_wrong_tier"
    if info.is_expired:
        return False, "campus_key_expired"
    if not location_id or not licensing.location_matches(info, location_id):
        return False, "campus_key_location_mismatch"
    return True, "ok"


# ── field hygiene ────────────────────────────────────────────────────────────
def _clean(text) -> str:
    if text is None:
        return ""
    text = str(text).strip()
    if any(unicodedata.category(c).startswith("C") for c in text):
        raise ReceiptError("control characters are not allowed in receipt fields")
    if len(text) > _MAX_TEXT:
        raise ReceiptError("a receipt field is longer than %d characters" % _MAX_TEXT)
    return text


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _valid_past_date(raw: str, today: date):
    """(ok, problem). problem is None, 'malformed' or 'future'."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw or ""):
        return False, "malformed"
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        return False, "malformed"
    return (False, "future") if d > today else (True, None)


# ── building ─────────────────────────────────────────────────────────────────
def build_receipt(
    *,
    mode: str,
    notice_bytes: bytes,
    accepted: bool,
    authorizer_name: str,
    attested: bool = False,
    capacity: str = "",
    delegation: dict | None = None,
    license_key: str = "",
    location_id: str = "",
    installer_name: str = "wizard",
    accepted_at: str | None = None,
    prior_receipt_sha256: str | None = None,
    shown_notice_sha256: str | None = None,
    today: date | None = None,
    receipt_id: str | None = None,
):
    """Return (record, findings). ``findings`` lists why a receipt is not
    verified; it is for the installer's message and is not stored."""
    if mode not in MODES:
        raise ReceiptError("mode must be 'family' or 'school'")
    if installer_name not in INSTALLER_NAMES:
        raise ReceiptError("unknown installer name")
    if not accepted:
        # Declining (or never accepting) creates no receipt at all.
        raise ReceiptError("the notice was not accepted; no receipt is created")
    notice_sha = hashlib.sha256(notice_bytes).hexdigest()
    if shown_notice_sha256 and shown_notice_sha256 != notice_sha:
        raise ReceiptError(
            "the notice changed after it was shown (hash mismatch); refusing to record acceptance"
        )
    today = today or datetime.now(timezone.utc).date()
    name = _clean(authorizer_name)
    if not name:
        raise ReceiptError("the authorizer's name is required")

    findings: list[str] = []
    state = "pending_verification"
    verification = {"method": None, "completed_at": None}
    delegation_rec = None
    campus_rec = None

    if mode == "family":
        if not attested:
            raise ReceiptError(
                "the parent or legal guardian attestation is required (it is never assumed)"
            )
        capacity_rec = "parent_guardian"
        attestation = FAMILY_ATTESTATION
        findings.append("parental_verification_method_unavailable")
    else:
        capacity_rec = _clean(capacity)
        attestation = SCHOOL_ATTESTATION
        d = delegation or {}
        deleg = {
            "reference": _clean(d.get("reference")) or None,
            "issued_by": _clean(d.get("issued_by")) or None,
            "dated": _clean(d.get("dated")) or None,
        }
        if any(deleg.values()):
            delegation_rec = deleg
        key = (license_key or "").strip()
        location = _clean(location_id)
        if not key:
            raise ReceiptError("the campus licence key is required for a school installation")
        if location and not _LOCATION_RE.fullmatch(location):
            raise ReceiptError("the campus location id is not valid")
        campus_rec = {
            "location_id": location or None,
            "license_key_sha256": hashlib.sha256(key.encode("utf-8")).hexdigest(),
        }
        key_ok, key_reason = check_campus_key(key, location)
        invalid = not key_ok
        if not key_ok:
            findings.append(key_reason)
        if capacity_rec not in SCHOOL_CAPACITIES:
            findings.append("authorizer_role_missing_or_unrecognised")
        if not (deleg["reference"] and deleg["issued_by"]):
            findings.append("delegation_incomplete")
        date_ok, date_problem = _valid_past_date(deleg["dated"] or "", today)
        if not date_ok:
            if date_problem == "future":
                findings.append("delegation_dated_in_the_future")
                invalid = True
            else:
                findings.append("delegation_date_missing_or_malformed")
        if invalid:
            state = "invalid"
        elif not findings:
            state = "verified"
            verification = {"method": SCHOOL_VERIFICATION_METHOD, "completed_at": _utc_now()}

    record = {
        "schema": SCHEMA,
        "receipt_id": receipt_id or str(uuid.uuid4()),
        "mode": mode,
        "state": state,
        "notice": {
            "file": NOTICE_FILES[mode],
            "version": notice_version(notice_bytes),
            "sha256": notice_sha,
        },
        "accepted_at": accepted_at or _utc_now(),
        "authorizer": {"name": name, "capacity": capacity_rec, "attestation": attestation},
        "delegation": delegation_rec,
        "campus": campus_rec,
        "verification": verification,
        "installer": {"name": installer_name, "version": INSTALLER_VERSION},
        "prior_receipt_sha256": prior_receipt_sha256,
    }
    return seal(record), findings


# ── validation (what the API's validator must agree with) ────────────────────
def validate_record(record: dict, notice_bytes: bytes | None = None) -> list[str]:
    """Return problems; an empty list means structurally valid. When
    ``notice_bytes`` is given, also checks the recorded hash against it."""
    problems: list[str] = []
    if not isinstance(record, dict):
        return ["not_an_object"]
    if record.get("schema") != SCHEMA:
        problems.append("schema")
    if record.get("mode") not in MODES:
        problems.append("mode")
    if record.get("state") not in STATES:
        problems.append("state")
    sha = record.get("receipt_sha256")
    if not isinstance(sha, str) or not _HEX64.fullmatch(sha):
        problems.append("receipt_sha256_format")
    elif compute_receipt_sha256(record) != sha:
        problems.append("receipt_sha256_mismatch")
    notice = record.get("notice") or {}
    if not isinstance(notice, dict) or not _HEX64.fullmatch(str(notice.get("sha256", ""))):
        problems.append("notice_sha256_format")
    elif notice_bytes is not None and hashlib.sha256(notice_bytes).hexdigest() != notice["sha256"]:
        problems.append("notice_sha256_mismatch")
    prior = record.get("prior_receipt_sha256")
    if prior is not None and not (isinstance(prior, str) and _HEX64.fullmatch(prior)):
        problems.append("prior_receipt_sha256_format")
    if record.get("state") == "verified":
        ver = record.get("verification") or {}
        if not ver.get("method") or not ver.get("completed_at"):
            problems.append("verified_without_verification")
        if record.get("mode") == "school":
            d = record.get("delegation") or {}
            a = record.get("authorizer") or {}
            c = record.get("campus") or {}
            if not (d.get("reference") and d.get("issued_by") and d.get("dated")):
                problems.append("verified_school_without_delegation")
            if a.get("capacity") not in SCHOOL_CAPACITIES or not a.get("name"):
                problems.append("verified_school_without_authorizer")
            if not c.get("location_id") or not c.get("license_key_sha256"):
                problems.append("verified_school_without_campus")
    return problems


def validate_chain(records: list[dict], notices: dict | None = None) -> list[str]:
    """Check every record, the prior-hash links, and (when ``notices`` maps a
    notice filename to its current bytes) that no notice was altered."""
    problems: list[str] = []
    previous = None
    for i, rec in enumerate(records):
        nb = (notices or {}).get(((rec or {}).get("notice") or {}).get("file"))
        problems += ["record %d: %s" % (i, p) for p in validate_record(rec, nb)]
        if isinstance(rec, dict) and rec.get("prior_receipt_sha256") != previous:
            problems.append("record %d: chain_broken" % i)
        previous = rec.get("receipt_sha256") if isinstance(rec, dict) else None
    return problems


# ── file I/O ─────────────────────────────────────────────────────────────────
def receipt_path(repo_dir) -> Path:
    return Path(repo_dir) / RECEIPT_RELPATH


def read_chain(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except ValueError as exc:
            raise ReceiptError("%s line %d is not valid JSON" % (path, n)) from exc
    return records


def head_hash(path: Path):
    """Hash of the last record of an existing, intact chain (None if no file).
    A damaged chain is refused rather than appended to."""
    records = read_chain(path)
    if not records:
        return None
    problems = validate_chain(records)
    if problems:
        raise ReceiptError(
            "the existing installation receipt chain is damaged (%s); move install/ aside "
            "and re-run to start a new chain" % "; ".join(problems[:3])
        )
    return records[-1]["receipt_sha256"]


def append_record(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = canonical_bytes(record) + b"\n"
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.chmod(str(path), 0o644)
    except OSError:
        pass


def create_and_write(*, repo_dir, **kwargs):
    """Build a receipt chained to any existing one and append it -- unless it
    is ``invalid``, which is reported but never written as an installation."""
    path = receipt_path(repo_dir)
    record, findings = build_receipt(prior_receipt_sha256=head_hash(path), **kwargs)
    if record["state"] != "invalid":
        append_record(path, record)
    return record, findings


# ── CLI (used by setup.sh) ───────────────────────────────────────────────────
def _cli_create(args) -> int:
    try:
        notice_path = Path(args.notice_file) if args.notice_file else default_notice_path(args.mode)
        notice = notice_path.read_bytes()
        license_key = os.environ.get(args.license_key_env, "") if args.license_key_env else ""
        record, findings = create_and_write(
            repo_dir=args.repo_dir,
            mode=args.mode,
            notice_bytes=notice,
            accepted=bool(args.accept_notice),
            authorizer_name=args.authorizer_name or "",
            attested=bool(args.attest_parent_guardian),
            capacity=args.capacity or "",
            delegation={
                "reference": args.delegation_reference,
                "issued_by": args.delegation_issued_by,
                "dated": args.delegation_dated,
            },
            license_key=license_key,
            location_id=args.location_id or "",
            installer_name=args.installer,
            accepted_at=args.accepted_at or None,
            shown_notice_sha256=args.shown_notice_sha256 or None,
        )
    except VerifierUnavailable as exc:
        print(json.dumps({"error": str(exc)}))
        return 4
    except (ReceiptError, OSError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    print(json.dumps({
        "state": record["state"],
        "receipt_id": record["receipt_id"],
        "receipt_sha256": record["receipt_sha256"],
        "findings": findings,
    }))
    return 3 if record["state"] == "invalid" else 0


def _cli_verify(args) -> int:
    try:
        records = read_chain(receipt_path(args.repo_dir))
    except ReceiptError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    notices = {}
    for mode, fname in NOTICE_FILES.items():
        p = default_notice_path(mode)
        if p.is_file():
            notices[fname] = p.read_bytes()
    problems = validate_chain(records, notices) if records else ["no_receipt"]
    print(json.dumps({
        "problems": problems,
        "state": records[-1]["state"] if records else None,
    }))
    return 0 if not problems else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--repo-dir", required=True)
    c.add_argument("--mode", required=True, choices=MODES)
    c.add_argument("--installer", required=True, choices=INSTALLER_NAMES)
    c.add_argument("--notice-file")
    c.add_argument("--shown-notice-sha256")
    c.add_argument("--accepted-at")
    c.add_argument("--accept-notice", action="store_true")
    c.add_argument("--authorizer-name")
    c.add_argument("--attest-parent-guardian", action="store_true")
    c.add_argument("--capacity")
    c.add_argument("--delegation-reference")
    c.add_argument("--delegation-issued-by")
    c.add_argument("--delegation-dated")
    c.add_argument("--location-id")
    c.add_argument("--license-key-env", help="NAME of an environment variable holding the key")
    c.set_defaults(fn=_cli_create)
    v = sub.add_parser("verify")
    v.add_argument("--repo-dir", required=True)
    v.set_defaults(fn=_cli_verify)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
