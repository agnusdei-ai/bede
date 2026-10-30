"""Practice Coach schemas (docs/PRACTICE_COACH.md).

A parent photographs a graded quiz; Bede reads it into a `GradedAssessment`,
the parent confirms it, a subject pack diagnoses the pattern behind each miss,
and Bede drafts a short `PracticeSet` the parent approves before the child
ever sees it.

Two absences are deliberate and are the reason these models are strict
(`extra="forbid"`):

* **No identity fields.** There is no name, school, teacher or date field
  anywhere, so a reader that transcribes one has nowhere to put it and fails
  validation instead of storing it.
* **No grade of Bede's own.** `teacher_mark_count()` counts the TEACHER'S
  marks for display; nothing here scores the child.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

TeacherMark = Literal["correct", "incorrect", "partial", "unmarked"]
RequiredFormat = Literal["complete_sentence", "single_word", "color_fill", "free", "unknown"]
Audience = Literal["parent_and_child", "parent_only"]

# Below this, an extracted field is shown to the parent to confirm and is
# left out of the diagnosis until they do. Guardrail 4: ask, never guess.
CONFIDENCE_FLOOR = 0.75

MAX_SECTIONS = 12
MAX_ITEMS_PER_SECTION = 60
MAX_WORD_BANK = 60


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssessmentItem(_Strict):
    number: int = Field(..., ge=1, le=500)
    prompt: str = Field(..., min_length=1, max_length=300)
    stimulus: Optional[str] = Field(default=None, max_length=200)
    # None or "" means nothing is written there. For a colour-fill item a
    # circle deliberately left white is the answer "uncolored", not a blank.
    student_response: Optional[str] = Field(default=None, max_length=200)
    teacher_mark: TeacherMark = "unmarked"
    teacher_correction: Optional[str] = Field(default=None, max_length=200)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    # Set when the reader could not settle something; the parent answers it.
    ask_parent: Optional[str] = Field(default=None, max_length=200)

    def needs_parent(self) -> bool:
        return bool(self.ask_parent) or self.confidence < CONFIDENCE_FLOOR


class AssessmentSection(_Strict):
    label: str = Field(..., min_length=1, max_length=60)
    instructions: str = Field(default="", max_length=500)
    required_format: RequiredFormat = "unknown"
    word_bank: List[str] = Field(default_factory=list, max_length=MAX_WORD_BANK)
    items: List[AssessmentItem] = Field(..., min_length=1, max_length=MAX_ITEMS_PER_SECTION)


class GradedAssessment(_Strict):
    subject: str = Field(..., min_length=1, max_length=30)
    sections: List[AssessmentSection] = Field(..., min_length=1, max_length=MAX_SECTIONS)

    def word_bank(self) -> List[str]:
        seen: list[str] = []
        for section in self.sections:
            for word in section.word_bank:
                if word not in seen:
                    seen.append(word)
        return seen

    def needs_parent(self) -> List[str]:
        return [
            f"{s.label} #{i.number}: {i.ask_parent or 'low confidence reading'}"
            for s in self.sections for i in s.items if i.needs_parent()
        ]


def teacher_mark_count(assessment: GradedAssessment) -> dict:
    """The teacher's own tally, for display only — never a Bede grade."""
    marked = [i for s in assessment.sections for i in s.items if i.teacher_mark != "unmarked"]
    return {
        "correct": sum(1 for i in marked if i.teacher_mark == "correct"),
        "total": len(marked),
        "source": "teacher_marks",
    }


class ErrorInstance(_Strict):
    item_ref: str = Field(..., max_length=80)
    category: str = Field(..., max_length=80)
    evidence: str = Field(..., max_length=300)
    severity: Literal["low", "medium", "high"] = "low"
    audience: Audience = "parent_and_child"


class Strength(_Strict):
    category: str = Field(..., max_length=80)
    note: str = Field(..., max_length=300)


class Diagnosis(_Strict):
    errors: List[ErrorInstance] = Field(default_factory=list)
    strengths: List[Strength] = Field(default_factory=list)
    ask_parent: List[str] = Field(default_factory=list)


class PracticeItem(_Strict):
    kind: Literal["drill", "sentence_habit", "retrieval"]
    target: str = Field(..., max_length=80)
    prompt: str = Field(..., max_length=300)
    expected_answer: str = Field(..., max_length=200)
    hint: str = Field(default="", max_length=300)


class PracticeSet(_Strict):
    targets: List[str] = Field(..., min_length=1)
    mode: Literal["drill", "retrieval"]
    est_minutes: int = Field(..., ge=1, le=10)
    items: List[PracticeItem] = Field(..., min_length=1, max_length=20)
    parent_script: str = Field(..., max_length=1200)
    recheck_schedule: List[str] = Field(default_factory=lambda: ["+3d", "+7d"])


# ── Request bodies ────────────────────────────────────────────────────────────

class PhotoPage(_Strict):
    # Base64 without a "data:" prefix — the same shape the handwriting canvas
    # sends as TutorRequest.drawing_image.
    data: str = Field(..., min_length=8, max_length=8_000_000)


class ReadPhotosRequest(_Strict):
    subject: str = Field(..., min_length=1, max_length=30)
    pages: List[PhotoPage] = Field(..., min_length=1, max_length=6)
    # "local" = the household's own model only. "cloud" = the household's
    # configured AI provider, which needs cloud_consent for this upload.
    route: Optional[Literal["local", "cloud"]] = None
    cloud_consent: bool = False


class DemoReadPhotosRequest(_Strict):
    """The public demo's upload (routers/practice_demo.py). No `route`: the
    demo never reads on a local model, so there is nothing to choose, and
    `cloud_consent` is not optional in practice — the route refuses without
    it. Fewer pages than a family may send: the demo is a preview."""
    subject: str = Field(..., min_length=1, max_length=30)
    pages: List[PhotoPage] = Field(..., min_length=1, max_length=3)
    cloud_consent: bool = False


class ConfirmAssessmentRequest(_Strict):
    assessment: GradedAssessment


class ApproveSetRequest(_Strict):
    # Optional parent edits; None approves the draft as written.
    practice_set: Optional[PracticeSet] = None
