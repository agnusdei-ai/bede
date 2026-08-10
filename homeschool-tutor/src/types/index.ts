import { Sun, BookOpen, Calculator, Leaf, Globe, PenLine, FlaskConical, Palette, Star, BookMarked, Landmark, Columns3, Scale, Sparkles } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

export type GradeStage = 'K-2' | '3-5' | '6-8'

export type Subject =
  | 'morning_time'
  | 'living_books'
  | 'mathematics'
  | 'nature_study'
  | 'history'
  | 'language_arts'
  | 'science'
  | 'art_music'
  | 'saints'
  | 'scripture'
  | 'latin'
  | 'greek'
  | 'logic'
  | 'free_study'

export interface SessionConfig {
  student_name: string
  grade: string
  grade_stage: GradeStage
  // Biological sex, not "gender identity" — see models/schemas.py's
  // SessionConfig.sex on the backend. Unused/optional on an English-only
  // deployment; required by POST /pod/configs once the deployment's LOCALE
  // is a grammatically gendered language (Spanish, Italian, Polish so far)
  // so Bede can address the student correctly. See docs/LOCALIZATION.md.
  sex?: 'male' | 'female'
  subjects: Subject[]
  lesson_focus?: string
  faith_emphasis?: string
  current_unit?: string
  // Optional, short label for the family's own church tradition (e.g.
  // "Baptist", "Catholic", "Non-denominational") — mirrors the backend's
  // SessionConfig.faith_tradition. Set in ParentSetup.tsx's optional
  // "session context" panel, shown only once Scripture & Bible Study or
  // Saints & Catechism is enabled for that student. Also populated by the
  // demo's own optional intake field (demo/src/App.tsx's CodeScreen), since
  // the demo shows both faith subjects to every visitor regardless of
  // background.
  faith_tradition?: string
  // Parent's preferred Bible translation (see BIBLE_TRANSLATIONS below) —
  // mirrors the backend's SessionConfig.bible_translation. Set in the same
  // ParentSetup.tsx panel as faith_tradition, so Bede's own quoting/
  // paraphrasing of Scripture matches the wording the family already reads
  // at home.
  bible_translation?: string
  // Curriculum publishers/resources the family already uses alongside Bede
  // (see CURRICULUM_RESOURCE_SUGGESTIONS below) — mirrors the backend's
  // SessionConfig.curriculum_resources. Set in the same ParentSetup.tsx
  // panel; Bede aligns terminology/approach where it naturally overlaps,
  // never claiming to reproduce a named publisher's actual content.
  curriculum_resources?: string[]
  // What the PARENT says helps this child — never inferred by Bede, never a
  // diagnosis. Mirrors the backend's SessionConfig.learning_support; see
  // LEARNING_SUPPORT_SUGGESTIONS below and the backend's
  // _learning_support_note for the rules that govern how Bede acts on it.
  learning_support?: string[]
  voice_required?: boolean  // false for mute students — PIN-only auth, no voice passphrase
  // The session's hard stop, in minutes — on by default and there by design
  // (2-hour default, 4-hour maximum; absent = 2 hours, and gradeTimer.ts's
  // effectiveSessionCap clamps whatever is stored). The session concludes
  // automatically when it's reached, and a mandatory 10-minute break runs
  // after every hour of session time regardless of this value.
  session_cap_minutes?: number
  // Parent-set cap on total on-screen tutoring minutes before a mandatory eye-rest
  // break is inserted. null/undefined = no cap beyond the normal grade-based
  // block/break cycle in gradeTimer.ts.
  screen_time_limit_minutes?: number | null
  // Length of the mandatory break once screen_time_limit_minutes is reached.
  // Floor of 30 is enforced in gradeTimer.ts regardless of what's stored here.
  eye_rest_break_minutes?: number
  // Remembers the child's own last choice for Bede's spoken narration (the
  // mute/unmute button in SocraticChat.tsx) — distinct from voice_required
  // above, which is about login voice-biometric verification, not TTS
  // output. Defaults true when absent (configs saved before this field existed).
  voice_narration_enabled?: boolean
  // Parent-side lock on the chat appearance picker (background theme +
  // bubble color). True hides the picker in the child's session — the
  // device keeps whatever look it already has; a parent-role session
  // still sees it. Defaults false/absent for configs saved before this
  // field existed.
  appearance_locked?: boolean
  // Parent's chosen starting point at setup (see CompanionMode below) —
  // how much Bede drives the day versus defers to the family's own
  // books. Purely a behavioral framing (services/ai_service.py's
  // _companion_mode_note); doesn't itself constrain which subjects can
  // be selected. Defaults to 'full_plan' (today's behavior, unchanged)
  // for configs saved before this field existed.
  companion_mode?: CompanionMode
  // ── Term schedule & outcomes ────────────────────────────────────────────
  // Mater Amabilis default is a 3-term (trimester) year; quarterly gives 4.
  term_schedule?: TermSchedule
  current_term?: number
  // Parent's mastery outcomes for the current term: up to 3 topics per core
  // area (keys from CORE_AREAS). Exposure to all is expected across the
  // term; mastery of these named topics is the outcome. Bede records
  // per-topic evidence via assess_narration (term_topic fields below).
  term_mastery_topics?: Partial<Record<CoreArea, string[]>>
  // ── Mastery cycle ───────────────────────────────────────────────────────
  // How far back Progress looks when answering "did this move recently?" —
  // a ROLLING window, not a sprint: nothing resets, nothing rolls over, and
  // no rate is computed across cycles. Mirrors models/schemas.py, where the
  // reasoning lives in full. Default 28 ACTUAL (calendar) days; travel_mode
  // is what unlocks widening it to 3-6 weeks, for a family whose weeks away
  // don't fit the usual evidence into 28 days. Parent-facing only — a child
  // never sees a cycle.
  travel_mode?: boolean
  mastery_cycle_days?: number
  // "Meet me where I am" — the parent's note about where an interrupted
  // lesson stopped, so Bede opens that subject mid-thread instead of
  // introducing it fresh (and without asking the child where they got to).
  // At most one entry per subject, and only for subjects in `subjects`
  // above — the backend drops anything else (models/schemas.py's
  // SessionConfig._validate_lesson_resume).
  lesson_resume?: LessonResume[]
}

