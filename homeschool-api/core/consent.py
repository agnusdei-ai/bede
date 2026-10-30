"""
Parental consent, the collection gate, and the per-child collection pause.

WHAT THIS IS. The control COPPA 16 CFR 312.5 asks for, as code: no personal
information about a child is collected until a parent has given consent that
is recorded, and a parent can pause collection for one child (312.6(a)(2))
without deleting anything. Every collection route calls require_collection()
before it touches the child's data. Consent and the pause are per student,
live in the database, and are audited.

WHAT THIS IS NOT. Whether a consent METHOD is verifiable parental consent
under the Rule is a question for counsel, not for this module. METHODS below
names the methods the product knows about and says which are wired. The
self-hosted default records an attestation by the parent, which is the
weakest method and is recorded as exactly that. The payment-transaction
method is a placeholder: it is listed so that its absence cannot be mistaken
for a decision, and it is refused until someone wires it to a real payment
flow and counsel has approved that flow. Nothing here decides sufficiency.

DEFAULT IS CLOSED. A student with no active consent record is refused (403
parental_consent_required), with two ways to be covered: a parent records
consent (per child, household-wide, or by the tick at pod save), or the
person who installed Bede acknowledged the family notice at install time
(CONSENT_INSTALL_ACK_HASH / CONSENT_INSTALL_ACK_AT). A valid install ack
covers a student only if that student has never had a consent record:
withdrawal is never undone by the ack. The first collection for a covered
student writes a ledger row (method install_custodian_attestation, dated at
the ack time). There is no mode and no grace period. Hosted or pilot
deployments never set the ack. The custodian wording is a draft for counsel.

A consent recorded against an older notice is STALE. Staleness only prompts
the parent (household status); it never blocks collection.

NOTICE. The text a parent is shown is NOTICE_TEXT, identified by
NOTICE_VERSION. A grant must present the hash of the current notice; a stale
client gets 409 notice_changed and must show the parent the current text
again. The hash is stored on the consent record, so the exact text a parent
agreed to can be recomputed later from this module's history.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select

from core import student_keys
from core.config import settings
from core.encryption import encrypt_json, student_aad

# The single source of truth, shared with the installers. Its first line is
# "Notice version: <X>". The hash is SHA-256 of the file's exact bytes, so
# setup.sh, the Python wizard and this module compute the same value.
NOTICE_PATH = Path(__file__).resolve().parents[1] / "data" / "consent_notice.txt"
_NOTICE_BYTES: bytes = NOTICE_PATH.read_bytes()


def _parse_version(raw: bytes) -> str:
    first = raw.decode("utf-8").splitlines()[0]
    prefix = "Notice version:"
    if not first.startswith(prefix):
        raise RuntimeError("consent_notice.txt must begin with 'Notice version: <X>'")
    return first[len(prefix):].strip()


NOTICE_VERSION = _parse_version(_NOTICE_BYTES)
NOTICE_TEXT = _NOTICE_BYTES.decode("utf-8")


def notice_hash() -> str:
    """Hex SHA-256 of the notice file's exact bytes."""
    return hashlib.sha256(_NOTICE_BYTES).hexdigest()


@dataclass(frozen=True)
class ConsentMethod:
    id: str
    label: str
    # wired=False means the method is named but refused. It exists so the
    # list shows the operator and counsel the option, and so the refusal is
    # a deliberate act and not a missing row.
    wired: bool
    # False for methods the product records itself and a client may not request.
    parent_selectable: bool = True


METHODS: dict[str, ConsentMethod] = {
    "parent_attested_checkbox": ConsentMethod(
        id="parent_attested_checkbox",
        label="Parent attests in the product that they consent",
        wired=True,
    ),
    "payment_transaction": ConsentMethod(
        id="payment_transaction",
        label="Consent verified by a payment transaction (not wired)",
        wired=False,
    ),
    "install_custodian_attestation": ConsentMethod(
        id="install_custodian_attestation",
        label="Operator and custodian acknowledged the notice at install time",
        wired=True,
        parent_selectable=False,
    ),
}

DEFAULT_METHOD = "parent_attested_checkbox"
SCOPE = "tutoring_and_records"


class ConsentError(Exception):
    """A refused consent operation, carrying the HTTP status and a stable code."""

    def __init__(self, http_status: int, code: str, message: str):
        super().__init__(message)
        self.http_status = http_status
        self.code = code
        self.message = message


def _label_aad(student_name: str) -> bytes:
    return student_aad("consent_records", "parent_label_enc", student_name)


def _reason_aad(student_name: str) -> bytes:
    return student_aad("consent_records", "revocation_reason_enc", student_name)


