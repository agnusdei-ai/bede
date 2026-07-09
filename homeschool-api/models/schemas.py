from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from enum import Enum
from datetime import date


class GradeStage(str, Enum):
    foundations = "K-2"        # Grammar stage: exploration & discovery
    core_mastery = "3-5"       # Logic stage: building knowledge
    independent = "6-8"        # Rhetoric stage: application & mastery


class Subject(str, Enum):
    morning_time = "morning_time"       # Bible, hymn, poetry, prayer
    living_books = "living_books"       # Charlotte Mason literature
    mathematics = "mathematics"         # Discovery-based math
    nature_study = "nature_study"       # Observation, nature journal
    history = "history"                 # Story-based history & geography
    language_arts = "language_arts"     # Narration, copywork, grammar
    science = "science"                 # Botany, zoology, earth science
    art_music = "art_music"             # Composer & artist study
    saints = "saints"                   # Saints, catechism, virtue formation
    free_study = "free_study"           # Child-directed exploration


SUBJECT_DURATIONS = {
    Subject.morning_time: 20,
    Subject.living_books: 25,
    Subject.mathematics: 20,
    Subject.nature_study: 20,
    Subject.history: 20,
    Subject.language_arts: 15,
    Subject.science: 20,
    Subject.art_music: 15,
    Subject.saints: 15,
    Subject.free_study: 20,
}

SUBJECT_LABELS = {
    Subject.morning_time: "Morning Time",
    Subject.living_books: "Living Books",
    Subject.mathematics: "Mathematics",
    Subject.nature_study: "Nature Study",
    Subject.history: "History & Geography",
    Subject.language_arts: "Language Arts",
    Subject.science: "Science",
    Subject.art_music: "Art & Music",
    Subject.saints: "Saints & Catechism",
    Subject.free_study: "Free Study",
}


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class SessionConfig(BaseModel):
    student_name: str = Field(..., min_length=1, max_length=50)
    grade: str = Field(..., description="e.g. '3' or 'K'")
    grade_stage: GradeStage
    subjects: List[Subject] = Field(
        default=[
            Subject.morning_time,
            Subject.living_books,
            Subject.mathematics,
            Subject.nature_study,
            Subject.history,
            Subject.language_arts,
        ]
    )
    lesson_focus: Optional[str] = None       # Parent's note for today
    faith_emphasis: Optional[str] = None     # Scripture or virtue focus
    current_unit: Optional[str] = None       # e.g. "Ancient Egypt", "Fractions"
    voice_required: bool = True              # False for mute students (PIN-only auth)


class PodConfigsRequest(BaseModel):
    configs: List[SessionConfig] = Field(..., min_length=1, max_length=10)


class TutorRequest(BaseModel):
    session_config: SessionConfig
    current_subject: Subject
    conversation_history: List[ChatMessage] = []
    child_message: str = Field(..., min_length=1, max_length=2000)
    # Base64 PNG (no "data:image/..." prefix) from the handwriting canvas, sent to
    # Claude as an image so Bede reads the child's actual work instead of a text
    # placeholder. ~8MB base64 ceiling comfortably covers a canvas drawing.
    drawing_image: Optional[str] = Field(default=None, max_length=8_000_000)


class LoginRequest(BaseModel):
    role: Literal["parent", "child"]
    credential: str   # password for parent, PIN for child


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class SessionSummaryRequest(BaseModel):
    session_config: SessionConfig
    conversation_history: List[ChatMessage]
    subjects_completed: List[Subject]
    duration_minutes: int


class NarrationRecord(BaseModel):
    subject: Subject
    narration_text: str
    timestamp: str


# ── Narration assessment (Phase 1 — mastery engine) ───────────────────────────

class TriviumStage(str, Enum):
    grammar  = "grammar"    # K-5: absorption, story, wonder
    logic    = "logic"      # 6-8: questioning, patterns, cause-effect
    rhetoric = "rhetoric"   # 9-12: synthesis, argument, application

class ProcessingStyle(str, Enum):
    visual         = "visual"          # rich imagery, spatial language
    auditory       = "auditory"        # rhythm, sound, music references
    reading_writing = "reading_writing" # precise quotes, careful language
    kinesthetic    = "kinesthetic"     # action, movement, hands-on focus

class NarrationMode(str, Enum):
    sequential  = "sequential"   # retells in careful chronological order
    associative = "associative"  # jumps to significance, makes cross-leaps

class NarrationAssessmentData(BaseModel):
    """Full rubric data stored encrypted per narration event."""
    subject:                str
    completeness:           int = Field(..., ge=1, le=5)
    sequence:               int = Field(..., ge=1, le=5)
    detail:                 int = Field(..., ge=1, le=5)
    language_quality:       int = Field(..., ge=1, le=5)
    synthesis:              int = Field(..., ge=1, le=5)
    total_score:            int = Field(..., ge=5, le=25)
    concepts_demonstrated:  List[str]
    misconceptions:         List[str]
    adaptive_signal:        Literal["advance", "repeat", "review_prerequisite"]
    bede_observation:       str
    assessed_at:            str

class LearnerProfileData(BaseModel):
    """Stable learner-type profile synthesized from accumulated assessments."""
    trivium_stage:         TriviumStage
    processing_style:      ProcessingStyle
    narration_mode:        NarrationMode
    attention_profile:     Literal["short_blocks", "sustained", "variable"]
    session_count_assessed: int
    bede_profile_notes:    str
    assessed_at:           str
