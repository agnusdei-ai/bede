"""
Parent review and export of everything held about one child (COPPA 312.6(a)(1)).

Walks services/student_deletion.py's student_scoped_models() list, so the
export cannot cover fewer tables than deletion removes. Every encrypted
column is decrypted with the same AAD its writer used. A row that cannot be
decrypted is reported as unreadable rather than dropped or failing the whole
export, so a parent sees that something is there.

Deliberately withheld from the export:
- voice_profiles.profile_enc. It is a voiceprint embedding, not a record a
  parent reads. Returning it would copy a biometric template out of the
  store for no review purpose. The row is listed with its date and marked
  withheld, so the parent still sees that it exists.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable

from sqlalchemy import select

from core import student_keys
from core.encryption import decrypt_json, student_aad

WITHHELD = "withheld: biometric template, not exported"


def _enc_aads() -> dict[str, dict[str, Callable[[Any], bytes | None]]]:
    """table label -> encrypted column -> function(row) returning its AAD.

    Each AAD mirrors the write site. A new encrypted column on a per-student
    table needs an entry here; the test in tests/test_student_export.py fails
    if a table in the deletion cascade has no entry at all.
    """
    return {
        "student_config": {
            "config_enc": lambda r: student_aad("student_configs", "config_enc", r.student_name),
        },
        "voice_profile": {"profile_enc": None},  # withheld, see module docstring
        "narration_assessments": {
            "assessment_enc": lambda r: student_aad("narration_assessments", "assessment_enc", r.student_name),
        },
        "learner_profile": {
            "profile_enc": lambda r: student_aad("learner_profiles", "profile_enc", r.student_name),
        },
        "learner_behavior_check": {
            "count_enc": lambda r: student_aad("learner_behavior_checks", "count_enc", r.student_name),
        },
        "lesson_bookmarks": {
            "bookmark_enc": lambda r: student_aad("lesson_bookmarks", "bookmark_enc", r.student_name, r.subject),
        },
        "mastery_profiles": {
            "profile_enc": lambda r: student_aad("mastery_profiles", "profile_enc", r.student_name, r.subject_area),
        },
        "diagnostic_evidence_log": {
            "delta_enc": lambda r: student_aad("diagnostic_evidence_log", "delta_enc", r.student_name),
        },
        "skill_activity_log": {
            "detail_enc": lambda r: student_aad(
                "skill_activity_log", "detail_enc", r.student_name, r.subject_area, r.skill_id
            ),
        },
        "adaptive_instruction_traces": {
            "detail_enc": lambda r: student_aad("adaptive_instruction_traces", "detail_enc", r.student_name),
        },
        "educator_assessment_evidence": {
            "detail_enc": lambda r: student_aad("educator_assessment_evidence", "detail_enc", r.student_name),
        },
        "practice_assessments": {
            "detail_enc": lambda r: student_aad("practice_assessments", "detail_enc", r.student_name),
        },
        "practice_sets": {
            "detail_enc": lambda r: student_aad("practice_sets", "detail_enc", r.student_name),
        },
        "educator_roster_assignments": {},
        "session_transcripts": {
            "transcript_enc": lambda r: student_aad("session_transcripts", "transcript_enc", r.student_name),
        },
        "api_usage_events": {},
        "consent_records": {
            "parent_label_enc": lambda r: student_aad("consent_records", "parent_label_enc", r.student_name),
            "revocation_reason_enc": lambda r: student_aad(
                "consent_records", "revocation_reason_enc", r.student_name
            ),
        },
        "student_collection_state": {},
    }


def _plain(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _render_row(row, label: str, encrypted: dict, key: bytes | None) -> dict:
    out: dict[str, Any] = {}
    for column in row.__table__.columns:
        name = column.name
        if name in encrypted:
            continue
        out[name] = _plain(getattr(row, name))

    for column, aad_for in encrypted.items():
        blob = getattr(row, column, None)
        if aad_for is None:
            out[column] = WITHHELD
            continue
        if blob is None:
            out[column] = None
            continue
        try:
            out[column] = decrypt_json(blob, aad_for(row), key)
        except Exception:  # noqa: BLE001 — an unreadable row must not fail the whole export
            out[column] = {"unreadable": True}
    return out


async def export_student(db, student_name: str) -> dict:
    """Every per-student table, decrypted for the parent. Holds no logs or other families' data.

    Returns {"student_name": ..., "tables": {label: [rows]}, "counts": {label: n}}.
    The key is read with get_existing, never created, so an export cannot
    write a key row for a student who has none.
    """
    from services.student_deletion import student_scoped_models

    aads = _enc_aads()
    key = await student_keys.get_existing(db, student_name)
    tables: dict[str, list] = {}
    for label, model in student_scoped_models():
        if label not in aads:
            raise RuntimeError(f"student export has no entry for table {label!r}")
        rows = (
            await db.execute(select(model).where(model.student_name == student_name))
        ).scalars().all()
        tables[label] = [_render_row(row, label, aads[label], key) for row in rows]
    return {
        "student_name": student_name,
        "tables": tables,
        "counts": {label: len(rows) for label, rows in tables.items()},
    }
