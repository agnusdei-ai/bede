"""Build real installation receipts for tests: same sealing code the API
validates with (core.installation_receipt.seal), so a test receipt is exactly
the shape an installer must produce."""
import json
import tempfile
import uuid
from pathlib import Path

from core import consent, installation_receipt as ir, school_authorization
from core.config import settings

LOCATION = "11111111-2222-3333-4444-555555555555"
KEY_SHA = "a" * 64
ACCEPTED = "2026-10-31T12:00:00Z"


def family_record(state="verified", *, accepted_at=ACCEPTED, notice_sha=None, receipt_id=None, **over):
    rec = {
        "schema": ir.SCHEMA,
        "receipt_id": receipt_id or str(uuid.uuid4()),
        "mode": "family",
        "state": state,
        "notice": {"file": "consent_notice.txt", "version": "t",
                   "sha256": consent.notice_hash() if notice_sha is None else notice_sha},
        "accepted_at": accepted_at,
        "authorizer": {"name": "Pat Parent", "capacity": "parent_guardian", "attestation": "I am the parent"},
        "delegation": None,
        "campus": None,
        "verification": ({"method": "email_plus", "completed_at": "2026-10-31T13:00:00Z"}
                         if state == "verified" else {"method": None, "completed_at": None}),
        "installer": {"name": "setup.sh", "version": "1"},
    }
    rec.update(over)
    return rec


def school_record(state="verified", *, location=LOCATION, receipt_id=None, role="administrator", **over):
    rec = {
        "schema": ir.SCHEMA,
        "receipt_id": receipt_id or str(uuid.uuid4()),
        "mode": "school",
        "state": state,
        "notice": {"file": "school_data_notice.txt", "version": "t",
                   "sha256": school_authorization.notice_hash()},
        "accepted_at": ACCEPTED,
        "authorizer": {"name": "Sam Principal", "capacity": role, "attestation": "authorized"},
        "delegation": {"reference": "board-minute-12", "issued_by": "School board", "dated": "2026-09-01"},
        "campus": {"location_id": location, "license_key_sha256": KEY_SHA},
        "verification": {"method": "campus_key", "completed_at": ACCEPTED},
        "installer": {"name": "wizard", "version": "1"},
    }
    rec.update(over)
    return rec


def chain(*records):
    """Seal records into one chain (each links to the previous)."""
    out, prior = [], None
    for r in records:
        s = ir.seal(r, prior)
        out.append(s)
        prior = s["receipt_sha256"]
    return out


def install(monkeypatch, records, *, location=None):
    """Write `records` (already sealed) as the base file and point settings at it."""
    d = Path(tempfile.mkdtemp())
    (d / "installation_receipt.json").write_text(json.dumps(records))
    monkeypatch.setattr(settings, "installation_receipt_path", str(d / "installation_receipt.json"))
    monkeypatch.setattr(settings, "installation_receipt_append_path", str(d / "append.jsonl"))
    if location is not None:
        monkeypatch.setattr(settings, "bede_location_id", location)
    ir.invalidate()
    return d


def verified_family(monkeypatch, **kw):
    return install(monkeypatch, chain(family_record("verified", **kw)))


def no_receipt(monkeypatch):
    d = Path(tempfile.mkdtemp())
    monkeypatch.setattr(settings, "installation_receipt_path", str(d / "installation_receipt.json"))
    monkeypatch.setattr(settings, "installation_receipt_append_path", str(d / "append.jsonl"))
    ir.invalidate()
    return d
