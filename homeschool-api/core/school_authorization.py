"""
School data authorization: a school official's recorded opt-in to storing
learner data for a campus, and the gate that enforces it.

WHAT THIS IS. A readiness control. Before any pilot route stores learner data
for a campus, the campus must hold an active authorization recorded against
the CURRENT notice. The ledger records who (role and reference, plus an
encrypted name), against which notice (its hash), and when. Old rows are
never rewritten: a grant against a changed notice adds a row; a revoke only
stamps revoked_at.

WHAT THIS IS NOT. Whether a school official has authority to authorize, and
whether this wording or mechanism suffices for the school's obligations, are
questions for counsel. Nothing here decides them. The wording is a draft.

STALE. A record against an older notice hash does not authorize new writes:
the notice changed, so a school official must read it again.

SCOPE OF THE GATE. Writes that store learner data are refused. Reads and
deletion stay available so a school can review and delete after withdrawing.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select

from core.encryption import aad_for, decrypt_json, encrypt_json

NOTICE_PATH = Path(__file__).resolve().parent.parent / "data" / "school_data_notice.txt"
SCOPE = "school_learner_records"
ROLES = ("administrator", "teacher")
ADMIN_REF = "administrator"


def _notice_bytes() -> bytes:
    return NOTICE_PATH.read_bytes()


def notice_text() -> str:
    return _notice_bytes().decode("utf-8")


def notice_hash() -> str:
    """SHA-256 of the notice file's exact bytes."""
    return hashlib.sha256(_notice_bytes()).hexdigest()


def notice_version() -> str:
    first = notice_text().splitlines()[0]
    prefix = "Notice version:"
    if not first.startswith(prefix):
        raise RuntimeError("school data notice must begin with 'Notice version:'")
    return first[len(prefix):].strip()


class SchoolAuthorizationError(Exception):
    def __init__(self, http_status: int, code: str, message: str):
        super().__init__(message)
        self.http_status = http_status
        self.code = code
        self.message = message


def authorize_path(campus_id: str) -> str:
    return f"/pilot/campuses/{campus_id}/data-authorization"


def _name_aad(campus_id: str, row_id: str) -> bytes:
    return aad_for("pilot_campus_data_authorizations", "authorizer_name_enc", f"{campus_id}:{row_id}")


def _reason_aad(campus_id: str, row_id: str) -> bytes:
    return aad_for("pilot_campus_data_authorizations", "revocation_reason_enc", f"{campus_id}:{row_id}")


async def active(db, campus_id: str):
    """The current unrevoked record for the campus, or None (any notice hash)."""
    from core.database import PilotCampusDataAuthorization as A
    return (await db.execute(
        select(A).where(A.campus_id == campus_id, A.revoked_at.is_(None))
        .order_by(A.granted_at.desc(), A.id.desc()).limit(1)
    )).scalar_one_or_none()


async def is_authorized(db, campus_id: str) -> bool:
    row = await active(db, campus_id)
    return row is not None and row.notice_hash == notice_hash()


async def status_for(db, campus_id: str) -> dict:
    row = await active(db, campus_id)
    current = notice_hash()
    ok = row is not None and row.notice_hash == current
    return {
        "authorized": ok,
        "stale": row is not None and not ok,
        "notice_hash": current,
        "notice_version": notice_version(),
        "notice_text": notice_text(),
        "authorized_at": row.granted_at.isoformat() if ok else None,
        "authorized_by": row.authorizer_role if ok else None,
    }


async def grant(db, campus_id: str, *, authorizer_role: str, authorizer_ref: str,
                authorizer_name: str, presented_notice_hash: str):
    """Record an authorization. Returns (record, created)."""
    from core.database import PilotCampusDataAuthorization as A
    if authorizer_role not in ROLES:
        raise SchoolAuthorizationError(422, "unknown_role", "Unknown authorizer role.")
    if presented_notice_hash != notice_hash():
        raise SchoolAuthorizationError(
            409, "notice_changed",
            "The notice has changed since it was shown. Show the current notice and try again.",
        )
    existing = await active(db, campus_id)
    if existing is not None and existing.notice_hash == notice_hash():
        return existing, False
    # A stale record is left exactly as it was (history). The new row, being
    # the latest, is the one active() returns.
    row_id = str(uuid.uuid4())
    record = A(
        id=row_id, campus_id=campus_id, authorizer_role=authorizer_role,
        authorizer_ref=authorizer_ref,
        authorizer_name_enc=encrypt_json({"name": authorizer_name}, _name_aad(campus_id, row_id)),
        notice_hash=notice_hash(), scope=SCOPE, granted_at=datetime.now(timezone.utc),
    )
    db.add(record)
    await db.commit()
    return record, True


async def revoke(db, campus_id: str, *, reason: Optional[str]):
    """Withdraw the authorization. Deletes nothing. None if none active.

    Stamps every unrevoked row (a superseded stale row is otherwise left
    unrevoked and would resurface as the active one)."""
    from core.database import PilotCampusDataAuthorization as A
    latest = await active(db, campus_id)
    if latest is None:
        return None
    now = datetime.now(timezone.utc)
    for row in (await db.execute(
        select(A).where(A.campus_id == campus_id, A.revoked_at.is_(None))
    )).scalars().all():
        row.revoked_at = now
    if reason:
        latest.revocation_reason_enc = encrypt_json({"reason": reason}, _reason_aad(campus_id, latest.id))
    await db.commit()
    return latest


def authorizer_name(row) -> str:
    return decrypt_json(row.authorizer_name_enc, _name_aad(row.campus_id, row.id))["name"]


async def require_authorized(db, campus_id: str) -> None:
    """Raise the 403 unless storing learner data for this campus is authorized.

    Fails closed: an unreadable notice file or any lookup error refuses."""
    try:
        ok = await is_authorized(db, campus_id)
    except Exception:
        ok = False
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "school_authorization_required",
                "message": (
                    "A school official has not yet authorized Bede to store student "
                    "information for this campus. Nothing is stored until they do."
                ),
                "authorize_path": authorize_path(campus_id),
            },
        )
