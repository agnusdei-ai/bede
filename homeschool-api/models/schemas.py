from pydantic import model_validator, BaseModel, EmailStr, Field
from typing import Dict, List, Optional, Literal
from enum import Enum
from datetime import date


class GradeStage(str, Enum):
    foundations = "K-2"        # Grammar stage: exploration & discovery
    core_mastery = "3-5"       # Logic stage: building knowledge
    independent = "6-8"        # Rhetoric stage: application & mastery


# Valid grade values a visitor can pick, in display order — mirrors
# services/ai_service.py's _GRADE_DESCRIPTORS keys.
VALID_GRADES = ["K", "1", "2", "3", "4", "5", "6", "7", "8"]

# Bible translations a parent can pick for SessionConfig.bible_translation,
# in display order — deliberately spans both Protestant and Catholic
# editions (see docs/CONSTITUTION.md's non-negotiable rule that Bede never
# rules on a family's beliefs), same reasoning behind Subject.scripture
# existing as a sibling to Subject.saints rather than one Bible-content
# module assuming a single tradition's preferred text. Mirrored in
# homeschool-tutor/src/pages/ParentSetup.tsx's own copy of this list, same
# duplication convention as VALID_GRADES/DEMO_GRADES above.
BIBLE_TRANSLATIONS = [
    "KJV", "NKJV", "ESV", "NIV", "NASB", "NLT", "CSB",
    "RSV-CE", "NABRE", "NRSV-CE", "Douay-Rheims",
]

# Of BIBLE_TRANSLATIONS above, these two are the ones actually in the public
# domain: KJV (in the US and virtually every jurisdiction that matters here)
# and the Challoner-revision Douay-Rheims (predates any modern copyright).
# Every other option — NKJV, ESV, NIV, NASB, NLT, CSB, RSV-CE, NABRE, NRSV-CE
# — is a modern, actively copyrighted translation owned by its own publisher
# (Crossway, Biblica, the Lockman Foundation, Tyndale, Holman, the USCCB for
# NABRE, and so on). Bede was never given a verified, licensed copy of any of
# those texts to quote from — only whatever it happened to learn during
# training, which is neither guaranteed accurate nor something this app has
# a license to reproduce at length. services/ai_service.py's
# _bible_translation_note treats the two groups differently for exactly that
# reason: freely favor wording for a public-domain translation, but default
# to paraphrase (never presenting invented or uncertain wording as an exact
# quotation) for a copyrighted one — the same "never fabricate certainty"
# rule the constitution already states, applied here to text Bede cannot
# verify it has permission or accurate memory to reproduce.
PUBLIC_DOMAIN_BIBLE_TRANSLATIONS = {"KJV", "Douay-Rheims"}

# What actually HELPS a particular child, in the parent's own words — never
# what is "wrong" with them. Quick-pick suggestions only; a family's own
# wording outside this list is kept exactly as typed (see
# SessionConfig.learning_support).
#
# Every entry names a change to HOW a lesson is delivered, never to WHAT is
# taught or the standard the work is held to. That distinction is the whole
# design: an accommodation removes an obstacle between a child and the
# material, and a lowered expectation removes the material. See
# services/ai_service.py's _learning_support_note.
LEARNING_SUPPORT_SUGGESTIONS = [
    "More time to answer",
    "Shorter passages at a time",
    "Answer out loud instead of writing",
    "Read the passage aloud to them",
    "Break tasks into one step at a time",
    "Frequent short breaks",
    "Repeat instructions before starting",
    "Say numbers and letters clearly, one at a time",
]

# Curriculum publishers commonly used alongside Bede by classical/Christian
# homeschool families, offered as quick-pick suggestions for
# SessionConfig.curriculum_resources — NOT a closed enum (a family's own
# entry outside this list is kept as-is, same "suggestion, not allowlist"
# treatment as faith_tradition). Deliberately spans several different
# subjects rather than one (Memoria Press/Classical Academic Press: Latin
# & classical method; Well-Trained Mind Press: general classical method;
# Institute for Excellence in Writing: writing; RightStart Mathematics:
# math; Logic of English: phonics/spelling) since a family may already use
# several of these for different subjects at once. Mirrored in
# homeschool-tutor/src/types/index.ts, same duplication convention as
# BIBLE_TRANSLATIONS above.
CURRICULUM_RESOURCE_SUGGESTIONS = [
    "Memoria Press", "Classical Academic Press", "Well-Trained Mind Press",
    "Institute for Excellence in Writing", "RightStart Mathematics", "Logic of English",
]


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


class TermSchedule(str, Enum):
    """Mater Amabilis is organized around a 3-term (trimester) year; some
    families run a 4-quarter year instead. The schedule choice drives the
    poetry/term rotation length and how term outcomes are framed."""
    trimester = "trimester"   # 3 terms per year (Mater Amabilis default)
    quarterly = "quarterly"   # 4 quarters per year


