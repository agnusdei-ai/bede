"""Official, educator-controlled assessment capture for the Valor teacher review cycle.

This is source transcription, NOT automated DIBELS scoring, a licensed test
form, or an interpretation of benchmark cut points. Existing canonical
assessment lifecycle transitions remain the authority for finalization.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

DibelsMeasure = Literal[
    "LNF", "PSF", "NWF", "NWF_CLS", "NWF_WRC", "WRF",
    "ORF", "ORF_WC", "ORF_ACCURACY", "MAZE", "COMPOSITE",
]
Instrument = Literal[
    "DIBELS_8", "TEACHER_OBSERVATION", "CURRICULUM_BASED_MEASURE", "OTHER",
]
Purpose = Literal[
    "benchmark", "progress_monitoring", "instructional_check", "teacher_observation",
]
Status = Literal[
    "not_started", "in_progress", "completed_pending_review", "finalized",
    "interrupted", "invalid", "voided", "skipped", "not_applicable",
]

class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class TenantScope(StrictRecord):
    campus_id: str = Field(min_length=3, max_length=100)
    educator_id: str = Field(min_length=3, max_length=100)
    learner_ids: list[str] = Field(min_length=1, max_length=90)
    grade_band: Literal["K-2", "3-5", "6-8", "mixed"] | None = None
    subject_area: str = Field(min_length=1, max_length=100)
    class_section_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def distinct_learners(self):
        if len(set(self.learner_ids)) != len(self.learner_ids):
            raise ValueError("Duplicate learner IDs are not allowed")
        return self


class OfficialAssessmentRecord(StrictRecord):
    record_id: UUID
    instrument: Instrument
    measure: str = Field(min_length=1, max_length=90)
    purpose: Purpose
    benchmark_window: Literal["BOY", "MOY", "EOY", "not_applicable"] = "not_applicable"
    valor_data_day_cycle: Literal[
        "valor_q1", "valor_q2", "valor_q3", "valor_q4", "not_applicable",
    ] = "not_applicable"
    administration_date: date
    administration_status: Status
    # Exact educator-entered external values, not machine-created benchmarks.
    official_score_fields: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict, max_length=40
    )
    accommodation_note: str = Field(default="", max_length=1000)
    administration_fidelity_note: str = Field(default="", max_length=1000)
    source_ref: str | None = Field(default=None, max_length=256)
    finalized_by: str | None = None
    finalized_at: datetime | None = None

    @model_validator(mode="after")
    def check_official_record(self):
        if self.instrument == "DIBELS_8":
            from services.assessment_interop import DIBELS_MEASURES
            # NWF and ORF are display-level umbrella terms. Persist the
            # precise reported submeasure instead of collapsing distinct units.
            if self.measure not in DIBELS_MEASURES:
                raise ValueError("Use a specific supported DIBELS 8 measure code")
            if self.purpose not in ("benchmark", "progress_monitoring"):
                raise ValueError("DIBELS requires benchmark or progress-monitoring purpose")
            if self.purpose == "benchmark" and self.benchmark_window == "not_applicable":
                raise ValueError("Benchmark requires a reported BOY/MOY/EOY window")
            if self.purpose == "progress_monitoring" and self.benchmark_window != "not_applicable":
                raise ValueError("Progress monitoring cannot be labeled as a benchmark window")
        else:
            if self.measure in ("LNF", "PSF", "NWF", "NWF_CLS", "NWF_WRC",
                                "WRF", "ORF", "ORF_WC", "ORF_ACCURACY",
                                "MAZE", "COMPOSITE"):
                raise ValueError("Non-DIBELS evidence cannot claim an official DIBELS measure")
            if self.purpose in ("benchmark", "progress_monitoring") and self.instrument == "TEACHER_OBSERVATION":
                raise ValueError("Teacher observation is not an official DIBELS score")
            if self.benchmark_window != "not_applicable":
                raise ValueError("Non-DIBELS records do not have a DIBELS benchmark window")
        if self.administration_status == "finalized":
            if not self.finalized_by or not self.finalized_at:
                raise ValueError("Finalization requires an identified teacher and timestamp")
            if self.instrument == "DIBELS_8" and not self.official_score_fields:
                raise ValueError("Finalized DIBELS entry requires a reported score record")
        elif self.finalized_by is not None or self.finalized_at is not None:
            raise ValueError("Unfinalized records must not claim teacher finalization")
        return self


class RawInput(StrictRecord):
    input_id: UUID
    input_type: Literal[
        "official_score_entry", "teacher_voice_note", "written_observation",
        "pacing_guide", "student_work_summary", "conference_note",
    ]
    summary: str = Field(min_length=1, max_length=2500)
    source_ref: str | None = Field(default=None, max_length=256)
