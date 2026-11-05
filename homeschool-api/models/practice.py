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

from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

TeacherMark = Literal["correct", "incorrect", "partial", "unmarked"]
RequiredFormat = Literal["complete_sentence", "single_word", "color_fill", "free", "unknown"]
Audience = Literal["parent_and_child", "parent_only"]

# Below this, an extracted field is shown to the parent to confirm and is
# left out of the diagnosis until they do. Guardrail 4: ask, never guess.
CONFIDENCE_FLOOR = 0.75

# A long upload is read in parts and its sections joined (extract.merge_readings),
# so this bounds what one review screen shows, not how many pages are read.
MAX_SECTIONS = 60
MAX_ITEMS_PER_SECTION = 60
MAX_WORD_BANK = 60


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── Diagrams ──────────────────────────────────────────────────────────────────
# A maths problem whose picture IS the problem (a shaded fraction, a clock, an
# array of dots) carries one of these. It is a closed vocabulary of numbers and
# short labels, never markup: the app draws it itself (Diagram.tsx), so a model
# can neither inject anything into the page nor draw a picture that disagrees
# with the answer, and services/practice/diagrams.py can work the answer out.

_Label = Field(default="", max_length=12)


class FractionDiagram(_Strict):
    kind: Literal["fraction_bar", "fraction_circle"]
    parts: int = Field(..., ge=1, le=24)
    shaded: int = Field(..., ge=0, le=24)

    @field_validator("shaded")
    @classmethod
    def _within(cls, value: int, info) -> int:
        if value > info.data.get("parts", 24):
            raise ValueError("more parts shaded than there are")
        return value


class ArrayDiagram(_Strict):
    kind: Literal["array"]
    rows: int = Field(..., ge=1, le=12)
    cols: int = Field(..., ge=1, le=12)


class BaseTenDiagram(_Strict):
    kind: Literal["base_ten"]
    hundreds: int = Field(default=0, ge=0, le=9)
    tens: int = Field(default=0, ge=0, le=9)
    ones: int = Field(default=0, ge=0, le=9)


class ClockDiagram(_Strict):
    kind: Literal["clock"]
    hour: int = Field(..., ge=1, le=12)
    minute: int = Field(..., ge=0, le=59)


class RectangleDiagram(_Strict):
    kind: Literal["rectangle"]
    width: int = Field(..., ge=1, le=100)
    height: int = Field(..., ge=1, le=100)
    unit: str = Field(default="", max_length=8)


class RightTriangleDiagram(_Strict):
    kind: Literal["right_triangle"]
    base: int = Field(..., ge=1, le=100)
    height: int = Field(..., ge=1, le=100)
    unit: str = Field(default="", max_length=8)


class NumberLineDiagram(_Strict):
    kind: Literal["number_line"]
    start: int = Field(..., ge=-100, le=1000)
    end: int = Field(..., ge=-99, le=1010)
    step: int = Field(default=1, ge=1, le=100)
    # Points marked with a dot; with labels, the labels are drawn instead of
    # the numbers, which is how "what number is at A?" is asked.
    marks: List[int] = Field(default_factory=list, max_length=4)
    mark_labels: List[str] = Field(default_factory=list, max_length=4)

    @field_validator("end")
    @classmethod
    def _after_start(cls, value: int, info) -> int:
        start = info.data.get("start")
        if start is not None and not (start < value <= start + 40 * 100):
            raise ValueError("a number line must run forwards")
        return value


class GraphBar(_Strict):
    label: str = Field(..., min_length=1, max_length=12)
    value: int = Field(..., ge=0, le=1000)


class BarGraphDiagram(_Strict):
    kind: Literal["bar_graph"]
    title: str = Field(default="", max_length=40)
    bars: List[GraphBar] = Field(..., min_length=1, max_length=8)


class PlanePoint(_Strict):
    label: str = Field(..., min_length=1, max_length=3)
    x: int = Field(..., ge=-10, le=10)
    y: int = Field(..., ge=-10, le=10)


class CoordinateDiagram(_Strict):
    kind: Literal["coordinate_plane"]
    size: int = Field(default=10, ge=2, le=10)
    four_quadrants: bool = False
    points: List[PlanePoint] = Field(..., min_length=1, max_length=6)


Diagram = Annotated[
    Union[FractionDiagram, ArrayDiagram, BaseTenDiagram, ClockDiagram, RectangleDiagram,
          RightTriangleDiagram, NumberLineDiagram, BarGraphDiagram, CoordinateDiagram],
    Field(discriminator="kind"),
]
DIAGRAM_KINDS = ("fraction_bar", "fraction_circle", "array", "base_ten", "clock", "rectangle",
                 "right_triangle", "number_line", "bar_graph", "coordinate_plane")


class AssessmentItem(_Strict):
    number: int = Field(..., ge=1, le=500)
    prompt: str = Field(..., min_length=1, max_length=300)
    stimulus: Optional[str] = Field(default=None, max_length=200)
    # The problem's picture, when it is one Bede can draw and check.
    diagram: Optional[Diagram] = None
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
    diagram: Optional[Diagram] = None


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
    # 25 MB a file (upload_safety.MAX_PAGE_BYTES), plus base64's third.
    data: str = Field(..., min_length=8, max_length=35_000_000)


