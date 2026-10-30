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

DEFAULT IS CLOSED. With no active consent record and no pause row, a
collection route refuses (403 parental_consent_required). There is no
deployment-wide bypass in this change. A bypass would need its own config
setting plumbed through docker-compose.yml, and that is a decision for the
operator, not a shortcut for development.

NOTICE. The text a parent is shown is NOTICE_TEXT, identified by
NOTICE_VERSION. A grant must present the hash of the current notice; a stale
client gets 409 notice_changed and must show the parent the current text
again. The hash is stored on the consent record, so the exact text a parent
agreed to can be recomputed later from this module's history.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select

from core import student_keys
from core.encryption import encrypt_json, student_aad

NOTICE_VERSION = "2026-10-29.1"

NOTICE_TEXT = """Bede keeps records about your child so that tutoring can continue from one session to the next.

What is collected about your child:
- The name you enter, their grade, and the subjects and lesson settings you choose.
- What your child types or says to Bede during a lesson, and Bede's replies.
- Narration assessments, a learner profile, mastery and skill-practice records, and lesson bookmarks that Bede writes from those lessons.
- Voice recordings your child makes are sent for speech-to-text. A voiceprint is kept only if you enroll your child's voice.
- Usage counts for the AI service.

Who receives it:
- The AI model provider and speech services your household has configured. On a self-hosted deployment, this can be a model that runs entirely on your own computer, so nothing leaves your home.

What you can do at any time:
- Review everything held about your child.
- Export a copy of it.
- Pause collection for your child. Lessons stop recording until you resume.
- Withdraw this consent. This stops further collection. It does not delete existing records.
- Delete your child's records. Deletion removes them and destroys the key that protects them.

By continuing, you confirm you are your child's parent or legal guardian and agree that Bede may collect and use the information described above for your child's tutoring.
"""


def notice_hash() -> str:
    """SHA-256 over the version and the full notice text.

    Both are hashed so that editing the text without bumping the version
    still changes the hash, and bumping the version alone also does.
    """
    material = f"{NOTICE_VERSION}\n{NOTICE_TEXT}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


@dataclass(frozen=True)
class ConsentMethod:
    id: str
    label: str
    # wired=False means the method is named but refused. It exists so the
    # list shows the operator and counsel the option, and so the refusal is
    # a deliberate act and not a missing row.
    wired: bool


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


async def require_collection(db, student_name: str) -> None:
    """Raise unless collecting from this student is currently permitted.

    Called by every collection route before it stores anything about the
    child. Refusal order: no consent first (403), then a pause (423). A paused
    student without consent is refused as unconsented, since that is the more
    basic fact.
    """
    if await active_record(db, student_name) is None:
        _log_refusal(student_name, "no_consent")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "parental_consent_required",
                "message": (
                    "A parent has not yet given consent to collect this student's "
                    "information. Bede does not record a child's lessons until they do."
                ),
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
    if not spec.wired:
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