class CompanionMode(str, Enum):
    """A parent-chosen starting point at setup (ParentSetup.tsx's preset
    picker) for how much of the day Bede should drive versus defer to the
    family's own physical books and materials — meant for families new to
    homeschooling, or easing into AI deliberately, who want a lighter
    footprint than the full subject rotation. full_plan is the default and
    matches every config saved before this field existed: it changes
    nothing (see services/ai_service.py's _companion_mode_note, which
    returns "" for full_plan, keeping today's prompt byte-for-byte
    unchanged for anyone who never touches this setting)."""
    book_companion = "book_companion"   # lightest touch — anchors on the family's own books
    guided = "guided"                   # middle ground — book-based, with more structure
    full_plan = "full_plan"             # today's default — Bede drives the full rotation


# Foundational core areas the parent tracks term-by-term. Every learner is
# expected to be EXPOSED to all of a term's topics and to reach MASTERY of
# the parent's chosen topics (up to 3 per area per term) — see
# SessionConfig.term_mastery_topics and services/ai_service.py's
# _term_outcomes_note.
#
# Mastery-cycle window (SessionConfig.mastery_cycle_days). The default is
# four ACTUAL weeks — calendar days, not days school happened — which is
# also what the learner's guarantee is written against. TRAVEL_* bound the
# range a travelling family may widen it to; a family not travelling gets
# the default and no choice to make.
DEFAULT_MASTERY_CYCLE_DAYS = 28
TRAVEL_MASTERY_CYCLE_MIN_DAYS = 21   # 3 weeks
TRAVEL_MASTERY_CYCLE_MAX_DAYS = 42   # 6 weeks

CORE_AREAS = {
    "phonics_language":    "Phonics & Language",
    "mathematics":         "Math",
    "reading_literature":  "Reading & Literature",
    "science":             "Science",
    "writing_composition": "Writing & Composition",
}

# Which subjects gauge which core areas — a subject's sessions produce the
# narration evidence that feeds that area's term-mastery picture.
SUBJECT_CORE_AREAS = {}  # populated after Subject is defined below


class Subject(str, Enum):
    morning_time = "morning_time"       # Bible, hymn, poetry, prayer
    living_books = "living_books"       # Mater Amabilis literature
    mathematics = "mathematics"         # Discovery-based math
    nature_study = "nature_study"       # Observation, nature journal
    history = "history"                 # Story-based history & geography
    language_arts = "language_arts"     # Narration, copywork, grammar
    science = "science"                 # Botany, zoology, earth science
    art_music = "art_music"             # Composer & artist study
    saints = "saints"                   # Saints, catechism, virtue formation (Catholic-tradition module)
    scripture = "scripture"             # Bible heroes, memory verses, doctrine — denominationally-configurable
    latin = "latin"                     # Latin rooted in the shared Christian vocabulary — see services/latin_catalog.py
    greek = "greek"                     # Koine Greek, the New Testament's own language — see services/greek_catalog.py
    logic = "logic"                     # Reasoning — 3-5 informal, 6-8 formal; NEVER K-2, see services/logic_catalog.py
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
    Subject.scripture: 15,
    # Deliberately the shortest block in the curriculum. A Latin session is
    # a handful of words met properly, not a class period — and at K-2 it
    # is purely oral (see services/latin_catalog.py's _STAGE_METHOD), where
    # ten minutes is already generous.
    Subject.latin: 10,
    # Same 10 minutes as Latin, and for the same reason — a few words or
    # letters met properly, not a class period. A family running both gets
    # 20 minutes of classical language a day, which is already more than
    # most K-8 homeschool days give it.
    Subject.greek: 10,
    # Longer than the language blocks: a single argument judged properly
    # needs the student to reason out loud, be wrong, and be walked back
    # through it. That doesn't compress the way a vocabulary word does.
    Subject.logic: 15,
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
    Subject.scripture: "Scripture & Bible Study",
    Subject.latin: "Latin & Christian Foundations",
    Subject.greek: "Greek & New Testament Foundations",
    Subject.logic: "Logic",
    Subject.free_study: "Free Study",
}


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class LessonResume(BaseModel):
    """
    One subject's "pick up where we left off" note, written by the parent
    before the day's session — the curriculum director telling Bede exactly
    where they and the child stopped, so the subject resumes mid-thread
    instead of opening as though the material were new.

    `subject` is a Subject enum member, which is the whole enforcement of
    "if it isn't a subject Bede teaches, it can't be introduced": a note can
    only ever attach to one of the subjects in the curriculum, never to
    an arbitrary parent-invented topic. SessionConfig's validator narrows
    that further to subjects actually scheduled for this student today.

    The free-text fields are parent-supplied context, so they take the same
    route every other parent field does — services/ai_service.py's
    _sanitize_parent_field (HTML, injection phrasing, credential shapes) on
    the way into the prompt, and no authority over Bede's rules once there
    (see _lesson_resume_note).
    """
    subject: Subject
    # Where the last lesson actually stopped — the one required field; a
    # resume note with nothing to resume from is just noise in the prompt.
    stopped_at: str = Field(..., min_length=1, max_length=300)
    # What the parent wants taken up next, if they have something specific
    # in mind. Left unset, Bede decides the next step itself.
    next_step: Optional[str] = Field(default=None, max_length=300)
    # Where the child struggled last time, so Bede can slow down there
    # rather than rediscovering the difficulty from scratch.
    sticking_point: Optional[str] = Field(default=None, max_length=300)
    # ISO date (YYYY-MM-DD) of the lesson being resumed, so Bede can tell a
    # thread picked up this morning from one dropped three weeks ago. Kept a
    # string rather than a date so config dicts stay JSON-serializable for
    # encrypt_json (core/encryption.py).
    recorded_on: Optional[str] = Field(default=None, max_length=10)


