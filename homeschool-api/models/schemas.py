from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional, Literal
from enum import Enum
from datetime import date


class GradeStage(str, Enum):
    foundations = "K-2"        # Grammar stage: exploration & discovery
    core_mastery = "3-5"       # Logic stage: building knowledge
    independent = "6-8"        # Rhetoric stage: application & mastery


# Valid grade values a visitor can pick, in display order — mirrors
# services/ai_service.py's _GRADE_DESCRIPTORS keys.
VALID_GRADES = ["K", "1", "2", "3", "4", "5", "6", "7", "8"]


def grade_to_stage(grade: str) -> GradeStage:
    """Maps a grade string to its Mater Amabilis-aligned stage (see
    services/ai_service.py's _STAGE_GUIDANCE for what each stage means for
    narration pacing). Unrecognized input defaults to foundations — the
    gentlest, least presumptuous stage — rather than raising, since this
    only ever drives tone/pacing, never a security-relevant decision."""
    g = grade.strip().upper()
    if g in ("K", "0", "1", "2"):
        return GradeStage.foundations
    if g in ("3", "4", "5"):
        return GradeStage.core_mastery
    if g in ("6", "7", "8"):
        return GradeStage.independent
    return GradeStage.foundations


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

    # Parent-set cap on total on-screen tutoring minutes before a mandatory
    # eye-rest break is inserted, independent of the grade-based block/break
    # cycle. None = no additional cap.
    screen_time_limit_minutes: Optional[int] = Field(default=None, ge=15, le=480)
    # Length of the mandatory break once the cap is reached. 30-minute floor
    # enforced here so a weaker value can never be saved, even if the client
    # is bypassed.
    eye_rest_break_minutes: int = Field(default=30, ge=30, le=120)
    # Remembers the child's own last choice for Bede's spoken narration (the
    # mute/unmute button in SocraticChat.tsx) — distinct from voice_required
    # above, which is about login voice-biometric verification, not TTS
    # output. Updated via PATCH /pod/configs/{student_name}/voice-narration
    # (routers/pod.py), reachable by the child themselves, not just the parent.
    voice_narration_enabled: bool = True

    # True only for a public demo session where the visitor supplied their
    # own Anthropic or OpenAI API key (see DemoCodeRequest.byok_anthropic_key
    # / byok_openai_key) — tells the demo frontend to skip the 15-minute
    # free-tier session cap, since the API cost is on the visitor's own
    # account. Always False for parent/child roles; never set from client
    # input (routers/tutor.py's _demo_session_config is the only place that
    # sets it).
    demo_uncapped: bool = False


class VoiceNarrationPreferenceRequest(BaseModel):
    voice_narration_enabled: bool


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


class NarrationUploadRequest(BaseModel):
    """A narration file exported from a smart pen/notebook app (e.g. inq) —
    see POST /tutor/extract-narration and services/document_extraction.py.
    No file is stored; extraction happens in memory for one request only."""
    filename: str = Field(..., min_length=1, max_length=200)
    content_base64: str = Field(..., min_length=1, max_length=7_000_000)


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


class SandboxChatRequest(BaseModel):
    """
    Parent-only, direct-answer chat for testing/exploring Bede's behavior —
    see routers/sandbox.py. Nothing here is ever persisted: no DB writes, no
    narration assessments, no audit-logged content. sandbox_pin is checked
    on every request rather than once at login, since this doesn't have its
    own session/token — it rides on the parent's existing auth instead.
    """
    sandbox_pin: str = Field(..., min_length=1, max_length=100)
    conversation_history: List[ChatMessage] = []
    message: str = Field(..., min_length=1, max_length=4000)
    # The parent's own live-edited context/instructions for this conversation
    # only — never written to the real per-subject prompts or catalog files
    # that actually drive a child's tutoring session.
    custom_instructions: str = Field(default="", max_length=4000)


class SandboxDemoChatRequest(BaseModel):
    """
    Public-demo preview of the sandbox above — same shape minus sandbox_pin,
    since the demo role's own auth (DEMO_PIN + single-active-session) is the
    gate here instead. See routers/sandbox.py's /demo-chat.
    """
    conversation_history: List[ChatMessage] = []
    message: str = Field(..., min_length=1, max_length=4000)
    custom_instructions: str = Field(default="", max_length=4000)


