"""Encrypted storage for the Practice Coach (practice_assessments, practice_sets).

Same shape as services/assessment_interop.py: per-student key, AAD bound to
table/column/student, and a tampered or unreadable row is treated as absent
rather than surfaced. Every lookup is scoped to the student in the URL, so an
id belonging to another child answers exactly like an id that does not exist.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from models.practice import GradedAssessment, PracticeSet


def _aad(table: str, student_name: str) -> bytes:
    from core.encryption import student_aad
    return student_aad(table, "detail_enc", student_name)


async def _require_student(db, student_name: str) -> bytes:
    from core import student_keys
    from core.database import StudentConfig

    if await db.get(StudentConfig, student_name) is None:
        raise LookupError("Student not found")
    return await student_keys.get_or_create(db, student_name)


async def save_assessment(db, student_name: str, assessment: GradedAssessment, status: str) -> int:
    from core.database import PracticeAssessment
    from core.encryption import encrypt_json

    key = await _require_student(db, student_name)
    row = PracticeAssessment(
        student_name=student_name,
        subject=assessment.subject,
        status=status,
        detail_enc=encrypt_json(assessment.model_dump(mode="json"), _aad("practice_assessments", student_name), key),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row.id


async def load_assessment(db, student_name: str, record_id: int) -> Optional[tuple[object, GradedAssessment]]:
    from core import student_keys
    from core.database import PracticeAssessment
    from core.encryption import decrypt_json

    row = (await db.execute(
        select(PracticeAssessment).where(
            PracticeAssessment.id == record_id, PracticeAssessment.student_name == student_name,
        )
    )).scalar_one_or_none()
    if row is None:
        return None
    try:
        key = await student_keys.get_existing(db, student_name)
        detail = decrypt_json(row.detail_enc, _aad("practice_assessments", student_name), key)
        return row, GradedAssessment.model_validate(detail)
    except Exception:
        return None


async def replace_assessment(db, row, assessment: GradedAssessment, status: str) -> None:
    from core import student_keys
    from core.encryption import encrypt_json

    key = await student_keys.get_existing(db, row.student_name)
    row.detail_enc = encrypt_json(assessment.model_dump(mode="json"), _aad("practice_assessments", row.student_name), key)
    row.subject = assessment.subject
    row.status = status
    await db.commit()


async def save_set(db, student_name: str, assessment_id: int, practice: PracticeSet, summary: str) -> int:
    from core.database import PracticeSetRecord
    from core.encryption import encrypt_json

    key = await _require_student(db, student_name)
    row = PracticeSetRecord(
        student_name=student_name,
        assessment_id=assessment_id,
        status="draft",
        detail_enc=encrypt_json(
            {"practice_set": practice.model_dump(mode="json"), "summary": summary},
            _aad("practice_sets", student_name), key,
        ),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row.id


async def load_set(db, student_name: str, set_id: int) -> Optional[tuple[object, dict]]:
    from core import student_keys
    from core.database import PracticeSetRecord
    from core.encryption import decrypt_json

    row = (await db.execute(
        select(PracticeSetRecord).where(
            PracticeSetRecord.id == set_id, PracticeSetRecord.student_name == student_name,
        )
    )).scalar_one_or_none()
    if row is None:
        return None
    try:
        key = await student_keys.get_existing(db, student_name)
        detail = decrypt_json(row.detail_enc, _aad("practice_sets", student_name), key)
        PracticeSet.model_validate(detail["practice_set"])
        return row, detail
    except Exception:
        return None


async def decide_set(db, row, status: str, practice: Optional[PracticeSet] = None, summary: str = "") -> None:
    from core import student_keys
    from core.encryption import encrypt_json

    if practice is not None:
        key = await student_keys.get_existing(db, row.student_name)
        row.detail_enc = encrypt_json(
            {"practice_set": practice.model_dump(mode="json"), "summary": summary},
            _aad("practice_sets", row.student_name), key,
        )
    row.status = status
    row.decided_at = datetime.now(timezone.utc)
    await db.commit()


async def list_sets(db, student_name: str, status: Optional[str] = None) -> list[dict]:
    from core import student_keys
    from core.database import PracticeSetRecord
    from core.encryption import decrypt_json

    query = select(PracticeSetRecord).where(PracticeSetRecord.student_name == student_name)
    if status:
        query = query.where(PracticeSetRecord.status == status)
    rows = (await db.execute(query.order_by(PracticeSetRecord.id.desc()).limit(50))).scalars().all()
    if not rows:
        return []
    key = await student_keys.get_existing(db, student_name)
    out = []
    for row in rows:
        try:
            detail = decrypt_json(row.detail_enc, _aad("practice_sets", student_name), key)
            out.append({"id": row.id, "assessment_id": row.assessment_id, "status": row.status, **detail})
        except Exception:
            continue
    return out