SUBJECT_CORE_AREAS.update({
    Subject.language_arts: ["phonics_language", "writing_composition"],
    Subject.mathematics:   ["mathematics"],
    Subject.living_books:  ["reading_literature", "writing_composition"],
    Subject.science:       ["science"],
    Subject.nature_study:  ["science"],
})


class SessionConfig(BaseModel):
    student_name: str = Field(..., min_length=1, max_length=50)
    grade: str = Field(..., description="e.g. '3' or 'K'")
    grade_stage: GradeStage
    # Biological sex, not a separate "gender identity" concept — consistent
    # with Bede's classical natural-law formation (docs/CONSTITUTION.md).
    # Optional for an English-only deployment, where it's never asked for or
    # used. Required by routers/pod.py's save_pod_configs whenever LOCALE is
    # a non-English value: Spanish, Italian, and Polish all need this for
    # grammatically correct address ("bienvenido"/"bienvenida", and in
    # Polish even past-tense verb agreement) — see
    # services/ai_service.py's _locale_directive and docs/LOCALIZATION.md.
    # Every locale currently supported happens to be a grammatically
    # gendered language; a future non-gendered addition (Tagalog, from the
    # original locale list, has no grammatical gender at all) would need
    # this requirement revisited rather than assumed to still apply.
    sex: Optional[Literal["male", "female"]] = None
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
    # Optional, short label for the family's own church tradition (e.g.
    # "Baptist", "Non-denominational", "Catholic", "Eastern Orthodox") — sets
    # framing guidance for Scripture & Bible Study / Saints & Catechism
    # content (see services/ai_service.py's _faith_tradition_note), never a
    # basis to rule on the family's beliefs (docs/CONSTITUTION.md). A real
    # parent sets this directly in ParentSetup.tsx's optional "session
    # context" panel, shown only once Scripture or Saints is enabled for
    # that student — their own subject selection already signals which
    # module applies, this just refines the framing within it. The public
    # demo populates it via its own optional intake note instead (see
    # DemoCodeRequest.faith_tradition and CLAUDE.md's "Continuing Mastery
    # (demo)" section), since the demo shows both faith subjects to every
    # visitor regardless of background.
    faith_tradition: Optional[str] = Field(default=None, max_length=60)
    # Parent's preferred Bible translation (see BIBLE_TRANSLATIONS above),
    # so Bede's own quoting/paraphrasing of Scripture in Scripture & Bible
    # Study, Saints & Catechism, and Morning Time aligns with the wording
    # the family already reads at home, rather than defaulting to whichever
    # translation Bede's own training happens to favor. Set alongside
    # faith_tradition in ParentSetup.tsx's optional "session context" panel
    # (see services/ai_service.py's _bible_translation_note). Not a closed
    # enum here — an unrecognized value is simply not one of the picker's
    # options, and the field is free enough to still be forward-compatible
    # with a translation added to BIBLE_TRANSLATIONS later without a schema
    # change.
    bible_translation: Optional[str] = Field(default=None, max_length=40)
    # Curriculum publishers/resources the family already uses alongside
    # Bede (see CURRICULUM_RESOURCE_SUGGESTIONS above) — up to 6 short
    # entries, cleaned/deduped by _validate_curriculum_resources below, same
    # "cap + clean, never reject" convention term_mastery_topics already
    # uses. Framing guidance only (see services/ai_service.py's
    # _curriculum_resources_note): Bede aligns terminology/approach where
    # it naturally overlaps with a named resource's own known method, but
    # never claims to reproduce that publisher's specific proprietary
    # lesson content — unlike data/catechism/faith_and_life.json, there is
    # no sourced, verified scope-and-sequence backing these names, so
    # treating them as anything beyond a name to align tone with would risk
    # fabricating claims about content Bede was never actually given.
    curriculum_resources: List[str] = Field(default_factory=list)
    # What helps THIS child, stated by the parent — never inferred by Bede,
    # and never a diagnosis. See LEARNING_SUPPORT_SUGGESTIONS above and
    # services/ai_service.py's _learning_support_note for the governing
    # rules; docs/PARENT_SETUP.md for how it is put to a parent.
    #
    # WHY PARENT-DECLARED AND NOT INFERRED. Deciding a child needs support
    # is a judgment about that child, and the two ways to reach it are a
    # qualified evaluator or the parent who lives with them. Bede is
    # neither. It can notice a pattern and say so (see the reading-strands
    # observation in docs/PARENT_SETUP.md), but the standing decision about
    # what a child needs is not one this software makes — the same
    # authority_order the constitution states, where the parent is the
    # child's primary educator.
    #
    # Same "clean, never reject" convention as curriculum_resources above.
    learning_support: List[str] = Field(default_factory=list)
    voice_required: bool = True              # False for mute students (PIN-only auth)

    # The session's hard stop, in minutes — on by default and there by
    # design: the session concludes automatically when it's reached. 2-hour
    # default; a parent (behind the parent password) may raise it, but the
    # schema ceiling means no stored value can ever exceed 4 hours. Configs
    # saved before this field existed load as the 2-hour default. A
    # mandatory 10-minute break runs after every hour of session time
    # regardless of this value (frontend gradeTimer.ts).
    session_cap_minutes: int = Field(default=120, ge=30, le=240)
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
    # Parent-side lock on the chat appearance picker (background theme +
    # bubble color). When True, the child's session hides the picker
    # entirely — whatever look the device already has stays put. For
    # children who find open-ended customization a distraction magnet
    # (ADD/ADHD tendencies especially), choice happens with the parent,
    # not mid-lesson. A parent-role session still sees the picker.
    appearance_locked: bool = False
    # Parent's chosen starting point (see CompanionMode) — how much Bede
    # drives the day versus defers to the family's own books. Purely a
    # behavioral framing layered into the prompt (_companion_mode_note);
    # does NOT itself constrain which subjects can be selected above.
    companion_mode: CompanionMode = CompanionMode.full_plan

    # ── Term schedule & outcomes ──────────────────────────────────────────
    # Mater Amabilis default is a 3-term year; quarterly gives 4. current_term
    # is 1-based and capped by the schedule (validated below).
    term_schedule: TermSchedule = TermSchedule.trimester
    current_term: int = Field(default=1, ge=1, le=4)
    # Parent's chosen mastery outcomes for the current term: up to 3 topics
    # per core area (keys from CORE_AREAS). Exposure to every listed topic is
    # expected across the term; mastery of these named topics is the outcome.
    # Bede steers sessions toward them and records per-topic evidence via
    # assess_narration's term_topic fields.
    term_mastery_topics: dict[str, list[str]] = Field(default_factory=dict)

    # ── Mastery cycle — how often the parent gets an honest read ──────────
    # A term (9-12 weeks) is too coarse to answer "is this on track?", and
    # the learner's guarantee is written in 30 days, so there was nothing
    # between today's session summary and the whole term. This is that
    # middle cadence.
    #
    # It bounds the LOOKING, never the child's work. Deliberately a ROLLING
    # window rather than a numbered sprint with a start date: there is no
    # boundary to hit, nothing resets, nothing rolls over, and no velocity
    # can be computed across cycles. "In the last N days, did this move" is
    # the only question it can answer — which is the question a parent
    # actually has, and is safe to ask about a child in a way "did they
    # finish on time" is not. Nothing here is ever shown to a child (see
    # Progress.tsx, parent-only, same posture as the work ledger).
    #
    # 28 ACTUAL days — calendar days, not days school happened. A family
    # that travels can't fit the usual evidence into 28 calendar days, so
    # travel_mode unlocks a longer window (3-6 weeks) to let the same
    # evidence accumulate. It lengthens the window; it does not pause a
    # clock, and it does not change one thing about how the child is taught.
    travel_mode: bool = False
    mastery_cycle_days: int = Field(default=DEFAULT_MASTERY_CYCLE_DAYS)

    # ── "Meet me where I am" — resuming an interrupted lesson ─────────────
    # At most one note per subject (later duplicates win; see the validator),
    # and only for subjects actually scheduled for this student today —
    # anything else is dropped rather than rejected, so a parent trimming
    # today's subject list never gets a save error over a stale note.
    lesson_resume: List[LessonResume] = Field(default_factory=list, max_length=len(Subject))

    @model_validator(mode="after")
    def _validate_term(self):
        max_term = 3 if self.term_schedule == TermSchedule.trimester else 4
        if self.current_term > max_term:
            self.current_term = max_term
        cleaned: dict[str, list[str]] = {}
        for area, topics in (self.term_mastery_topics or {}).items():
            if area not in CORE_AREAS:
                continue
            kept = [t.strip()[:120] for t in topics if t and t.strip()][:3]
            if kept:
                cleaned[area] = kept
        self.term_mastery_topics = cleaned

        # Mastery-cycle window, same "clean, never reject" shape as above.
        # Travel mode is what UNLOCKS the choice — with it off there is only
        # one honest answer (28 actual days, what the guarantee is written
        # against), so a stale or hand-crafted value is corrected rather
        # than 422'd. With it on the parent picks, and we clamp to 3-6
        # weeks: under three there isn't room for evidence to accumulate,
        # over six it stops being a cadence and becomes the term again.
        if not self.travel_mode:
            self.mastery_cycle_days = DEFAULT_MASTERY_CYCLE_DAYS
        else:
            self.mastery_cycle_days = max(
                TRAVEL_MASTERY_CYCLE_MIN_DAYS,
                min(TRAVEL_MASTERY_CYCLE_MAX_DAYS, self.mastery_cycle_days),
            )
        return self

    @model_validator(mode="after")
    def _validate_curriculum_resources(self):
        """Trims, drops empties, dedupes case-insensitively (keeping the
        first-seen casing), and caps at 6 — the same "clean, never reject"
        shape _validate_term applies to term_mastery_topics, so a client
        sending a slightly malformed list never gets a 422 over a field
        this low-stakes."""
        seen: dict[str, str] = {}
        for entry in self.curriculum_resources or []:
            cleaned = entry.strip()[:60] if entry else ""
            if cleaned and cleaned.lower() not in seen:
                seen[cleaned.lower()] = cleaned
        self.curriculum_resources = list(seen.values())[:6]
        return self

    @model_validator(mode="after")
    def _validate_learning_support(self):
        """Same clean-never-reject shape as _validate_curriculum_resources
        above, and for a sharper reason: a parent describing what helps
        their child is the last person who should meet a 422 over
        whitespace."""
        seen: dict[str, str] = {}
        for entry in self.learning_support or []:
            cleaned = entry.strip()[:80] if entry else ""
            if cleaned and cleaned.lower() not in seen:
                seen[cleaned.lower()] = cleaned
        self.learning_support = list(seen.values())[:8]
        return self

    @model_validator(mode="after")
    def _validate_logic_stage(self):
        """Logic is not a K-2 subject, and this is where that is actually
        enforced rather than assumed.

        Formal reasoning before the Logic stage is the premature
        abstraction classical education specifically warns against — a
        Grammar-stage child is gathering the world, not auditing it. The UI
        never offers the card to a K-2 student and services/logic_catalog.py
        renders nothing for that stage, but neither of those is a
        server-side guarantee: a hand-rolled request, a saved config from
        before a student's stage was corrected downward, or a future client
        bug would all sail past them.

        "Clean, never reject" — the same shape _validate_term and
        _validate_curriculum_resources use. A parent who somehow submits
        this gets a config without it, not a 422 they can't act on. It runs
        BEFORE _validate_lesson_resume deliberately, so a resume note
        attached to the dropped subject is filtered out by that validator
        in the same pass rather than surviving as an orphan.

        Dropping this can in principle leave `subjects` empty (a K-2 config
        naming logic and nothing else). That is a state the UI cannot
        produce and the parent can immediately fix by picking subjects —
        strictly better than honoring a subject the child shouldn't be
        sitting.
        """
        if self.grade_stage == GradeStage.foundations and Subject.logic in self.subjects:
            self.subjects = [s for s in self.subjects if s != Subject.logic]
        return self

    @model_validator(mode="after")
    def _validate_lesson_resume(self):
        """One resume note per scheduled subject.

        A note for a subject the child isn't doing today can only confuse
        Bede's opener (it would never be read) or, worse, smuggle context
        into a subject the parent has since dropped — so those are filtered
        out here rather than trusted from the client. Duplicates collapse to
        the last one given, which is what a form that appends edits produces.
        """
        scheduled = set(self.subjects)
        by_subject: dict[Subject, LessonResume] = {}
        for entry in self.lesson_resume:
            if entry.subject in scheduled:
                by_subject[entry.subject] = entry
        self.lesson_resume = list(by_subject.values())
        return self


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
    # The child's device clock at login, bucketed client-side (see
    # sessionStore.ts's deriveTimeOfDay) — the server has no reliable way to
    # know the child's timezone otherwise. None for older clients / the
    # sandbox, in which case Bede just doesn't adjust its greeting/prayer
    # framing for time of day.
    local_time_of_day: Optional[Literal["morning", "afternoon", "evening"]] = None
    # The child's device calendar date at login (see sessionStore.ts's
    # deriveLocalDate) — used so the weekly poetry/prayer rotation
    # (services/poetry_catalog.py, services/prayer_catalog.py) picks the
    # week the child's own calendar is actually on, not the server's
    # (which could disagree near a Sunday/Monday boundary if the server
    # runs in a different timezone, e.g. UTC). None for older clients /
    # the sandbox, in which case the catalogs fall back to date.today().
    local_date: Optional[date] = None
    # Minted client-side at startSession() (sessionStore.ts) and sent with
    # every turn. Used ONLY as the key for a session-scoped mastery
    # estimate when settings.retain_mastery_profiles is False — see
    # services/diagnostic_session.py for why the key must be the session
    # rather than the student. Absent from older clients and the sandbox,
    # in which case there is simply nothing to accumulate into.
    session_id: Optional[str] = Field(default=None, max_length=64)


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