async def active_record(db, student_name: str):
    """The current, unrevoked consent for a student, or None."""
    from core.database import ConsentRecord

    result = await db.execute(
        select(ConsentRecord)
        .where(ConsentRecord.student_name == student_name, ConsentRecord.revoked_at.is_(None))
        .order_by(ConsentRecord.granted_at.desc(), ConsentRecord.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def pause_state(db, student_name: str):
    from core.database import StudentCollectionState

    return await db.get(StudentCollectionState, student_name)


async def is_paused(db, student_name: str) -> bool:
    state = await pause_state(db, student_name)
    return state is not None and state.paused_at is not None


def _log_refusal(student_name: str, reason: str) -> None:
    # Fire-and-forget, like every other hot-path audit write. No request is in
    # scope here, so the record carries the reason and the student only.
    from core.audit import AuditEvent, log_event_nowait

    log_event_nowait(
        AuditEvent.COLLECTION_REFUSED,
        role=None,
        student_name=student_name,
        detail=f"reason={reason}",
    )


INSTALL_ACK_METHOD = "install_custodian_attestation"
INSTALL_ACK_LABEL = "install-time custodian acknowledgement"
_ACK_FUTURE_TOLERANCE = timedelta(minutes=5)


def _now() -> datetime:
    """Clock seam so tests can move time without sleeping."""
    return datetime.now(timezone.utc)


def install_ack_time() -> Optional[datetime]:
    """The ack time if the install-time acknowledgement is valid, else None.

    Valid only when the hash equals the CURRENT notice hash (an ack of an
    older notice is not valid) and the time parses as a timezone-aware
    ISO-8601 value no more than five minutes in the future.
    """
    if settings.consent_install_ack_hash != notice_hash():
        return None
    raw = settings.consent_install_ack_at.strip()
    if not raw:
        return None
    try:
        at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if at.tzinfo is None:
        return None
    at = at.astimezone(timezone.utc)
    if at > _now() + _ACK_FUTURE_TOLERANCE:
        return None
    return at


async def _ever_had_consent(db, student_name: str) -> bool:
    from core.database import ConsentRecord

    result = await db.execute(
        select(ConsentRecord.id).where(ConsentRecord.student_name == student_name).limit(1)
    )
    return result.first() is not None


async def _record_from_install_ack(db, student_name: str, at: datetime):
    """Write the ledger row an install-time ack implies, once."""
    from core.database import ConsentRecord

    key = await student_keys.get_or_create(db, student_name)
    record = ConsentRecord(
        student_name=student_name,
        parent_label_enc=encrypt_json({"label": INSTALL_ACK_LABEL}, _label_aad(student_name), key),
        method=INSTALL_ACK_METHOD,
        notice_hash=notice_hash(),
        scope=SCOPE,
        granted_at=at,
    )
    db.add(record)
    await db.commit()
    from core.audit import AuditEvent, log_event_nowait

    log_event_nowait(
        AuditEvent.CONSENT_INSTALL_ACK_RECORDED,
        role=None,
        student_name=student_name,
        detail=f"method={INSTALL_ACK_METHOD} notice={notice_hash()[:12]}",
    )
    return record


async def require_collection(db, student_name: str) -> None:
    """Raise unless collecting from this student is currently permitted.

    Called by every collection route before it stores anything about the
    child. Refusal order: no consent first (403), then a pause (423). A valid
    install-time ack covers a student with NO consent record at all (a revoked
    one still counts as having had one), by lazily writing a ledger row.
    """
    if await active_record(db, student_name) is None:
        at = install_ack_time()
        if at is not None and not await _ever_had_consent(db, student_name):
            await _record_from_install_ack(db, student_name, at)
        else:
            _log_refusal(student_name, "no_consent")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "parental_consent_required",
                    "message": (
                        "A parent has not yet given consent to collect this student's "
                        "information. Bede does not record a child's lessons until they do."
                    ),
                    "parent_action": "open_parent_setup",
                },
            )
    if await is_paused(db, student_name):
        _log_refusal(student_name, "paused")
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail={
                "error": "collection_paused",
                "message": (
                    "A parent has paused collection for this student. Lessons are not "
                    "recorded until the parent resumes it."
                ),
            },
        )