// Mirrors homeschool-api/models/schemas.py's LessonResume. `subject` is a
// Subject, not free text: a resume note can only ever point at one of the
// subjects Bede already teaches, never introduce a new topic of its own.
export interface LessonResume {
  subject: Subject
  stopped_at: string
  next_step?: string
  sticking_point?: string
  recorded_on?: string  // ISO YYYY-MM-DD
}

export type TermSchedule = 'trimester' | 'quarterly'

// See models/schemas.py's CompanionMode for the full rationale. Mirrors
// GradeStage's shape: a small, stable string union kept in sync by hand
// with the backend enum, same convention already used throughout this file.
export type CompanionMode = 'book_companion' | 'guided' | 'full_plan'

// Bible translations a parent can pick for SessionConfig.bible_translation —
// mirrors homeschool-api/models/schemas.py's BIBLE_TRANSLATIONS, same
// duplication convention as DEMO_GRADES/VALID_GRADES. Deliberately spans
// both Protestant and Catholic editions — see that constant's own comment.
export const BIBLE_TRANSLATIONS = [
  'KJV', 'NKJV', 'ESV', 'NIV', 'NASB', 'NLT', 'CSB',
  'RSV-CE', 'NABRE', 'NRSV-CE', 'Douay-Rheims',
] as const

// Curriculum publishers commonly used alongside Bede, offered as quick-pick
// Quick-pick suggestions for SessionConfig.learning_support — mirrors
// homeschool-api/models/schemas.py's LEARNING_SUPPORT_SUGGESTIONS. Not a
// closed list: a family's own wording is kept exactly as typed.
//
// Every entry names a change to HOW a lesson is delivered, never to what is
// taught or the standard the work is held to. A parent reading this list
// should come away with "here is what we can do", not a deficit checklist.
export const LEARNING_SUPPORT_SUGGESTIONS = [
  'More time to answer',
  'Shorter passages at a time',
  'Answer out loud instead of writing',
  'Read the passage aloud to them',
  'Break tasks into one step at a time',
  'Frequent short breaks',
  'Repeat instructions before starting',
  'Say numbers and letters clearly, one at a time',
]

// suggestions for SessionConfig.curriculum_resources — mirrors
// homeschool-api/models/schemas.py's CURRICULUM_RESOURCE_SUGGESTIONS. Not a
// closed list — a parent's own free-text entry is kept as typed.
export const CURRICULUM_RESOURCE_SUGGESTIONS = [
  'Memoria Press', 'Classical Academic Press', 'Well-Trained Mind Press',
  'Institute for Excellence in Writing', 'RightStart Mathematics', 'Logic of English',
] as const