class LoginRequest(BaseModel):
    role: Literal["parent", "child", "demo_code"]
    credential: str   # password for parent, PIN for child, generated code for demo_code


class DemoCodeRequest(BaseModel):
    """Optional personalization for a demo session — see POST /auth/demo-code.
    All fields are optional; omitting student_name/grade keeps the operator's
    configured DEMO_STUDENT_NAME/DEMO_GRADE default for that field.
    student_name is sanitized server-side (see routers/tutor.py's
    _demo_session_config) since it's the one new piece of free text an
    anonymous visitor can put in front of the model.

    byok_anthropic_key: a visitor's own Anthropic API key, used ONLY for that
    visitor's own Anthropic calls for that session (see
    core/demo_code_session.py's get_byok_anthropic_key and
    services/ai_service.py's stream_tutor_response) — never the operator's
    key, never logged, never written to the database, held only in the same
    in-memory, ephemeral _codes dict as everything else about a demo code.
    Supplying one skips the 15-minute free-tier session cap (routers/tutor.py
    sets SessionConfig.demo_uncapped), since the API cost is now on the
    visitor's own account, not the operator's.

    byok_openai_key: the same idea, but for a visitor who'd rather use their
    own OpenAI account and have Bede tutor on GPT instead of Claude (see
    core/demo_code_session.py's get_byok_openai_key and
    services/ai_service.py's _stream_tutor_events_openai). Mutually
    exclusive in practice with byok_anthropic_key — the frontend only shows
    one BYOK field at a time — but nothing here enforces that; routers/
    tutor.py prefers an OpenAI key over an Anthropic one if a caller somehow
    supplies both."""
    student_name: Optional[str] = Field(None, min_length=1, max_length=50)
    grade: Optional[str] = Field(None, max_length=2)
    byok_anthropic_key: Optional[str] = Field(None, min_length=10, max_length=200)
    byok_openai_key: Optional[str] = Field(None, min_length=10, max_length=200)


class DemoCodeResponse(BaseModel):
    """A freshly minted, one-time 6-digit code — see POST /auth/demo-code.
    Exchanged for a JWT via POST /auth/login (role="demo_code")."""
    code: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    # True when this token is only a "parent_pending" stepping-stone — the
    # parent's password was correct, but an enrolled security key/TOTP code
    # is still required before the real "parent" token is issued.
    mfa_required: bool = False
    mfa_methods: List[Literal["webauthn", "totp"]] = []


# ── Parent MFA: FIDO2 security key + TOTP ────────────────────────────────────

class WebAuthnRegisterVerifyRequest(BaseModel):
    credential: dict
    nickname: str = Field(default="", max_length=100)


class WebAuthnAuthVerifyRequest(BaseModel):
    credential: dict


class TotpConfirmRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=8)


class TotpVerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=8)


class SessionSummaryRequest(BaseModel):
    session_config: SessionConfig
    conversation_history: List[ChatMessage]
    subjects_completed: List[Subject]
    duration_minutes: int


class EmailSummaryRequest(BaseModel):
    # Used for exactly one outbound send — never persisted anywhere, not the
    # database, not the audit log. See routers/tutor.py's /email-summary.
    email: EmailStr
    session_config: SessionConfig
    conversation_history: List[ChatMessage]
    subjects_completed: List[Subject]
    duration_minutes: int


class FeedbackRequest(BaseModel):
    """
    Beta feedback from any authenticated role (parent, child, or a public
    demo visitor) routed to the operator's own inbox — see routers/feedback.py.
    Nothing here is persisted server-side beyond the outbound email itself;
    the audit log records only that feedback was submitted, never its content
    or contact_email (same "never log the address" rule as email-summary).
    """
    category: Literal["cx", "ux", "content_quality", "other"]
    message: str = Field(..., min_length=1, max_length=2000)
    rating: Optional[int] = Field(None, ge=1, le=5)
    contact_email: Optional[EmailStr] = None


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