class ElevationRequest(BaseModel):
    """Step-up to management-plane privilege (P8, core/elevation.py).

    The parent re-presents the password they already used to log in, plus a
    TOTP code if one is enrolled. Deliberately not a second, separate
    "admin password" — one more secret for a family to lose is a worse
    trade than re-typing the one they already know."""
    password: str
    totp_code: str = ""


class ElevationResponse(BaseModel):
    elevated: bool
    expires_at: str
    # Echoed so the frontend can schedule its own re-prompt rather than
    # discovering the expiry by getting a 403 mid-action.
    ttl_seconds: int


class DeviceInfo(BaseModel):
    """One row from core/device_registry.py — see DeviceRecord's own
    docstring for what this does and does not prove."""
    device_id: str
    first_seen_at: str
    last_seen_at: str
    last_role: str
    last_user_agent: str
    revoked: bool
    revoked_at: Optional[str] = None


class LoginRequest(BaseModel):
    role: Literal["parent", "child", "demo_code"]
    credential: str   # password for parent, PIN for child, generated code for demo_code
    # Chosen at the login screen itself (Login.tsx's English/Español toggle) —
    # per-login, not a per-student or deployment-wide setting. Validated
    # against core.config.SUPPORTED_LOCALES at the route (not here, to avoid
    # this module importing core.config) and embedded as a JWT claim, so the
    # rest of that session's requests carry it automatically via
    # core.deps.require_auth's returned payload. See services/ai_service.py's
    # _locale_directive and services/prayer_catalog.py for where it's read.
    locale: str = "en"
    # P9 device revocation (core/device_registry.py, docs/DEVICE_IDENTITY_
    # DESIGN.md's Option C) — a UUID the browser generates once and persists
    # in localStorage, identifying this physical device across logins.
    # Optional and parent/child-only: a caller driving the API directly (or
    # an older client) that omits this simply gets no device tracking for
    # that login, never a rejected one. Never sent for demo_code — that
    # role is anonymous and already carries its own one-time-code identity.
    # max_length matches DeviceRecord.device_id's String(64) column exactly
    # — without this, an oversized value would reach the DB unvalidated and
    # fail as an unhandled DataError (500) instead of a clean 422 here.
    device_id: Optional[str] = Field(default=None, max_length=64)


