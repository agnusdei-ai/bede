"""Educator-supplied assessment evidence, deliberately separate from Bede's diagnostics.

DIBELS® is a University of Oregon trademark. Bede does NOT administer or
score DIBELS assessments, import test forms, calculate benchmarks, or
incorporate externally entered results into diagnostic mastery probabilities.
A trained educator uses the licensed/official materials independently,
then optionally records the result as reported.

Classical formative observations are factual work records, not grades of
character, spirituality, curiosity, virtue, or learner aptitude.

This module is the bounded, versioned interoperability foundation for the
Teaching Desk. External frameworks can be added with new approved registry
entries, never with agent-generated scoring rubrics or inferred thresholds.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

DIBELS_MEASURES = frozenset({
    "LNF", "PSF", "NWF_CLS", "NWF_WRC", "WRF",
    "ORF_WC", "ORF_ACCURACY", "MAZE", "COMPOSITE",
})
CLASSICAL_MEASURES = frozenset({
    "oral_narration", "oral_examination", "composition",
    "translation", "observation", "applied_work",
})
DIBELS_UNITS = {
    **{measure: "correct_per_minute" for measure in (
        "LNF", "PSF", "NWF_CLS", "NWF_WRC", "WRF", "ORF_WC"
    )},
    "ORF_ACCURACY": "percent",
    "MAZE": "points",
    "COMPOSITE": "points",
}
DIBELS_GRADES = frozenset({"K", "1", "2", "3", "4", "5", "6", "7", "8"})
DIBELS_WINDOWS = frozenset({
    "beginning_of_year", "middle_of_year", "end_of_year", "progress_monitoring",
})
OFFICIAL_RISK_BANDS = frozenset({
    "core_negligible_risk", "core_minimal_risk",
    "strategic_some_risk", "intensive_at_risk", "not_reported",
})

Framework = Literal["dibels8", "classical", "external_other"]
Assistance = Literal["unaided", "with_a_hint", "with_help"]
ReportedBand = Literal[
    "at_or_above_benchmark", "below_benchmark",
    "well_below_benchmark", "not_reported",
    # University of Oregon DIBELS 8 color / instructional-support categories.
    # Older generic labels remain valid for *reading* existing records.
    "core_negligible_risk", "core_minimal_risk",
    "strategic_some_risk", "intensive_at_risk",
]
ScoreUnit = Literal["count", "correct_per_minute", "percent", "points", "other"]


class EducatorAssessmentInput(BaseModel):
    """Strict input contract: no child answer or raw test material allowed."""

    model_config = ConfigDict(extra="forbid")

    framework: Framework
    measure: str = Field(min_length=1, max_length=85)
    assessed_on: date
    source_name: str = Field(min_length=2, max_length=120)
    score: Optional[float] = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)
    score_unit: Optional[ScoreUnit] = None
    reported_band: Optional[ReportedBand] = None
    assistance: Optional[Assistance] = None
    # Optional in the reader to preserve educator-entered records created
    # before the grade/assessment-window capture was supported.
    assessed_grade: Optional[Literal["K", "1", "2", "3", "4", "5", "6", "7", "8"]] = None
    assessment_window: Optional[Literal[
        "beginning_of_year", "middle_of_year", "end_of_year", "progress_monitoring",
    ]] = None

    @model_validator(mode="after")
    def check_framework_contract(self):
        if self.assessed_on > datetime.now(timezone.utc).date():
            raise ValueError("Assessment date must not be in the future")
        if self.framework == "dibels8":
            if self.measure not in DIBELS_MEASURES:
                raise ValueError("Unsupported DIBELS 8th Edition measure")
            if self.score is None or self.score_unit is None:
                raise ValueError("Enter both the reported score and its unit")
            if self.assistance is not None:
                raise ValueError("Assistance labels do not apply to DIBELS records")
        elif self.framework == "classical":
            if self.measure not in CLASSICAL_MEASURES:
                raise ValueError("Unsupported classical observation type")
            if self.assistance is None:
                raise ValueError("Record only the factual assistance observed")
            if self.score is not None or self.score_unit is not None or self.reported_band is not None:
                raise ValueError("Classical observations do not use external scores or benchmarks")
        else:
            if self.score is None or self.score_unit is None:
                raise ValueError("Enter both the externally reported score and its unit")
            if self.assistance is not None or self.reported_band is not None:
                raise ValueError("Unsupported interpretation for an unregistered external framework")
        return self


class EducatorAssessmentSubmission(EducatorAssessmentInput):
    """Stricter new-write contract; old encrypted records remain readable."""

    @model_validator(mode="after")
    def check_report_fidelity(self):
        if self.framework == "dibels8":
            if self.assessed_grade is None or self.assessment_window is None:
                raise ValueError("DIBELS entries require reported grade and testing window")
            if self.score_unit != DIBELS_UNITS[self.measure]:
                raise ValueError("Reported score unit does not match the selected DIBELS measure")
            if self.reported_band is not None and self.reported_band not in OFFICIAL_RISK_BANDS:
                raise ValueError("Use official DIBELS risk categories from the source report")
        if self.score_unit == "percent" and self.score is not None and self.score > 100:
            raise ValueError("Percentage cannot exceed 100")
        return self


def _aad(student_name: str) -> bytes:
    from core.encryption import student_aad
    return student_aad("educator_assessment_evidence", "detail_enc", student_name)


def _render(row, record: dict) -> dict:
    quality_flags = []
    if record["framework"] == "dibels8":
        if not record.get("assessed_grade"):
            quality_flags.append("missing_assessed_grade")
        if not record.get("assessment_window"):
            quality_flags.append("missing_assessment_window")
        if record.get("score_unit") != DIBELS_UNITS.get(record["measure"]):
            quality_flags.append("review_reported_unit")
        if record.get("reported_band") and record["reported_band"] not in OFFICIAL_RISK_BANDS:
            quality_flags.append("legacy_benchmark_label")
    if record.get("score_unit") == "percent" and record.get("score") is not None:
        if record["score"] > 100:
            quality_flags.append("reported_percent_out_of_range")
    return {
        "quality_flags": quality_flags,
        "id": row.id,
        "student_name": row.student_name,
        "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat()
        if row.created_at.tzinfo is None else row.created_at.isoformat(),
        **record,
        "record_status": "educator_entered_unverified",
    }


async def record_assessment(db, student_name: str, entry: EducatorAssessmentInput) -> dict:
    # Validate even on direct service invocation, not only via the HTTP API.
    # Do not rewrite or delete older, legitimately recorded family evidence.
    entry = EducatorAssessmentSubmission.model_validate(entry.model_dump(mode="json"))
    from core import student_keys
    from core.database import StudentConfig, EducatorAssessmentEvidence
    from core.encryption import encrypt_json

    # Reject typos or fabricated student records. Caller enforces parent auth.
    if await db.get(StudentConfig, student_name) is None:
        raise LookupError("Student not found")
    key = await student_keys.get_or_create(db, student_name)
    detail = entry.model_dump(mode="json")
    row = EducatorAssessmentEvidence(
        student_name=student_name,
        framework=entry.framework,
        detail_enc=encrypt_json(detail, _aad(student_name), key),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _render(row, detail)


async def list_assessments(db, student_name: str, *, limit: int = 60) -> list[dict]:
    from sqlalchemy import select
    from core import student_keys
    from core.database import EducatorAssessmentEvidence
    from core.encryption import decrypt_json

    rows = (await db.execute(
        select(EducatorAssessmentEvidence)
        .where(EducatorAssessmentEvidence.student_name == student_name)
        .order_by(EducatorAssessmentEvidence.id.desc())
        .limit(min(max(limit, 1), 100))
    )).scalars().all()
    if not rows:
        return []
    key = await student_keys.get_existing(db, student_name)
    results = []
    for row in rows:
        try:
            detail = decrypt_json(row.detail_enc, _aad(student_name), key)
            if not isinstance(detail, dict) or detail.get("framework") != row.framework:
                continue
            # All persisted details must satisfy today's same strictly
            # bounded input contract. Invalid/tampered records aren't data.
            record = EducatorAssessmentInput.model_validate(detail)
            results.append(_render(row, record.model_dump(mode="json")))
        except Exception:
            continue
    return results


async def delete_assessment(db, student_name: str, record_id: int) -> bool:
    from sqlalchemy import delete
    from core.database import EducatorAssessmentEvidence

    result = await db.execute(
        delete(EducatorAssessmentEvidence).where(
            EducatorAssessmentEvidence.id == record_id,
            EducatorAssessmentEvidence.student_name == student_name,
        )
    )
    await db.commit()
    return bool(result.rowcount)


def frameworks_catalog() -> list[dict]:
    """Capabilities of the *interoperability UI*, not assessment endorsements."""
    return [
        {
            "id": "dibels8",
            "label": "DIBELS 8th Edition",
            "kind": "external_standardized",
            "supported_measures": sorted(DIBELS_MEASURES),
            "measure_units": DIBELS_UNITS,
            "grades": sorted(DIBELS_GRADES),
            "windows": sorted(DIBELS_WINDOWS),
            "reported_bands": sorted(OFFICIAL_RISK_BANDS),
            "administration": "external_only",
            "interpretation": "educator_supplied_only",
        },
        {
            "id": "classical",
            "label": "Classical formative observations",
            "kind": "observed_academic_work",
            "supported_measures": sorted(CLASSICAL_MEASURES),
            "administration": "instructor_observation",
            "interpretation": "assistance_record_only",
        },
        {
            "id": "external_other",
            "label": "Other external assessment",
            "kind": "external_standardized",
            "supported_measures": [],
            "administration": "external_only",
            "interpretation": "reported_score_only",
        },
    ]