// Foundational core areas tracked term-by-term — mirrors
// homeschool-api/models/schemas.py CORE_AREAS.
export type CoreArea =
  | 'phonics_language'
  | 'mathematics'
  | 'reading_literature'
  | 'science'
  | 'writing_composition'

export const CORE_AREAS: Array<{ id: CoreArea; label: string }> = [
  { id: 'phonics_language',    label: 'Phonics & Language' },
  { id: 'mathematics',         label: 'Math' },
  { id: 'reading_literature',  label: 'Reading & Literature' },
  { id: 'science',             label: 'Science' },
  { id: 'writing_composition', label: 'Writing & Composition' },
]

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface VisualAidData {
  id: string
  title: string
  creator: string
  year: string
  wiki_title: string
  description: string
  category: string
}

export interface StreamChunk {
  type: 'text' | 'tool' | 'done' | 'assessment' | 'visual_aid' | 'subject_complete'
  content?: string
  tool?: string
  reason?: 'mastery' | 'frustration'
  data?: { subject: string; total_score: number; adaptive_signal: string }
  visualAid?: VisualAidData
}

export interface SubjectInfo {
  id: Subject
  label: string
  Icon: LucideIcon
  durationMin: number
  // A single hex color, not a Tailwind class string — one hue per subject,
  // used as a left-border accent (SubjectPicker, SubjectDrawer). Matches
  // agnusdei.io's own curriculum-grid color binder exactly: 14 hues evenly
  // spaced around the wheel (25.7° apart, S=0.380, L=0.361 — see
  // site/assets/site.css's ".curriculum .card:nth-child" rules, the source
  // of truth for these values), in the same subject order as the Subject
  // enum on the backend, so a family sees the same subject in the same
  // color whether they're reading the marketing site or using the app.
  color: string
  description: string
}

export const SUBJECTS: SubjectInfo[] = [
  {
    id: 'morning_time',
    label: 'Morning Time',
    Icon: Sun,
    durationMin: 20,
    color: '#7f3939',
    description: 'Bible, hymn, poetry & prayer',
  },
  {
    id: 'living_books',
    label: 'Living Books',
    Icon: BookOpen,
    durationMin: 25,
    color: '#7f5739',
    description: 'Classical literature & narration',
  },
  {
    id: 'mathematics',
    label: 'Mathematics',
    Icon: Calculator,
    durationMin: 20,
    color: '#7f7539',
    description: 'Discovery-based mathematical thinking',
  },
  {
    id: 'nature_study',
    label: 'Nature Study',
    Icon: Leaf,
    durationMin: 20,
    color: '#6b7f39',
    description: 'Observation, wonder & creation',
  },
  {
    id: 'history',
    label: 'History & Geography',
    Icon: Globe,
    durationMin: 20,
    color: '#4d7f39',
    description: 'Story-based history & real places',
  },
  {
    id: 'language_arts',
    label: 'Language Arts',
    Icon: PenLine,
    durationMin: 15,
    color: '#397f43',
    description: 'Narration, copywork & grammar',
  },
  {
    id: 'science',
    label: 'Science',
    Icon: FlaskConical,
    durationMin: 20,
    color: '#397f61',
    description: 'Botany, zoology & earth science',
  },
  {
    id: 'art_music',
    label: 'Art & Music',
    Icon: Palette,
    durationMin: 15,
    color: '#397f7f',
    description: 'Composer & artist study',
  },
  {
    id: 'saints',
    label: 'Saints & Catechism',
    Icon: Star,
    durationMin: 15,
    color: '#39617f',
    description: 'Saints, catechism & virtue formation',
  },
  {
    id: 'scripture',
    label: 'Scripture & Bible Study',
    Icon: BookMarked,
    durationMin: 15,
    color: '#39437f',
    description: 'Bible heroes, memory verses & doctrine',
  },
  {
    id: 'latin',
    label: 'Latin & Christian Foundations',
    Icon: Landmark,
    durationMin: 10,
    color: '#4d397f',
    description: 'Latin rooted in faith, hope & love',
  },
  {
    id: 'greek',
    label: 'Greek & New Testament Foundations',
    Icon: Columns3,
    durationMin: 10,
    color: '#6b397f',
    description: 'The alphabet & the New Testament’s own words',
  },
  {
    // Not offered to K-2 students — see subjectsForStage in ParentSetup.tsx
    // and SessionConfig._validate_logic_stage on the backend.
    id: 'logic',
    label: 'Logic',
    Icon: Scale,
    durationMin: 15,
    color: '#7f3975',
    description: 'Reasoning, argument & clear thinking',
  },
  {
    id: 'free_study',
    label: 'Free Study',
    Icon: Sparkles,
    durationMin: 20,
    color: '#7f3957',
    description: 'Student-directed exploration',
  },
]