class DemoCodeRequest(BaseModel):
    """Optional personalization for a demo session — see POST /auth/demo-code.
    All fields are optional; omitting any keeps the operator's configured
    DEMO_STUDENT_NAME/DEMO_GRADE default for that field (current_unit and
    faith_tradition simply stay unset). student_name, current_unit, and
    faith_tradition are sanitized server-side (see routers/auth.py's
    create_demo_code) since they're free text an anonymous visitor can put
    in front of the model. current_unit is a short "what are we already
    covering at home" note (e.g. "reading Farmer Boy together", "our own
    Ancient Egypt unit") — see core/database.py's DemoCodeUnitNote and
    CLAUDE.md's "Continuing Mastery (demo)" section. faith_tradition is a
    short, optional label for the visiting family's own church tradition
    (e.g. "Baptist", "Catholic", "Non-denominational") — since the demo
    shows every subject, including both Scripture & Bible Study and Saints
    & Catechism, regardless of the visitor's own background (unlike a real
    family, who simply enables the module that fits their own church), this
    lets Bede frame that content consistently with the family's tradition
    rather than assuming one. See core/database.py's DemoCodeFaithNote."""
    student_name: Optional[str] = Field(None, min_length=1, max_length=50)
    grade: Optional[str] = Field(None, max_length=2)
    current_unit: Optional[str] = Field(None, max_length=200)
    faith_tradition: Optional[str] = Field(None, max_length=60)


