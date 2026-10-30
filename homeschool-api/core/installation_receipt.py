"""
The installation receipt: an append-only, hash-chained record of who authorized
this installation to process child data, and the single place that decides
whether it currently does.

CONTRACT. docs/INSTALLATION_AUTHORIZATION_FLOW.md. A receipt
(`bede.installation_receipt.v1`) lives in `install/installation_receipt.json`,
mounted READ-ONLY into the api container. State changes are recorded by
APPENDING a new record, never by editing: every record carries
`prior_receipt_sha256` (the previous record's hash) and its own
`receipt_sha256`. Because the install mount is read-only, records the API
appends itself (a withdrawal) go to a separate writable append file
(`installation_receipt_append_path`, one JSON object per line); the chain is
the base file's records followed by the append file's.

HASH. `receipt_sha256` is the SHA-256 of the record's canonical JSON with the
`receipt_sha256` field removed: `json.dumps(rec, sort_keys=True,
separators=(",", ":"), ensure_ascii=False)` encoded as UTF-8. The base file is
either one receipt object, a JSON array of receipt objects, or
`{"records": [...]}`.

WHAT THIS PROVES. The chain is TAMPER-EVIDENT, not authenticated: there is no
signature, so someone who can write the install directory and recompute every
hash can forge a chain. What it does catch is the realistic failures: a field
edited by hand, a record deleted or reordered, a receipt copied from another
installation (wrong location id), a receipt for a notice that has since
changed. The campus key and delegation record are the school's authentication
leg; the parental-verification method is the family's, and none is approved.

NEVER TRUST THE FILE FOR "verified". `current()` reports `verified` only when
EVERY record's hash and chain link validate, the last record's state is
`verified`, its notice hash equals the SHA-256 of the notice bytes this build
ships, and the mode's required fields are present and (school) the location
matches `BEDE_LOCATION_ID`. Anything else is `invalid`, `pending_verification`,
`withdrawn`, `superseded`, or `none` (no file), and every one of those leaves
child-data processing off. A missing or unreadable file is `none`: closed.

Whether any verification method is sufficient is for counsel. Nothing here
decides it.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from core.config import settings

SCHEMA = "bede.installation_receipt.v1"
STATES = ("pending_verification", "verified", "invalid", "withdrawn", "superseded")
MODES = ("family", "school")
NONE_STATE = "none"  # no receipt file: not one of the contract's states, and closed

NOTICE_FILES = {"family": "consent_notice.txt", "school": "school_data_notice.txt"}
FAMILY_CAPACITY = "parent_guardian"
SCHOOL_CAPACITIES = ("administrator", "teacher")

# Same receipt_id: which state may follow which. A record carrying a DIFFERENT
# receipt_id is a new authorization (reauthorization) and starts afresh.
_TRANSITIONS = {
    "pending_verification": {"pending_verification", "verified", "invalid", "withdrawn", "superseded"},
    "verified": {"verified", "invalid", "withdrawn", "superseded"},
    "invalid": {"invalid", "withdrawn", "superseded"},
    "withdrawn": {"withdrawn", "superseded"},
    "superseded": {"superseded"},
}

_SHA = re.compile(r"^[0-9a-f]{64}$")
_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Hashing ───────────────────────────────────────────────────────────────────

def record_hash(record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "receipt_sha256"}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def seal(record: dict, prior_receipt_sha256: Optional[str]) -> dict:
    """Return a copy of `record` chained to `prior` with its hash filled in."""
    out = copy.deepcopy(record)
    out["prior_receipt_sha256"] = prior_receipt_sha256
    out["receipt_sha256"] = record_hash(out)
    return out


# ── Paths ─────────────────────────────────────────────────────────────────────

def receipt_path() -> Path:
    return Path(settings.installation_receipt_path)


def append_path() -> Path:
    return Path(settings.installation_receipt_append_path)


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class InstallationState:
    state: str
    chain_valid: bool
    reasons: tuple = ()
    mode: Optional[str] = None
    receipt_id: Optional[str] = None
    record_count: int = 0
    accepted_at: Optional[str] = None
    location_id: Optional[str] = None
    authorizer_capacity: Optional[str] = None
    last_receipt_sha256: Optional[str] = None
    # The last record as written (never trusted beyond what `state` says).
    last_record: dict = field(default_factory=dict, compare=False)

    @property
    def processing_enabled(self) -> bool:
        return self.state == "verified"

    @property
    def family_verified(self) -> bool:
        return self.state == "verified" and self.mode == "family"

    @property
    def school_verified(self) -> bool:
        return self.state == "verified" and self.mode == "school"


# ── Loading ───────────────────────────────────────────────────────────────────

def _load_base(path: Path) -> list:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("records"), list):
        return raw["records"]
    if isinstance(raw, list):
        return raw
    return [raw]


def _load_appended(path: Path) -> list:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _stat_key(path: Path):
    try:
        st = path.stat()
        return (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return (str(path), None, None)


def _notice_sha(mode: str) -> Optional[str]:
    """SHA-256 of the notice bytes THIS build ships for the mode."""
    try:
        if mode == "family":
            from core import consent
            return consent.notice_hash()
        if mode == "school":
            from core import school_authorization
            return school_authorization.notice_hash()
    except Exception:
        return None
    return None


def _parse_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        at = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if at.tzinfo is None:
        return None
    return at.astimezone(timezone.utc)


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


# ── Validation ────────────────────────────────────────────────────────────────

def _check_structure(rec: Any) -> Optional[str]:
    if not isinstance(rec, dict):
        return "record_not_an_object"
    if rec.get("schema") != SCHEMA:
        return "unknown_schema"
    if not _nonempty(rec.get("receipt_id")):
        return "missing_receipt_id"
    if rec.get("mode") not in MODES:
        return "unknown_mode"
    if rec.get("state") not in STATES:
        return "unknown_state"
    notice = rec.get("notice")
    if not isinstance(notice, dict) or not isinstance(notice.get("sha256"), str):
        return "missing_notice"
    return None


def _chain_problem(records: list) -> Optional[str]:
    prior_hash: Optional[str] = None
    prev: Optional[dict] = None
    for i, rec in enumerate(records):
        bad = _check_structure(rec)
        if bad:
            return f"record_{i}_{bad}"
        if not isinstance(rec.get("receipt_sha256"), str) or rec["receipt_sha256"] != record_hash(rec):
            return f"record_{i}_hash_mismatch"
        if rec.get("prior_receipt_sha256") != prior_hash:
            return f"record_{i}_chain_broken"
        if prev is not None and prev["receipt_id"] == rec["receipt_id"]:
            if rec["mode"] != prev["mode"]:
                return f"record_{i}_mode_changed"
            if rec["state"] not in _TRANSITIONS[prev["state"]]:
                return f"record_{i}_illegal_transition"
        prior_hash = rec["receipt_sha256"]
        prev = rec
    return None


def _verified_problems(rec: dict) -> list:
    """Everything a `verified` record must carry. Empty list = acceptable."""
    problems = []
    mode = rec["mode"]
    notice = rec["notice"]
    if notice.get("file") != NOTICE_FILES[mode]:
        problems.append("notice_file_mismatch")
    current = _notice_sha(mode)
    if current is None or notice.get("sha256") != current:
        problems.append("notice_changed")
    at = _parse_iso(rec.get("accepted_at"))
    if at is None:
        problems.append("accepted_at_invalid")
    auth = rec.get("authorizer")
    auth = auth if isinstance(auth, dict) else {}
    if not _nonempty(auth.get("name")) or not _nonempty(auth.get("attestation")):
        problems.append("authorizer_incomplete")
    verification = rec.get("verification")
    verification = verification if isinstance(verification, dict) else {}
    if mode == "family":
        if auth.get("capacity") != FAMILY_CAPACITY:
            problems.append("authorizer_capacity_invalid")
        if not _nonempty(verification.get("method")) or _parse_iso(verification.get("completed_at")) is None:
            problems.append("verification_incomplete")
    else:
        if auth.get("capacity") not in SCHOOL_CAPACITIES:
            problems.append("authorizer_capacity_invalid")
        delegation = rec.get("delegation")
        delegation = delegation if isinstance(delegation, dict) else {}
        if not (_nonempty(delegation.get("reference")) and _nonempty(delegation.get("issued_by"))):
            problems.append("delegation_incomplete")
        try:
            date.fromisoformat(str(delegation.get("dated", "")))
        except ValueError:
            problems.append("delegation_date_invalid")
        campus = rec.get("campus")
        campus = campus if isinstance(campus, dict) else {}
        loc = campus.get("location_id")
        configured = (settings.bede_location_id or "").strip()
        if not _nonempty(loc) or not configured or loc.strip() != configured:
            problems.append("location_mismatch")
        if not isinstance(campus.get("license_key_sha256"), str) or not _SHA.match(campus["license_key_sha256"]):
            problems.append("campus_key_missing")
    return problems


def _resolve(records: list) -> InstallationState:
    if not records:
        return InstallationState(state=NONE_STATE, chain_valid=True)
    problem = _chain_problem(records)
    last = records[-1] if isinstance(records[-1], dict) else {}
    ident = dict(
        mode=last.get("mode") if last.get("mode") in MODES else None,
        receipt_id=last.get("receipt_id") if isinstance(last.get("receipt_id"), str) else None,
        record_count=len(records),
    )
    if problem:
        return InstallationState(state="invalid", chain_valid=False, reasons=(problem,), **ident)
    state = last["state"]
    reasons: tuple = ()
    if state == "verified":
        found = _verified_problems(last)
        if found:
            state, reasons = "invalid", tuple(found)
    elif state == "pending_verification":
        # A pending receipt for a notice that has since changed is stale.
        if last["notice"].get("sha256") != _notice_sha(last["mode"]):
            state, reasons = "invalid", ("notice_changed",)
    campus = last.get("campus") if isinstance(last.get("campus"), dict) else {}
    auth = last.get("authorizer") if isinstance(last.get("authorizer"), dict) else {}
    return InstallationState(
        state=state, chain_valid=True, reasons=reasons,
        accepted_at=last.get("accepted_at") if isinstance(last.get("accepted_at"), str) else None,
        location_id=campus.get("location_id") if last["mode"] == "school" else None,
        authorizer_capacity=auth.get("capacity"),
        last_receipt_sha256=last["receipt_sha256"],
        last_record=copy.deepcopy(last),
        **ident,
    )


_cache: dict = {"key": None, "value": None}


def current() -> InstallationState:
    """The current installation state. Cached on file stat + inputs, so a hot
    path (every collection route) costs two stats, not a parse. Never raises:
    an unreadable or malformed file is `invalid` (or `none` when absent)."""
    base, extra = receipt_path(), append_path()
    key = (
        _stat_key(base), _stat_key(extra), (settings.bede_location_id or "").strip(),
        _notice_sha("family"), _notice_sha("school"),
    )
    with _lock:
        if _cache["key"] == key:
            return _cache["value"]
        try:
            records = _load_base(base) if base.is_file() else []
            if extra.is_file():
                records += _load_appended(extra)
            value = _resolve(records)
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            value = InstallationState(state="invalid", chain_valid=False,
                                      reasons=(f"unreadable:{type(exc).__name__}",))
        _cache["key"], _cache["value"] = key, value
        return value


def invalidate() -> None:
    with _lock:
        _cache["key"] = _cache["value"] = None


# ── Appending ─────────────────────────────────────────────────────────────────

class ReceiptError(Exception):
    def __init__(self, http_status: int, code: str, message: str):
        super().__init__(message)
        self.http_status, self.code, self.message = http_status, code, message


def append_withdrawal(*, by_role: str) -> InstallationState:
    """Append a `withdrawn` record chained to the current tip. Never edits an
    existing record; the original receipt is preserved."""
    st = current()
    if st.state == NONE_STATE:
        raise ReceiptError(409, "no_receipt", "There is no installation receipt to withdraw.")
    if not st.chain_valid:
        raise ReceiptError(
            409, "receipt_chain_invalid",
            "The installation receipt chain does not validate, so nothing can be appended to it. "
            "Child-data processing is already off.",
        )
    if st.state in ("withdrawn", "superseded"):
        raise ReceiptError(409, "already_ended", f"The installation receipt is already {st.state}.")
    record = copy.deepcopy(st.last_record)
    record["state"] = "withdrawn"
    record["recorded_at"] = _now().isoformat().replace("+00:00", "Z")
    record["recorded_by"] = by_role
    sealed = seal(record, st.last_receipt_sha256)
    path = append_path()
    line = json.dumps(sealed, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
            try:
                os.write(fd, line.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
    except OSError as exc:
        raise ReceiptError(
            503, "withdrawal_not_recorded",
            "The withdrawal could not be written, so it was NOT recorded. "
            f"({type(exc).__name__})",
        ) from exc
    invalidate()
    return current()