async def grant(
    db,
    student_name: str,
    *,
    parent_label: str,
    method: str,
    presented_notice_hash: str,
):
    """Record a parent's consent. Returns (record, created).

    Idempotent while a consent is active: a second grant returns the existing
    record and does not change its method or notice. To change either, revoke
    first. That keeps the ledger a record of what was agreed to, not the
    latest click.
    """
    from core.database import ConsentRecord

    spec = METHODS.get(method)
    if spec is None:
        raise ConsentError(422, "unknown_method", f"Unknown consent method {method!r}.")
    if not spec.wired or not spec.parent_selectable:
        raise ConsentError(
            422,
            "method_not_available",
            f"Consent method {method!r} is not available on this deployment.",
        )
    if presented_notice_hash != notice_hash():
        raise ConsentError(
            409,
            "notice_changed",
            "The privacy notice has changed since it was shown. Show the current notice and try again.",
        )

    existing = await active_record(db, student_name)
    if existing is not None:
        return existing, False

    key = await student_keys.get_or_create(db, student_name)
    record = ConsentRecord(
        student_name=student_name,
        parent_label_enc=encrypt_json({"label": parent_label}, _label_aad(student_name), key),
        method=method,
        notice_hash=notice_hash(),
        scope=SCOPE,
        granted_at=datetime.now(timezone.utc),
    )
    db.add(record)
    await db.commit()
    return record, True


async def revoke(db, student_name: str, *, reason: Optional[str]):
    """Withdraw the active consent. Returns the revoked record, or None if none was active.

    Revocation stops further collection (require_collection refuses from now
    on). It deletes nothing. Deletion is a separate act.
    """
    record = await active_record(db, student_name)
    if record is None:
        return None
    record.revoked_at = datetime.now(timezone.utc)
    if reason:
        key = await student_keys.get_or_create(db, student_name)
        record.revocation_reason_enc = encrypt_json({"reason": reason}, _reason_aad(student_name), key)
    await db.commit()
    return record


async def set_paused(db, student_name: str, *, paused: bool) -> Optional[datetime]:
    """Pause or resume collection for one student. Returns paused_at (None when resumed)."""
    from core.database import StudentCollectionState

    state = await pause_state(db, student_name)
    now = datetime.now(timezone.utc)
    if state is None:
        state = StudentCollectionState(student_name=student_name)
        db.add(state)
    state.paused_at = now if paused else None
    state.updated_at = now
    await db.commit()
    return state.paused_at


async def status_for(db, student_name: str) -> dict:
    """Parent-visible consent and pause status. Holds no child content."""
    record = await active_record(db, student_name)
    paused = await is_paused(db, student_name)
    return {
        "student_consented": record is not None,
        "method": record.method if record else None,
        "notice_version": NOTICE_VERSION,
        "granted_at": record.granted_at.isoformat() if record else None,
        "collection_paused": paused,
        "current_notice_hash": notice_hash(),
    }


async def ensure_consent(
    db,
    student_names: list[str],
    *,
    parent_label: str,
    presented_notice_hash: str,
    method: str = DEFAULT_METHOD,
) -> dict:
    """Record consent for each named student against the current notice.

    Returns {granted, already, refreshed}. A student with no active consent is
    granted; one whose active consent is against an older notice is revoked
    (reason recorded) and granted afresh, so the ledger keeps both rows rather
    than rewriting one; one already current is left alone. Idempotent.
    Raises ConsentError 409 notice_changed before touching anything if the
    presented hash is not the current one.
    """
    if presented_notice_hash != notice_hash():
        raise ConsentError(
            409,
            "notice_changed",
            "The privacy notice has changed since it was shown. Show the current notice and try again.",
        )
    out: dict = {"granted": [], "already": [], "refreshed": []}
    for name in dict.fromkeys(student_names):
        current = await active_record(db, name)
        if current is None:
            await grant(db, name, parent_label=parent_label, method=method,
                        presented_notice_hash=presented_notice_hash)
            out["granted"].append(name)
        elif current.notice_hash != notice_hash():
            await revoke(db, name, reason="superseded by a newer privacy notice")
            await grant(db, name, parent_label=parent_label, method=method,
                        presented_notice_hash=presented_notice_hash)
            out["refreshed"].append(name)
        else:
            out["already"].append(name)
    return out


async def household_status(db) -> dict:
    """Parent-visible household consent picture. Holds no child content."""
    from core.database import StudentConfig

    names = [r[0] for r in (await db.execute(
        select(StudentConfig.student_name).order_by(StudentConfig.student_name)
    )).all()]
    students = []
    current_hash = notice_hash()
    ack_valid = install_ack_time() is not None
    for name in names:
        rec = await active_record(db, name)
        covered = rec is None and ack_valid and not await _ever_had_consent(db, name)
        students.append({
            "student_name": name,
            "consented": rec is not None or covered,
            "stale": rec is not None and rec.notice_hash != current_hash,
        })
    return {
        "needs_consent": any((not s["consented"]) or s["stale"] for s in students),
        "install_ack": ack_valid,
        "notice_hash": current_hash,
        "notice_version": NOTICE_VERSION,
        "notice_text": NOTICE_TEXT,
        "students": students,
    }