class DemoCodeResponse(BaseModel):
    """A freshly minted, one-time 6-digit code — see POST /auth/demo-code.
    Exchanged for a JWT via POST /auth/login (role="demo_code")."""
    code: str


class DiagnosticChatRequest(BaseModel):
    """Direct-answer chat for the demo's mastery-tracking preview — same
    shape as SandboxDemoChatRequest, reachable with the same demo_code
    token the child's own session already has (no separate login). See
    routers/diagnostic.py."""
    conversation_history: List[ChatMessage] = []
    message: str = Field(..., min_length=1, max_length=4000)


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


class ChangePasswordRequest(BaseModel):
    """Requires a full parent session (not recovery) — a parent who's
    already logged in changing their password on purpose. See
    ChangePasswordRecoveryRequest for the "I'm locked out" counterpart."""
    current_password: str
    new_password: str = Field(..., min_length=1, max_length=200)


# ── Parent account recovery (routers/recovery.py) ────────────────────────────
# "≥2 of {recovery_secret, totp_code, webauthn_credential}" — exactly which
# fields are set is what determines which factors were attempted; see
# routers/recovery.py's own verify() for the counting logic. All optional
# here since a real request only ever supplies whichever 2 the parent
# actually has.

class RecoveryVerifyRequest(BaseModel):
    # Either shape of the "something you know" factor — a recovery PIN or
    # a recovery code, whichever this parent enrolled (they're mutually
    # exclusive, see services/parent_recovery.py). The backend tries both
    # verify functions; only the one that's actually enrolled can match.
    recovery_secret: Optional[str] = None
    totp_code: Optional[str] = None
    webauthn_credential: Optional[dict] = None