export const SUBJECT_MAP: Record<Subject, SubjectInfo> = Object.fromEntries(
  SUBJECTS.map((s) => [s.id, s])
) as Record<Subject, SubjectInfo>

export interface NarrationAssessmentData {
  subject: string
  completeness: number
  sequence: number
  detail: number
  language_quality: number
  synthesis: number
  total_score: number
  concepts_demonstrated: string[]
  misconceptions: string[]
  adaptive_signal: 'advance' | 'repeat' | 'review_prerequisite'
  bede_observation: string
  assessed_at: string
  // Term-outcome evidence — present only when the exchange demonstrated one
  // of the parent's term mastery topics (see SessionConfig.term_mastery_topics).
  term_topic?: string | null
  term_topic_level?: 'introduced' | 'developing' | 'mastered' | null
}

export interface LearnerProfileData {
  trivium_stage: 'grammar' | 'logic' | 'rhetoric'
  processing_style: 'visual' | 'auditory' | 'reading_writing' | 'kinesthetic'
  narration_mode: 'sequential' | 'associative'
  attention_profile: 'short_blocks' | 'sustained' | 'variable'
  session_count_assessed: number
  bede_profile_notes: string
  assessed_at: string
}

// Parent-only (unlike LearnerProfileData, which a child token can also
// read) — see homeschool-api/core/database.py's LearnerBehaviorCheck for
// what this is and isn't. Only ever present while processing_style is
// currently one of the three TRACKABLE_STYLES (kinesthetic, reading_writing,
// visual — see routers/narration.py); null otherwise, including for
// auditory, which gets a prompt nudge but no counter (no honest tool-level
// signal exists for it). Deliberately NOT a claim that any of these labels
// improves learning — only a check that Bede's own prompted adaptation is
// actually happening. count's meaning depends on the CURRENT
// processing_style (see behaviorCheckLine in pages/Progress.tsx).
export interface LearnerBehaviorCheck {
  count: number
  since: string
}

// Real, persisted (mastery_profiles) diagnostic summary — see
// homeschool-api/services/diagnostic/get_mastery_summary. Same shape as
// the public demo's own preview (demo/src/api.ts's MasteryProfileSummary),
// but this one reflects the student's whole history, not one session.
export type MasteryLevel = 'gap' | 'developing' | 'secure'

export interface SkillMasteryView {
  skill_id: string
  label: string
  domain: string
  grade_band: string
  probability: number
  level: MasteryLevel
}

export interface DomainMasteryView {
  domain: string
  average_probability: number
  level: MasteryLevel
  skills: SkillMasteryView[]
}

export interface MasteryProfileSummary {
  student_name: string
  subject_area: string
  evidence_count: number
  calibration: boolean
  domains: DomainMasteryView[]
  gaps: SkillMasteryView[]
  next_steps: SkillMasteryView[]
  updated_at: string
}

// Best-effort Anthropic API token/cost estimate for this BYOK deployment
// (see homeschool-api/core/api_usage.py) — never a bill, console.anthropic.com
// is the authoritative source. student_name is null for the household-wide
// total (GET /admin/status); set for a specific student's own breakdown
// (GET /admin/usage/{student_name}).
export interface ModelUsage {
  model: string
  input_tokens: number
  output_tokens: number
  cache_creation_tokens: number
  cache_read_tokens: number
  calls: number
  estimated_cost_usd: number
}

export interface UsageSummary {
  student_name: string | null
  total_input_tokens: number
  total_output_tokens: number
  total_calls: number
  estimated_cost_usd: number
  by_model: ModelUsage[]
}

// Best-effort analytics for stream_tutor_response's bounded tool_result
// loop (see homeschool-api/core/api_usage.py's get_loop_stats and
// CLAUDE.md's "Bounded tool_result loop" section) — GET
// /admin/agentic-loop-stats. Every field here inherits a timestamp-gap
// APPROXIMATION of which API calls belong to the same turn, not an exact
// stored value — AgenticLoopInsights.tsx surfaces that caveat rather than
// presenting these as precise counts.
export interface AgenticLoopStats {
  window_days: number
  turns_analyzed: number
  multi_round_turns: number
  multi_round_pct: number
  avg_rounds_per_turn: number
  max_rounds_seen: number
  round_distribution: Record<number, number>
  avg_added_latency_seconds: number
  max_added_latency_seconds: number
  extra_round_estimated_cost_usd: number
}