class ReadPhotosRequest(_Strict):
    subject: str = Field(..., min_length=1, max_length=30)
    # Any number of pages. A browser sends a long upload as several requests,
    # each continuing the last; the server reads them in groups either way.
    pages: List[PhotoPage] = Field(..., min_length=1)
    # "local" = the household's own model only. "cloud" = the household's
    # configured AI provider, which needs cloud_consent for this upload.
    route: Optional[Literal["local", "cloud"]] = None
    cloud_consent: bool = False
    # When this request continues an earlier part of the same upload: the page
    # number of its first page, and (app) the record that part was saved as,
    # or (demo, which stores nothing) what that part read.
    first_page: int = Field(default=1, ge=1)
    continues_record: Optional[int] = Field(default=None, ge=1)
    continues: Optional[GradedAssessment] = None


class ConfirmAssessmentRequest(_Strict):
    assessment: GradedAssessment


class ApproveSetRequest(_Strict):
    # Optional parent edits; None approves the draft as written.
    practice_set: Optional[PracticeSet] = None


class PracticeOutcomeRequest(_Strict):
    item_index: int = Field(..., ge=0, le=19)
    response: str = Field(..., min_length=1, max_length=1000)

    @field_validator("response")
    @classmethod
    def response_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A response is required.")
        return value


# ── Generated quizzes and exams ───────────────────────────────────────────────
#
# A quiz Bede drafts from an existing quiz, a prior or prep exam, or a lesson
# description. Bede writes the questions AND the answers, so every answer
# carries `answer_check`: "computed" when this backend worked a maths answer
# out itself, "checked" when an independent second answer agreed, "verify"
# otherwise, for the adult to check before approving.
# Nothing here is stored; the draft lives in the request and on the screen.

QuizKind = Literal["ad_hoc", "quiz", "unit_test", "midterm", "final", "prep_exam"]
QuizLevel = Literal["review", "on_level", "challenge"]
QuestionType = Literal["multiple_choice", "true_false", "short_answer", "fill_in_blank", "computation", "written_response"]
QuizGrade = Literal["K", "1", "2", "3", "4", "5", "6", "7", "8"]

MAX_QUIZ_QUESTIONS = 50


class QuizQuestion(_Strict):
    number: int = Field(..., ge=1, le=MAX_QUIZ_QUESTIONS)
    type: QuestionType
    topic: str = Field(default="", max_length=80)
    prompt: str = Field(..., min_length=1, max_length=600)
    options: List[str] = Field(default_factory=list, max_length=6)
    answer: str = Field(..., min_length=1, max_length=400)
    diagram: Optional[Diagram] = None
    # computed: worked out by this backend. checked: a second, independent
    # answer agreed. verify: the adult should check it.
    answer_check: Literal["computed", "checked", "verify"] = "verify"
    # What the independent second answer said, when it disagreed.
    second_answer: Optional[str] = Field(default=None, max_length=400)


class GeneratedQuiz(_Strict):
    title: str = Field(..., min_length=1, max_length=120)
    subject: str = Field(..., min_length=1, max_length=30)
    grade: QuizGrade
    kind: QuizKind
    level: QuizLevel
    coverage: List[str] = Field(default_factory=list, max_length=20)
    est_minutes: int = Field(..., ge=1, le=120)
    questions: List[QuizQuestion] = Field(..., min_length=1, max_length=MAX_QUIZ_QUESTIONS)


# How much copied-out source a quiz draft reads (a long upload's later pages
# beyond this are not used, and the screen says so).
MAX_SOURCE_PAGES_TEXT = 60_000


class QuizSourceRequest(_Strict):
    """One part of a long quiz source, to be copied out as text."""
    subject: str = Field(..., min_length=1, max_length=30)
    pages: List[PhotoPage] = Field(..., min_length=1)
    route: Optional[Literal["local", "cloud"]] = None
    cloud_consent: bool = False
    first_page: int = Field(default=1, ge=1)


class GenerateQuizRequest(_Strict):
    subject: str = Field(..., min_length=1, max_length=30)
    grade: QuizGrade
    kind: QuizKind = "quiz"
    level: QuizLevel = "on_level"
    question_count: int = Field(default=10, ge=1, le=MAX_QUIZ_QUESTIONS)
    # What to cover, in the adult's words: a lesson, a unit, a chapter.
    focus: Optional[str] = Field(default=None, max_length=600)
    # An existing quiz, a previous exam or a prep exam to learn from: photos
    # or scanned pages, and/or its text pasted in.
    pages: List[PhotoPage] = Field(default_factory=list)
    source_text: Optional[str] = Field(default=None, max_length=12000)
    # A long upload's pages, already copied out as text part by part
    # (POST .../quiz/source). Counts as photos for routing and consent.
    source_pages_text: Optional[str] = Field(default=None, max_length=MAX_SOURCE_PAGES_TEXT)
    route: Optional[Literal["local", "cloud"]] = None
    cloud_consent: bool = False

    @field_validator("focus", "source_text", "source_pages_text")
    @classmethod
    def _blank_is_none(cls, value: Optional[str]) -> Optional[str]:
        value = (value or "").strip()
        return value or None

    def has_material(self) -> bool:
        return bool(self.pages or self.source_text or self.source_pages_text or self.focus)