class RecoveryPinEnrollRequest(BaseModel):
    # 6-12 digits — the real strength/pattern check is
    # services/parent_recovery.py's enroll_recovery_pin (pin_is_strong() +
    # its own max-length check); this Field bound just rejects an obviously
    # malformed request before it reaches that logic.
    pin: str = Field(..., min_length=1, max_length=12)


class ChangePasswordRecoveryRequest(BaseModel):
    new_password: str = Field(..., min_length=1, max_length=200)


class SessionSummaryRequest(BaseModel):
    session_config: SessionConfig
    conversation_history: List[ChatMessage]
    subjects_completed: List[Subject]
    duration_minutes: int
    # Same value TutorRequest carries. Only meaningful when the deployment
    # keeps no mastery profile between sessions, where the summary is the
    # ONE moment the session's estimate is reported before being released.
    session_id: Optional[str] = Field(default=None, max_length=64)


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

    "plans" reuses this exact same pipeline for a different intent: a demo
    visitor asking about the full-featured version / monthly-annual plans
    (surfaced from the diagnostic preview's quota-exceeded state) rather
    than product feedback — same operator inbox (FEEDBACK_EMAIL), same
    one-outbound-email-and-nothing-persisted contract, just a different
    category label on the email subject so it's easy to triage at a glance.

    "beta_close" is the demo's own end-of-session "help us improve" prompt
    (DemoSummaryScreen, demo/src/App.tsx) — contact_email here is opt-in and
    explicitly gated behind a parent/guardian affirmation client-side before
    the field is even shown, since unlike the rest of this endpoint's
    traffic, a volunteered email address is unambiguous personal
    information, not an anonymized signal.

    "onboarding" is a real beta family's own one-time intake prompt
    (BetaIntakeModal, homeschool-tutor/src/components) shown once, right
    after a parent completes their very first pod setup — "what are you
    hoping Bede helps with," collected before they've used the product at
    all rather than after, unlike every other category here. Same pipeline,
    same contract; just a distinct subject-line prefix (see
    services/email_service.py's _feedback_prefix) so it doesn't read like
    ordinary in-use feedback.

    "beta_survey" is the beta period's structured instrument — a whole set
    of questions rather than one remark — and is the ONE category with more
    than one delivery channel: the two hosted pages on the marketing site
    (site/survey/, site/educators/) and the in-app BetaSurveyModal all post
    under it, deliberately, so their answers pool into a single pile in the
    operator's inbox instead of three that have to be merged by hand. Which
    channel a given response came from is carried in the message body's own
    leading tag line, not in the category. The questions themselves, and
    the rules governing what a survey here may and may not ask (never rate
    a child, never ask about a child's faith), live in docs/BETA_SURVEY.md,
    which is the source of truth all three channels are checked against.
    """
    category: Literal[
        "cx", "ux", "content_quality", "plans", "other",
        "beta_close", "onboarding", "beta_survey",
    ]
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

# ── Diagnostic engine (mastery profile) ──────────────────────────────────────

class MasteryLevel(str, Enum):
    gap        = "gap"          # P(mastery) < 0.4
    developing = "developing"   # 0.4 <= P < 0.8
    secure     = "secure"       # P >= 0.8

class SkillMasteryView(BaseModel):
    """One sub-skill's rolled-up view for the parent dashboard."""
    skill_id:     str
    label:        str
    domain:       str
    grade_band:   str
    probability:  float = Field(..., ge=0.0, le=1.0)
    level:        MasteryLevel

class DomainMasteryView(BaseModel):
    domain:              str
    average_probability: float = Field(..., ge=0.0, le=1.0)
    level:               MasteryLevel
    skills:              List[SkillMasteryView]

class MasteryProfileSummary(BaseModel):
    """Render-only parent summary. No raw evidence, no transcript."""
    student_name:   str
    subject_area:   str = "mathematics"
    evidence_count: int
    calibration:    bool                       # still in cold-start widening phase
    domains:        List[DomainMasteryView]
    gaps:           List[SkillMasteryView]     # level == gap, worst first
    next_steps:     List[SkillMasteryView]     # KST fringe — learnable now
    updated_at:     str

class ModelUsage(BaseModel):
    """One model's token totals within a UsageSummary — see core/api_usage.py."""
    model:                  str
    input_tokens:           int
    output_tokens:          int
    cache_creation_tokens:  int
    cache_read_tokens:      int
    calls:                  int
    estimated_cost_usd:     float

class UsageSummary(BaseModel):
    """
    Best-effort Anthropic API token/cost estimate for this BYOK deployment
    — never a bill, console.anthropic.com is the authoritative source.
    student_name is None for the household-wide total (GET /admin/status);
    set to a specific student's name for the per-student breakdown
    (GET /admin/usage/{student_name}).
    """
    student_name:         Optional[str] = None
    total_input_tokens:   int
    total_output_tokens:  int
    total_calls:          int
    estimated_cost_usd:   float
    by_model:             List[ModelUsage]

class AgenticLoopStats(BaseModel):
    """
    Best-effort analytics for stream_tutor_response's bounded tool_result
    loop (services/ai_service.py's _MAX_TOOL_LOOP_ROUNDS) — how often a
    turn actually takes more than one model round-trip, and the added
    latency/cost that implies. See core/api_usage.py's get_loop_stats for
    how "which rows belong to one turn" is approximated (a timestamp-gap
    heuristic, not an exact stored value) — every field here inherits
    that same approximation, which is why this is a trend view, not a
    bill or an audit record.
    """
    window_days:                    int
    turns_analyzed:                 int
    multi_round_turns:              int
    multi_round_pct:                float
    avg_rounds_per_turn:            float
    max_rounds_seen:                int
    round_distribution:             Dict[int, int]
    avg_added_latency_seconds:      float
    max_added_latency_seconds:      float
    extra_round_estimated_cost_usd: float


# How a completed piece of work is scored. Three dimensions, all optional
# and all about the WORK PRODUCT rather than about the child — that
# distinction is the whole design (see services/diagnostic/activity.py).
# Scoring what a student produced is ordinary assessment; scoring what a
# student IS would be a claim this app has no standing to make.
#
# Every scale's floor is a real, respectable outcome. There is no "poor"
# quality and no "slow" pace, because an attempt that failed is never
# logged as completed work in the first place, and because a child who
# works deliberately is not thereby working worse.
WORK_QUALITY_LEVELS = ("adequate", "proficient", "exemplary")

# Did this piece of work go beyond the task as set? This is the dimension
# that actually surfaces initiative — a student who answered the question
# and one who answered it and then asked a better one have produced
# different work, and only this field can tell them apart.
WORK_DISTINCTION_LEVELS = ("expected", "noteworthy", "original")

# Observed pace. Deliberately non-pejorative at both ends: "deliberate" is
# a description, not a deficiency, and a child is never shown any of this.
WORK_SPEED_LEVELS = ("deliberate", "steady", "brisk")


class WorkScoreFields(BaseModel):
    """
    The three optional scoring dimensions shared by every silent evidence
    tool. Optional throughout: Bede fills them when it genuinely observed
    enough to judge, and omits them otherwise. A missing score is honest;
    an invented one is not.
    """
    quality:     Optional[Literal["adequate", "proficient", "exemplary"]] = None
    distinction: Optional[Literal["expected", "noteworthy", "original"]] = None
    speed:       Optional[Literal["deliberate", "steady", "brisk"]] = None


class RecordSkillEvidenceInput(WorkScoreFields):
    """Server-side validation of the silent record_skill_evidence tool's
    input (Phase 3). Never leaves the server; not part of any response body."""
    probe_id:   str = Field(..., max_length=80)
    outcome:    Literal["correct", "partial", "incorrect", "hint_dependent"]
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

class RecordLiteracyEvidenceInput(WorkScoreFields):
    """Server-side validation of the silent record_literacy_evidence tool's
    input — see services/diagnostic/literacy.py (reading and spelling,
    grades 3-8). Never leaves the server; not part of any response body.
    `domain` isn't validated against literacy.DOMAINS here for the same
    reason RecordPhonicsEvidenceInput doesn't: a Literal would require
    importing the diagnostic package into the schema module, and
    literacy.apply_evidence already degrades an unrecognized domain to a
    true no-op, so a hallucinated value is harmless — just unpersisted."""
    domain:  str = Field(..., max_length=60)
    outcome: Literal["correct", "partial", "incorrect", "hint_dependent"]


class RecordPhonicsEvidenceInput(WorkScoreFields):
    """Server-side validation of the silent record_phonics_evidence tool's
    input — see services/diagnostic/phonics.py. Never leaves the server;
    not part of any response body. domain isn't validated against
    phonics.DOMAINS here (Literal would require importing the diagnostic
    package into the schema module); services.diagnostic.phonics.
    apply_evidence already degrades an unrecognized domain to a true no-op,
    so a hallucinated value is harmless, just unpersisted."""
    domain:  str = Field(..., max_length=40)
    outcome: Literal["correct", "partial", "incorrect", "hint_dependent"]

class RecordLanguageEvidenceInput(WorkScoreFields):
    """Server-side validation of the silent record_language_evidence tool's
    input — see services/diagnostic/language_exposure.py. Never leaves the
    server; not part of any response body. language isn't validated against
    language_exposure.LANGUAGES here, same reasoning as
    RecordPhonicsEvidenceInput's domain field above: apply_evidence already
    degrades an unrecognized language to a true no-op."""
    language: str = Field(..., max_length=40)
    outcome:  Literal["correct", "partial", "incorrect", "hint_dependent"]