// Mirrors homeschool-api/core/licensing.py's LicenseInfo, as surfaced by
// GET /admin/status. Null on the wire (see routers/admin.py) when
// LICENSE_KEY is unset — dev/self-managed mode, or the operator's public
// demo (Settings.is_demo_deployment exempts it from needing one). A real
// family production deployment is REQUIRED to have one, enforced by the
// license gate (core/license_state.py + LicenseGateMiddleware) rather
// than a boot refusal — so a gated instance can report ok:false with a
// problem message and no license identity at all. `source` says where
// the effective key came from: 'db' = applied in-app (renewal), 'env' =
// the key the deployment was installed with.
export interface LicenseStatus {
  ok: boolean
  required: boolean
  source: 'db' | 'env' | 'none'
  problem: string | null
  tier?: 'trial' | 'core' | 'coop'
  licensee?: string
  seats?: number
  expires?: string | null
  days_remaining?: number | null
  is_expired?: boolean
}

export type AIProviderName = 'local' | 'openai' | 'mistral' | 'anthropic'

// Mirrors homeschool-api/routers/admin.py's GET/POST /admin/ai-provider(/secondary) —
// which adapters (homeschool-api/services/adapters/) actually have
// credentials configured in this deployment's .env, and which one is
// primary right now. `override`/`secondary_override` are set only when a
// parent has picked one from this card (homeschool-api/core/provider_state.py
// — DB value wins over env, live, no restart); `primary`/`secondary` are
// always the adapters that would actually serve the next tutoring turn (and
// its first failover), override or not.
export interface AIProviderStatus {
  known: AIProviderName[]
  configured: AIProviderName[]
  env_order: AIProviderName[]
  effective_order: AIProviderName[]
  primary: AIProviderName | null
  secondary: AIProviderName | null
  override: AIProviderName | null
  secondary_override: AIProviderName | null
  forced: AIProviderName | null
}


// ── The work ledger ──────────────────────────────────────────────────────
//
// Mirrors services/diagnostic/activity.py. Deliberately carries no
// probability, level, average, or rank: the ledger records what a student
// DID, while the mastery summaries above record what Bede infers they can
// do. Keeping the two shapes visibly different is part of keeping the two
// ideas apart.

export type WorkAssistance = 'unaided' | 'with_a_hint' | 'with_help'
export type WorkQuality = 'adequate' | 'proficient' | 'exemplary'
export type WorkDistinction = 'expected' | 'noteworthy' | 'original'
export type WorkSpeed = 'deliberate' | 'steady' | 'brisk'

export interface WorkLedgerSkill {
  skill_id: string
  label: string
  subject_area: string
  completed: number
  unaided: number
  with_a_hint: number
  with_help: number
  /** How many of `completed` carried at least one score. */
  scored: number
  quality: Record<WorkQuality, number>
  distinction: Record<WorkDistinction, number>
  speed: Record<WorkSpeed, number>
  last_worked: string | null
}

/**
 * Counts of work done exemplarily, taken beyond the task, and done
 * briskly. Deliberately has no verdict, threshold, or type field — whether
 * a child is a "learning entrepreneur" is not a call the software makes.
 */
export interface InitiativeSignal {
  student_name: string
  scored_activities: number
  exemplary: number
  beyond_the_task: number
  brisk: number
  standout_skills: Array<{
    skill_id: string
    label: string
    exemplary: number
    beyond_the_task: number
  }>
}

export interface WorkLedger {
  student_name: string
  since_days: number
  total: number
  skills: WorkLedgerSkill[]
  initiative: InitiativeSignal
}

/**
 * The pod roster. Note the shape: keyed by SKILL, with the students who
 * have worked it nested inside. A per-student shape would invite a
 * leaderboard; this one can only answer "who has done this work".
 */
export interface PodWorkRoster {
  since_days: number
  skills: Array<{
    skill_id: string
    label: string
    subject_area: string
    worked_by: Array<{
      student_name: string
      completed: number
      unaided: number
      last_worked: string | null
    }>
  }>
}
