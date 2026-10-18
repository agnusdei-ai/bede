"""Canonical assessment contracts and pure helpers (no I/O).

Input models, the instructional-review calendar, the snapshot hash, growth,
error patterns and Bede's proposal policy. The router
(``routers/pilot_assessments.py``) owns authorization and persistence; this
module owns the semantics, so each rule is testable by stating a situation.

Standing boundaries, each asserted in ``tests/test_canonical_assessment_api.py``:

* Official administration/scoring is transcribed, never generated. No
  DIBELS norm table, cut-point table or band calculation exists here. Cut
  points and band labels are stored exactly as printed on the source report.
* A measure that was not administered has no score. It is never 0 and
  never enters growth.
* Progress monitoring is never a benchmark: only ``benchmark`` purpose may
  carry an official benchmark window, and benchmark purpose needs a
  recorded per-campus authorization (enforced by the router).
* ``report_source``, ``official_benchmark_window`` and
  ``vendor_next_assessment_date`` are transcribed separately and never
  derived from ``instructional_cycle``.
* Vendor guidance is the vendor's, stored as ``vendor_guidance`` and never
  presented as a Bede recommendation or an approved action.
* Bede's proposal describes instruction, never the child, and proposes a
  review date only; a teacher confirms anything that is scheduled.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from services.assessment_interop import DIBELS_MEASURES, DIBELS_UNITS

POLICY_VERSION = "canonical-review-2026-10-16"

AdministrationPurpose = Literal[
    "benchmark", "progress_monitoring", "instructional_check", "teacher_observation",
]
OfficialWindow = Literal["BOY", "MOY", "EOY", "none"]
MeasureStatus = Literal[
    "scored", "not_administered_by_rule", "not_administered_other",
    "skipped", "not_applicable", "interrupted", "invalid", "voided",
]
Grade = Literal["K", "1", "2", "3", "4", "5", "6", "7", "8"]

#: The two label vocabularies a composite (or measure) may be printed with.
#: Both are stored exactly as printed; neither is computed from the other
#: or from a score.
BENCHMARK_LABELS = ("Well Below Benchmark", "Below Benchmark", "At Benchmark", "Above Benchmark")
SUPPORT_LABELS = ("Most Support", "Some Support", "Goal", "Above Goal")
BenchmarkLabel = Literal["Well Below Benchmark", "Below Benchmark", "At Benchmark", "Above Benchmark"]
SupportLabel = Literal["Most Support", "Some Support", "Goal", "Above Goal"]

CUT_POINT_PROVENANCE = "as printed on the source report"
VENDOR_ATTRIBUTION = "vendor guidance, as printed on the source report; not a Bede recommendation"

_SLUG = r"^[a-z0-9_]+$"


# ── Calendar ────────────────────────────────────────────────────────────────

VALOR_DEFAULT_CYCLES = (
    ("valor_q1", "Valor Q1 Data Day"),
    ("valor_q2", "Valor Q2 Data Day"),
    ("valor_q3", "Valor Q3 Data Day"),
    ("valor_q4", "Valor Q4 / year-end Data Day"),
)
#: About nine weeks between Valor Data Days.
VALOR_DATA_DAY_SPACING = timedelta(weeks=9)


@dataclass(frozen=True)
class Cycle:
    cycle_key: str
    label: str
    position: int
    data_day_on: Optional[date]


def valor_default_calendar(first_data_day: Optional[date] = None) -> list[Cycle]:
    """The Valor default: Q1..Q4 Data Days about nine weeks apart.

    Dates are only produced from a campus-supplied first Data Day; without
    one, the cycle keys exist with no dates rather than with invented ones.
    """
    return [
        Cycle(key, label, i,
              first_data_day + VALOR_DATA_DAY_SPACING * i if first_data_day else None)
        for i, (key, label) in enumerate(VALOR_DEFAULT_CYCLES)
    ]


class CycleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cycle_key: str = Field(min_length=2, max_length=32, pattern=_SLUG)
    label: str = Field(min_length=2, max_length=80)
    data_day_on: Optional[date] = None


class CalendarInput(BaseModel):
    """Either the Valor preset (optionally dated) or an explicit cycle list."""
    model_config = ConfigDict(extra="forbid")
    preset: Optional[Literal["valor_default"]] = None
    first_data_day: Optional[date] = None
    cycles: Optional[list[CycleInput]] = Field(default=None, min_length=1, max_length=12)

    @model_validator(mode="after")
    def _one_source(self):
        if (self.preset is None) == (self.cycles is None):
            raise ValueError("Give either preset='valor_default' or an explicit cycles list")
        if self.cycles is not None:
            keys = [c.cycle_key for c in self.cycles]
            if len(set(keys)) != len(keys):
                raise ValueError("Cycle keys must be unique")
            if self.first_data_day is not None:
                raise ValueError("first_data_day applies only to the Valor preset")
        return self

    def resolve(self) -> list[Cycle]:
        if self.preset == "valor_default":
            return valor_default_calendar(self.first_data_day)
        return [Cycle(c.cycle_key, c.label.strip(), i, c.data_day_on)
                for i, c in enumerate(self.cycles or [])]


def next_data_day(calendar: list[Cycle], cycle_key: str) -> Optional[Cycle]:
    """The campus's next cycle after ``cycle_key`` that has a Data Day date."""
    ordered = sorted(calendar, key=lambda c: c.position)
    after = False
    for c in ordered:
        if after and c.data_day_on is not None:
            return c
        if c.cycle_key == cycle_key:
            after = True
    return None


class BenchmarkAuthorizationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument: Literal["dibels8"]
    licensed_program_ref: str = Field(min_length=3, max_length=160)
    approved_forms: list[str] = Field(min_length=1, max_length=50)
    local_policy_ref: str = Field(min_length=3, max_length=160)
    attestation: Literal[
        "licensed program, approved forms and local policy permit benchmark administration"
    ]

    @field_validator("approved_forms")
    @classmethod
    def _forms(cls, v: list[str]) -> list[str]:
        cleaned = [f.strip() for f in v if f and f.strip()]
        if not cleaned or any(len(f) > 64 for f in cleaned):
            raise ValueError("Approved form identifiers must be 1-64 characters")
        return sorted(set(cleaned))


# ── Administration and scores ───────────────────────────────────────────────

class VendorGuidance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    support_areas: list[str] = Field(default_factory=list, max_length=12)
    home_activities: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("support_areas", "home_activities")
    @classmethod
    def _bounded(cls, v: list[str]) -> list[str]:
        out = [x.strip() for x in v if x and x.strip()]
        if any(len(x) > 300 for x in out):
            raise ValueError("Each guidance line must be 300 characters or fewer")
        return out


class AdministrationLog(BaseModel):
    """Publisher-neutral marks and timings, not proprietary assessment content."""
    model_config = ConfigDict(extra="forbid")
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    elapsed_seconds: Optional[int] = Field(default=None, ge=0, le=86400)
    last_item_attempted: Optional[int] = Field(default=None, ge=0, le=10000)
    correct_marks: Optional[int] = Field(default=None, ge=0, le=10000)
    error_marks: Optional[int] = Field(default=None, ge=0, le=10000)
    self_corrections: Optional[int] = Field(default=None, ge=0, le=10000)
    discontinue_rule_result: Literal["not_recorded", "met", "not_met", "not_applicable"] = "not_recorded"
    interrupted: bool = False
    interruption_note: Optional[str] = Field(default=None, max_length=500)
    administration_fidelity_note: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _times(self):
        if self.start_time is not None and self.end_time is not None:
            if (self.start_time.tzinfo is None) != (self.end_time.tzinfo is None):
                raise ValueError("Start and end must use the same timezone convention")
            if self.end_time < self.start_time:
                raise ValueError("End time precedes start time")
        if self.interrupted and not (self.interruption_note or "").strip():
            raise ValueError("Record the reason for an interruption")
        return self


class AdministrationLogUpdate(BaseModel):
    """A version-aware update before finalization, not a score recalculation."""
    model_config = ConfigDict(extra="forbid")
    expected_state: str = Field(min_length=2, max_length=40)
    administration_log: AdministrationLog


class AdministrationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument: Literal["dibels8"]
    edition: str = Field(min_length=1, max_length=32)
    measure: str = Field(min_length=2, max_length=32)
    grade: Grade
    form_id: str = Field(min_length=1, max_length=64)
    administration_purpose: AdministrationPurpose
    instructional_cycle: str = Field(min_length=2, max_length=32, pattern=_SLUG)
    administered_at: datetime
    report_source: str = Field(min_length=2, max_length=32, pattern=_SLUG)
    official_benchmark_window: OfficialWindow
    vendor_next_assessment_date: Optional[date] = None
    accommodations: list[str] = Field(default_factory=list, max_length=10)
    notes: Optional[str] = Field(default=None, max_length=1000)
    vendor_guidance: Optional[VendorGuidance] = None
    administration_log: Optional[AdministrationLog] = None

    @model_validator(mode="after")
    def _semantics(self):
        if self.measure != "multiple" and self.measure not in DIBELS_MEASURES:
            raise ValueError("Unsupported DIBELS 8th Edition measure")
        # Progress monitoring (or any non-benchmark purpose) is never a
        # benchmark, whatever cycle or Data Day it happens on.
        if self.administration_purpose != "benchmark" and self.official_benchmark_window != "none":
            raise ValueError("Only a benchmark administration carries an official benchmark window")
        if any(len(a) > 120 for a in self.accommodations):
            raise ValueError("Each accommodation must be 120 characters or fewer")
        return self

    def content(self) -> dict:
        """The encrypted part: accommodations, notes, vendor guidance."""
        return {
            "accommodations": [a.strip() for a in self.accommodations if a.strip()],
            "notes": (self.notes or "").strip() or None,
            "vendor_guidance": self.vendor_guidance.model_dump() if self.vendor_guidance else None,
            "administration_log": self.administration_log.model_dump(mode="json") if self.administration_log else None,
        }


class CutPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=60)
    value: float = Field(ge=0, le=100_000, allow_inf_nan=False)


class ScoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measure: str = Field(min_length=2, max_length=32)
    administration_status: MeasureStatus
    raw_score: Optional[float] = Field(default=None, ge=0, le=100_000, allow_inf_nan=False)
    score_unit: Optional[str] = None
    reason: Optional[str] = Field(default=None, max_length=300)
    benchmark_label: Optional[BenchmarkLabel] = None
    support_label: Optional[SupportLabel] = None
    printed_cut_points: list[CutPoint] = Field(default_factory=list, max_length=10)
    correct_count: Optional[int] = Field(default=None, ge=0, le=100000)
    error_count: Optional[int] = Field(default=None, ge=0, le=100000)
    accuracy_percent: Optional[float] = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    composite_eligibility: Literal["not_verified", "eligible_as_reported", "not_eligible"] = "not_verified"
    required_composite_measures: list[str] = Field(default_factory=list, max_length=12)
    teacher_reviewed: bool = False
    calculation_version: str = Field(default="as_printed_on_source_report",
                                     min_length=2, max_length=64)

    @model_validator(mode="after")
    def _semantics(self):
        if self.measure not in DIBELS_MEASURES:
            raise ValueError("Unsupported DIBELS 8th Edition measure")
        if self.composite_eligibility != "not_verified" and self.measure != "COMPOSITE":
            raise ValueError("Composite eligibility belongs only to a composite record")
        if self.measure != "COMPOSITE" and self.required_composite_measures:
            raise ValueError("Required composite measures belong only to a composite record")
        if any(m not in DIBELS_MEASURES or m == "COMPOSITE" for m in self.required_composite_measures):
            raise ValueError("Required composite measures must be recognized non-composite measures")
        if self.administration_status == "scored":
            if self.raw_score is None:
                raise ValueError("A scored measure needs its reported raw score")
            if self.score_unit != DIBELS_UNITS[self.measure]:
                raise ValueError("Reported score unit does not match the measure")
            if self.score_unit == "percent" and self.raw_score > 100:
                raise ValueError("Percentage cannot exceed 100")
        else:
            # Never zero, never a score: a skipped/invalid measure has none.
            if any(x is not None for x in (self.raw_score, self.score_unit,
                                          self.correct_count, self.error_count,
                                          self.accuracy_percent)):
                raise ValueError("A measure that was not scored has no numeric marks, not zero")
            if self.composite_eligibility == "eligible_as_reported":
                raise ValueError("An unscored composite cannot be eligible")
            if not (self.reason or "").strip():
                raise ValueError("Transcribe the reason the measure was not scored")
            if self.benchmark_label or self.support_label:
                raise ValueError("A measure that was not scored has no printed band")
        return self

    @property
    def is_composite(self) -> bool:
        return self.measure == "COMPOSITE"

    def detail(self) -> dict:
        return {
            "raw_score": self.raw_score, "score_unit": self.score_unit,
            "reason": (self.reason or "").strip() or None,
            "benchmark_label": self.benchmark_label, "support_label": self.support_label,
            "printed_cut_points": [c.model_dump() for c in self.printed_cut_points],
            "correct_count": self.correct_count, "error_count": self.error_count,
            "accuracy_percent": self.accuracy_percent,
            "composite_eligibility": self.composite_eligibility,
            "required_composite_measures": self.required_composite_measures,
            "teacher_reviewed": self.teacher_reviewed,
        }


class ResponseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    measure: str = Field(min_length=2, max_length=32)
    item_index: int = Field(ge=0, le=10_000)
    mark: str = Field(min_length=1, max_length=32)
    correct: bool
    error_type: Optional[str] = Field(default=None, max_length=40, pattern=_SLUG)
    annotation: Optional[str] = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _error_type_only_on_error(self):
        if self.correct and self.error_type:
            raise ValueError("An error type applies only to an incorrect response")
        return self


class ScoresSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scores: list[ScoreInput] = Field(min_length=1, max_length=20)
    responses: list[ResponseInput] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def _unique(self):
        measures = [s.measure for s in self.scores]
        if len(set(measures)) != len(measures):
            raise ValueError("Each measure appears at most once")
        items = [(r.measure, r.item_index) for r in self.responses]
        if len(set(items)) != len(items):
            raise ValueError("Each response item appears at most once")
        if not {r.measure for r in self.responses} <= set(measures):
            raise ValueError("Responses must belong to a submitted measure")
        scored_measures = {s.measure for s in self.scores if s.administration_status == "scored"}
        for score in self.scores:
            if score.is_composite and score.composite_eligibility == "eligible_as_reported":
                required = set(score.required_composite_measures)
                if not required or not required <= (scored_measures - {"COMPOSITE"}):
                    raise ValueError("Composite eligibility needs every listed applicable measure scored")
        return self


class TransitionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["mark_ready", "start", "interrupt", "resume", "invalidate",
                    "resolve_invalid", "submit", "finalize", "void"]
    expected_state: str = Field(min_length=2, max_length=40)
    resolution: Optional[str] = Field(default=None, max_length=500)


class TeacherObservation(BaseModel):
    """Separate teacher-authored interpretation; never an official score."""
    model_config = ConfigDict(extra="forbid")
    accuracy_fluency_notes: Optional[str] = Field(default=None, max_length=600)
    error_patterns: Optional[str] = Field(default=None, max_length=600)
    attention_circumstances: Optional[str] = Field(default=None, max_length=600)
    narration_comprehension: Optional[str] = Field(default=None, max_length=600)
    curriculum_concepts_taught: Optional[str] = Field(default=None, max_length=600)
    teacher_interpretation: Optional[str] = Field(default=None, max_length=800)
    suggested_next_step: Optional[str] = Field(default=None, max_length=800)
    # District Improvement Plan: separate what was done from the evidence
    # that learning changed; neither field is an automatic efficacy claim.
    instructional_strategy: Optional[str] = Field(default=None, max_length=400)
    responsible_staff_role: Optional[str] = Field(default=None, max_length=100)
    follow_up_on: Optional[date] = None
    implementation_evidence: Optional[str] = Field(default=None, max_length=600)
    impact_evidence: Optional[str] = Field(default=None, max_length=600)
    external_assessment_context: Optional[str] = Field(default=None, max_length=400)


class EvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: Optional[str] = Field(default=None, max_length=600)
    observation: Optional[TeacherObservation] = None


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "edit", "reject"]
    expected_version: int = Field(ge=1)
    edited_text: Optional[str] = Field(default=None, max_length=1200)
    rationale: Optional[str] = Field(default=None, max_length=600)
    confirmed_review_on: Optional[date] = None

    @model_validator(mode="after")
    def _contract(self):
        if self.action == "edit" and not (self.edited_text or "").strip():
            raise ValueError("An edit must include the edited instruction")
        if self.action != "edit" and self.edited_text is not None:
            raise ValueError("Only an edit carries edited instruction text")
        if self.action == "reject" and self.confirmed_review_on is not None:
            raise ValueError("A rejected proposal schedules nothing")
        return self


class PlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_text: str = Field(min_length=3, max_length=2000)


class ProgressMonitoringInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    measure: str = Field(min_length=2, max_length=32)
    planned_dates: list[date] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def _semantics(self):
        if self.measure not in DIBELS_MEASURES or self.measure == "COMPOSITE":
            raise ValueError("Progress monitoring names one DIBELS measure")
        if len(set(self.planned_dates)) != len(self.planned_dates):
            raise ValueError("Planned dates must be unique")
        return self


class SupersedeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=500)


# ── Snapshot, growth, error patterns ────────────────────────────────────────

def canonical_hash(obj: dict) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def snapshot(meta: dict, content: dict, scores: list[dict], responses: list[dict]) -> dict:
    """The exact content a FINALIZED administration commits to."""
    return {
        "administration": meta, "content": content,
        "scores": sorted(scores, key=lambda s: s["measure"]),
        "responses": sorted(responses, key=lambda r: (r["measure"], r["item_index"])),
    }


@dataclass(frozen=True)
class ScorePoint:
    assessment_id: str
    administered_at: datetime
    purpose: str
    measure: str
    status: str
    raw_score: Optional[float]
    score_unit: Optional[str]


def growth_by_measure(points: list[ScorePoint]) -> dict:
    """Per purpose, per measure: the scored series and consecutive changes.

    Purposes are never mixed (a progress-monitoring probe is not compared
    with a benchmark), and only ``scored`` points enter: a skipped or
    invalid measure is absent, never a zero.
    """
    out: dict[str, dict[str, dict]] = {}
    for p in sorted(points, key=lambda p: (p.administered_at, p.assessment_id)):
        if p.status != "scored" or p.raw_score is None:
            continue
        series = out.setdefault(p.purpose, {}).setdefault(
            p.measure, {"score_unit": p.score_unit, "points": [], "changes": []})
        if series["score_unit"] != p.score_unit:
            continue  # never subtract across units
        if series["points"]:
            prev = series["points"][-1]
            series["changes"].append({
                "from_assessment_id": prev["assessment_id"],
                "to_assessment_id": p.assessment_id,
                "change": round(p.raw_score - prev["raw_score"], 4),
            })
        series["points"].append({
            "assessment_id": p.assessment_id,
            "administered_at": p.administered_at.isoformat(),
            "raw_score": p.raw_score,
        })
    return out


def error_patterns(responses: list[dict]) -> dict:
    """Counts of teacher-marked error types per measure. Nothing inferred."""
    out: dict[str, dict[str, int]] = {}
    for r in responses:
        if r.get("correct") or not r.get("error_type"):
            continue
        bucket = out.setdefault(r["measure"], {})
        bucket[r["error_type"]] = bucket.get(r["error_type"], 0) + 1
    return {m: dict(sorted(v.items())) for m, v in sorted(out.items())}


# ── Bede's proposal (a proposal, never a decision) ──────────────────────────

_ATTENTION_LABELS = {"Well Below Benchmark", "Below Benchmark", "Most Support", "Some Support"}


@dataclass(frozen=True)
class Proposal:
    abstained: bool
    text: str
    rationale: tuple[str, ...]
    proposed_review_on: Optional[date]
    reason: str = ""
    policy_version: str = POLICY_VERSION


def propose(scores: list[dict], next_cycle: Optional[Cycle]) -> Proposal:
    """Propose a next instructional step from one finalized administration.

    Reads only what the report printed. It names measures whose PRINTED
    label calls for attention; it never computes a band, never reads cut
    points, never uses vendor guidance, and describes instruction rather
    than the child. With nothing scored it abstains.
    """
    scored = [s for s in scores if s["administration_status"] == "scored"]
    if not scored:
        return Proposal(True, "", (), None,
                        reason="No scored measure on this record; the teacher decides.")
    flagged = sorted(
        s["measure"] for s in scored
        if not s.get("is_composite")
        and (s.get("benchmark_label") in _ATTENTION_LABELS
             or s.get("support_label") in _ATTENTION_LABELS)
    )
    rationale = [
        f"{s['measure']}: printed label {s.get('benchmark_label') or s.get('support_label')}"
        for s in scored if s.get("benchmark_label") or s.get("support_label")
    ]
    if flagged:
        text = ("Proposed: targeted practice on " + ", ".join(flagged)
                + " with the teacher's chosen materials, and progress monitoring on "
                  "those measures before the next Data Day.")
    else:
        text = ("Proposed: continue current instruction; no measure on this report "
                "was printed with a label calling for additional support.")
    review = next_cycle.data_day_on if next_cycle else None
    if next_cycle:
        rationale.append(f"Proposed review at the campus's next Data Day ({next_cycle.label}).")
    else:
        rationale.append("No later Data Day is configured; the teacher sets any review date.")
    return Proposal(False, text, tuple(rationale), review)
