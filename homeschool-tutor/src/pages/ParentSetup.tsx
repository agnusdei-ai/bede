import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router'
import { useTranslation, Trans } from 'react-i18next'
import { Plus, Trash2, Mic, CheckCircle, ChevronDown, ChevronUp, Database, Shield, Users, Loader2, DollarSign, KeyRound, AlertTriangle, BookMarked, X } from 'lucide-react'
import { useSessionStore } from '../store/sessionStore'
import type { Subject, GradeStage, SessionConfig, TermSchedule, CoreArea, CompanionMode, LessonResume } from '../types'
import { SUBJECTS, SUBJECT_MAP, CORE_AREAS, BIBLE_TRANSLATIONS, CURRICULUM_RESOURCE_SUGGESTIONS } from '../types'
import { capForStudyMinutes, studyMinutesWithinCap } from '../utils/gradeTimer'
import { DEFAULT_MASTERY_CYCLE_DAYS } from '../utils/masteryCycle'
import VoiceEnrollment from '../components/VoiceEnrollment'
import ParentSecuritySettings from '../components/ParentSecuritySettings'
import DeviceSettings from '../components/DeviceSettings'
import LicenseSettings from '../components/LicenseSettings'
import AIProviderSettings from '../components/AIProviderSettings'
import AgenticLoopInsights from '../components/AgenticLoopInsights'
import { listVoiceProfiles } from '../services/voiceApi'
import { fetchSystemStatus, isFeedbackEnabled, listPodConfigs, savePodConfigs, type SystemStatus } from '../services/api'
import BetaIntakeModal from '../components/BetaIntakeModal'

// label is a numeric grade range, not a translated word — same across
// locales. descriptionKey resolves through i18n at render time since this
// array is module-level (no hook context to call t() here directly).
const GRADE_STAGES: Array<{ label: string; value: GradeStage; descriptionKey: string; emoji: string }> = [
  { label: 'K–2', value: 'K-2', descriptionKey: 'parentSetup.stageDescGrammar', emoji: '🌱' },
  { label: '3–5', value: '3-5', descriptionKey: 'parentSetup.stageDescLogic', emoji: '🔭' },
  { label: '6–8', value: '6-8', descriptionKey: 'parentSetup.stageDescRhetoric', emoji: '🎓' },
]

// One "pick up where we left off" row in the form. `subject` is '' until the
// parent picks one, and the picker only ever offers subjects already
// selected for this student — a resume note can never introduce a topic
// outside what Bede teaches (the backend enforces the same thing; see
// models/schemas.py's SessionConfig._validate_lesson_resume).
interface ResumeForm {
  subject: Subject | ''
  stopped_at: string
  next_step: string
  sticking_point: string
  recorded_on: string
}

const blankResume = (): ResumeForm => ({
  subject: '',
  stopped_at: '',
  next_step: '',
  sticking_point: '',
  recorded_on: '',
})

// Subjects a family opts INTO, never receives by default. Everything else
// is the Mater Amabilis core rotation that "Full Daily Plan" has always
// meant. The classical languages and Logic are real electives most
// families won't run: auto-selecting them would silently add 35 minutes to
// every new student's day and put Latin in front of a family that never
// asked for it, which is the opposite of the opt-in promise those subjects
// are documented with. `free_study` was already excluded for its own
// reasons and keeps that behavior.
const ELECTIVE_SUBJECTS: Subject[] = ['latin', 'greek', 'logic', 'free_study']
const DEFAULT_SUBJECTS: Subject[] = SUBJECTS
  .filter((s) => !ELECTIVE_SUBJECTS.includes(s.id))
  .map((s) => s.id)

// Logic is the app's only stage-gated subject: formal reasoning before the
// Logic stage is the premature abstraction classical education warns
// against, so a K-2 student is never offered the card. The backend drops
// it independently (SessionConfig._validate_logic_stage) — this is the
// UI's half of that gate, not the whole of it.
const subjectsForStage = (stage: GradeStage) =>
  SUBJECTS.filter((s) => s.id !== 'logic' || stage !== 'K-2')

// A "start here" preset, not a lock — picking one fills in selected_subjects
// and session_cap_minutes as sensible defaults; both remain freely editable
// afterward via their own controls below. Meets a family where they are:
// new to homeschooling or easing into AI deliberately (book_companion),
// wanting a bit more structure (guided), or ready for the full rotation
// (full_plan — matches blankStudent()'s existing default exactly, so
// picking it after another preset restores today's original behavior).
// See models/schemas.py's CompanionMode for the backend-side rationale —
// full_plan also changes nothing about Bede's own tutoring prompt; the
// other two lightly reframe it (services/ai_service.py's _companion_mode_note).
// Minutes of instruction a subject list actually asks for.
const studyMinutesFor = (subjects: Subject[]) =>
  subjects.reduce((acc, id) => acc + (SUBJECT_MAP[id]?.durationMin ?? 0), 0)

const COMPANION_MODES: Array<{
  value: CompanionMode
  labelKey: string
  descriptionKey: string
  emoji: string
  subjects: Subject[]
  sessionCapMinutes: number
}> = [
  // Mathematics is in EVERY preset, deliberately. It is foundational, and
  // it is also the only subject carrying Bede's full diagnostic engine
  // (services/diagnostic/) — a family on a lighter preset was previously
  // getting no math and therefore no real mastery signal at all, which
  // made "mastery-based outcome" untrue for exactly the families most
  // likely to need the reassurance.
  //
  // Every cap below is DERIVED from its own subject list rather than typed
  // in, so intent and capacity are equal by construction. Before this they
  // were independent literals and had silently diverged: full_plan asked
  // for 185 minutes of subjects inside a 120-minute cap.
  {
    value: 'book_companion',
    labelKey: 'parentSetup.companionModeBookCompanion',
    descriptionKey: 'parentSetup.companionModeBookCompanionDesc',
    emoji: '📖',
    subjects: ['living_books', 'morning_time', 'mathematics'],
    sessionCapMinutes: capForStudyMinutes(studyMinutesFor(['living_books', 'morning_time', 'mathematics'])),
  },
  {
    value: 'guided',
    labelKey: 'parentSetup.companionModeGuided',
    descriptionKey: 'parentSetup.companionModeGuidedDesc',
    emoji: '🧭',
    subjects: ['living_books', 'morning_time', 'mathematics', 'language_arts', 'nature_study'],
    sessionCapMinutes: capForStudyMinutes(
      studyMinutesFor(['living_books', 'morning_time', 'mathematics', 'language_arts', 'nature_study']),
    ),
  },
  {
    value: 'full_plan',
    labelKey: 'parentSetup.companionModeFullPlan',
    descriptionKey: 'parentSetup.companionModeFullPlanDesc',
    emoji: '🗓️',
    subjects: DEFAULT_SUBJECTS,
    sessionCapMinutes: capForStudyMinutes(studyMinutesFor(DEFAULT_SUBJECTS)),
  },
]

interface StudentForm {
  student_name: string
  grade: string
  grade_stage: GradeStage
  // Biological sex, not "gender identity" — see types/index.ts's
  // SessionConfig.sex. '' means unset; only required when systemStatus's
  // locale is a grammatically gendered language (see requireSex below).
  sex: '' | 'male' | 'female'
  companion_mode: CompanionMode
  selected_subjects: Subject[]
  lesson_focus: string
  faith_emphasis: string
  current_unit: string
  faith_tradition: string
  bible_translation: string
  // Comma-separated in the form, same convention as term_topics; parsed to
  // string[] on save (up to 6 — see models/schemas.py's
  // _validate_curriculum_resources).
  curriculum_resources: string
  voice_required: boolean
  appearance_locked: boolean
  session_cap_minutes: number
  screen_time_limit_enabled: boolean
  screen_time_limit_minutes: number
  eye_rest_break_minutes: number
  term_schedule: TermSchedule
  current_term: number
  // Mastery-cycle window — how far back Progress looks when saying whether
  // a term topic moved. travel_mode is what unlocks changing it; see
  // models/schemas.py and utils/masteryCycle.ts for why it is a rolling
  // window rather than a sprint.
  travel_mode: boolean
  mastery_cycle_days: number
  // Comma-separated per area in the form; parsed to string[] on save.
  term_topics: Record<CoreArea, string>
  // Where each interrupted subject left off — see ResumeForm above.
  lesson_resume: ResumeForm[]
  // Not editable here: this is the child's own mute/unmute choice for
  // Bede's narration (PATCH /pod/configs/{name}/voice-narration). Carried
  // through the form only so re-saving the pod doesn't silently reset it.
  voice_narration_enabled: boolean
  expandedContext: boolean
  showEnrollment: boolean
}

const blankStudent = (): StudentForm => ({
  student_name: '',
  grade: '',
  grade_stage: '3-5',
  sex: '',
  companion_mode: 'full_plan',
  selected_subjects: DEFAULT_SUBJECTS,
  lesson_focus: '',
  faith_emphasis: '',
  current_unit: '',
  faith_tradition: '',
  bible_translation: '',
  curriculum_resources: '',
  voice_required: true,
  appearance_locked: false,
  // Derived from DEFAULT_SUBJECTS, not a literal — a new student's session
  // must actually hold the plan they're given. A saved config keeps
  // whatever the parent chose (see formFromConfig's own fallback).
  session_cap_minutes: capForStudyMinutes(studyMinutesFor(DEFAULT_SUBJECTS)),
  screen_time_limit_enabled: false,
  screen_time_limit_minutes: 90,
  eye_rest_break_minutes: 30,
  term_schedule: 'trimester',
  current_term: 1,
  travel_mode: false,
  mastery_cycle_days: DEFAULT_MASTERY_CYCLE_DAYS,
  term_topics: {
    phonics_language: '', mathematics: '', reading_literature: '',
    science: '', writing_composition: '',
  },
  lesson_resume: [],
  voice_narration_enabled: true,
  expandedContext: false,
  showEnrollment: false,
})

// Rebuilds the form from a config already saved on the server, so a parent
// coming back the next day edits their existing plan — and last session's
// resume notes — instead of retyping the pod from a blank page.
const formFromConfig = (c: SessionConfig): StudentForm => {
  const blank = blankStudent()
  return {
    ...blank,
    student_name: c.student_name,
    grade: c.grade,
    grade_stage: c.grade_stage,
    sex: c.sex ?? '',
    selected_subjects: c.subjects,
    lesson_focus: c.lesson_focus ?? '',
    faith_emphasis: c.faith_emphasis ?? '',
    current_unit: c.current_unit ?? '',
    faith_tradition: c.faith_tradition ?? '',
    bible_translation: c.bible_translation ?? '',
    curriculum_resources: (c.curriculum_resources ?? []).join(', '),
    voice_required: c.voice_required ?? true,
    appearance_locked: c.appearance_locked ?? false,
    session_cap_minutes: c.session_cap_minutes ?? 120,
    screen_time_limit_enabled: c.screen_time_limit_minutes != null,
    screen_time_limit_minutes: c.screen_time_limit_minutes ?? 90,
    eye_rest_break_minutes: c.eye_rest_break_minutes ?? 30,
    term_schedule: c.term_schedule ?? 'trimester',
    current_term: c.current_term ?? 1,
    travel_mode: c.travel_mode ?? false,
    mastery_cycle_days: c.mastery_cycle_days ?? DEFAULT_MASTERY_CYCLE_DAYS,
    term_topics: {
      ...blank.term_topics,
      ...Object.fromEntries(
        CORE_AREAS.map(({ id }) => [id, (c.term_mastery_topics?.[id] ?? []).join(', ')]),
      ),
    },
    lesson_resume: (c.lesson_resume ?? []).map((r) => ({
      subject: r.subject,
      stopped_at: r.stopped_at,
      next_step: r.next_step ?? '',
      sticking_point: r.sticking_point ?? '',
      recorded_on: r.recorded_on ?? '',
    })),
    voice_narration_enabled: c.voice_narration_enabled ?? true,
    // Already-filled context shouldn't hide behind a collapsed toggle.
    expandedContext: !!(c.lesson_focus || c.faith_emphasis || c.current_unit || c.faith_tradition || c.bible_translation || c.curriculum_resources?.length),
  }
}

export default function ParentSetup() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { setSessionConfig, startSession, podStudents, setPodStudents, logout, token } = useSessionStore()

  const [students, setStudents] = useState<StudentForm[]>([blankStudent()])
  const [enrolledProfiles, setEnrolledProfiles] = useState<string[]>([])
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null)
  const [statusError, setStatusError] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [hitlConsent, setHitlConsent] = useState(false)
  const [feedbackEnabled, setFeedbackEnabled] = useState(false)
  // Set only when this save was this family's very first-ever pod (see
  // handleSavePod) — holds the saved configs so BetaIntakeModal's onDone can
  // finish the same navigation handleSavePod would have done immediately,
  // once the one-time intake prompt is skipped or submitted.
  const [pendingFirstSaveConfigs, setPendingFirstSaveConfigs] = useState<SessionConfig[] | null>(null)

  useEffect(() => {
    if (!token) return
    listVoiceProfiles(token).then(setEnrolledProfiles).catch(() => {})
    fetchSystemStatus(token)
      .then(setSystemStatus)
      .catch(() => setStatusError(true))
    isFeedbackEnabled().then(setFeedbackEnabled)
    // Load the pod the parent already saved, so this page opens on their
    // existing plan (resume notes included) rather than a blank form. The
    // functional update is the guard against clobbering anything typed
    // while the request was in flight; failure just leaves the blank form.
    listPodConfigs(token)
      .then((configs) => {
        if (!configs.length) return
        setStudents((prev) =>
          prev.length === 1 && !prev[0].student_name.trim() && !prev[0].grade.trim()
            ? configs.map(formFromConfig)
            : prev,
        )
      })
      .catch(() => {})
  }, [token])

  const isEnrolled = (name: string) =>
    enrolledProfiles.some((p) => p.toLowerCase() === name.toLowerCase())

  const update = (i: number, patch: Partial<StudentForm>) =>
    setStudents((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)))

  const toggleSubject = (i: number, id: Subject) => {
    const s = students[i]
    update(i, {
      selected_subjects: s.selected_subjects.includes(id)
        ? s.selected_subjects.filter((x) => x !== id)
        : [...s.selected_subjects, id],
    })
  }

  const addStudent = () => setStudents((prev) => [...prev, blankStudent()])
  const removeStudent = (i: number) =>
    setStudents((prev) => prev.filter((_, idx) => idx !== i))

  // Every locale this deployment currently supports (Spanish, Italian,
  // Polish) is a grammatically gendered language, so a non-English locale
  // means Bede needs to know each student's sex to address them correctly
  // — see docs/LOCALIZATION.md. An English-only deployment never asks.
  const requireSex = !!systemStatus?.locale && systemStatus.locale !== 'en'

  const canSave =
    hitlConsent &&
    students.length > 0 &&
    students.every((s) =>
      s.student_name.trim() && s.grade.trim() && s.selected_subjects.length > 0 &&
      (!requireSex || s.sex)
    )

  const handleSavePod = async () => {
    if (!canSave || !token) return
    setSaving(true)
    setSaveError('')
    const configs: SessionConfig[] = students.map((s) => ({
      student_name: s.student_name.trim(),
      grade: s.grade.trim(),
      grade_stage: s.grade_stage,
      sex: s.sex || undefined,
      subjects: s.selected_subjects,
      lesson_focus: s.lesson_focus.trim() || undefined,
      faith_emphasis: s.faith_emphasis.trim() || undefined,
      current_unit: s.current_unit.trim() || undefined,
      faith_tradition: s.faith_tradition.trim() || undefined,
      bible_translation: s.bible_translation.trim() || undefined,
      curriculum_resources: s.curriculum_resources.split(',').map((r) => r.trim()).filter(Boolean).slice(0, 6),
      voice_required: s.voice_required,
      appearance_locked: s.appearance_locked,
      companion_mode: s.companion_mode,
      session_cap_minutes: Math.max(30, Math.min(240, s.session_cap_minutes)),
      screen_time_limit_minutes: s.screen_time_limit_enabled ? s.screen_time_limit_minutes : null,
      eye_rest_break_minutes: Math.max(30, s.eye_rest_break_minutes),
      term_schedule: s.term_schedule,
      current_term: Math.min(s.current_term, s.term_schedule === 'trimester' ? 3 : 4),
      travel_mode: s.travel_mode,
      // The backend validator is the authority here (it forces the default
      // back when travel mode is off, and clamps to 3-6 weeks when it is on);
      // sending the form value unmodified keeps one source of truth.
      mastery_cycle_days: s.mastery_cycle_days,
      term_mastery_topics: Object.fromEntries(
        CORE_AREAS.map(({ id }) => [
          id,
          s.term_topics[id].split(',').map((t) => t.trim()).filter(Boolean).slice(0, 3),
        ]).filter(([, topics]) => (topics as string[]).length > 0),
      ),
      voice_narration_enabled: s.voice_narration_enabled,
      // Only complete rows for a subject this student is actually doing
      // today — a half-filled row is dropped rather than saved as an empty
      // resume note. The backend re-checks both (schemas.py).
      lesson_resume: s.lesson_resume
        .filter((r): r is ResumeForm & { subject: Subject } =>
          !!r.subject && !!r.stopped_at.trim() && s.selected_subjects.includes(r.subject as Subject))
        .map((r): LessonResume => ({
          subject: r.subject,
          stopped_at: r.stopped_at.trim().slice(0, 300),
          next_step: r.next_step.trim().slice(0, 300) || undefined,
          sticking_point: r.sticking_point.trim().slice(0, 300) || undefined,
          recorded_on: r.recorded_on || undefined,
        })),
    }))
    // Capture BEFORE savePodConfigs/setPodStudents below overwrite it — this
    // is the one moment that can tell "first pod this family has ever
    // created" from "adding another student to an existing pod."
    const isFirstEverPod = podStudents.length === 0
    try {
      await savePodConfigs(token, configs)
      setPodStudents(configs)
      if (isFirstEverPod && feedbackEnabled) {
        // Hold off on navigating — BetaIntakeModal's onDone finishes this
        // exact navigation once the one-time prompt is skipped or sent.
        setPendingFirstSaveConfigs(configs)
      } else {
        proceedAfterSave(configs)
      }
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : t('parentSetup.saveFailed'))
    } finally {
      setSaving(false)
    }
  }

  // Single-student shortcut: start session directly
  const proceedAfterSave = (configs: SessionConfig[]) => {
    if (configs.length === 1) {
      setSessionConfig(configs[0])
      startSession()
      navigate('/session')
    } else {
      navigate('/pod')
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-parchment-50 via-parchment-50 to-navy-50/40 p-4 md:p-8">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="flex justify-between items-center mb-8">
          <div>
            <div className="flex items-center gap-3">
              <img src="/bede-icon.webp" alt="Bede" className="w-9 h-9 rounded-full object-cover" />
              <h1 className="text-2xl font-display font-bold text-gray-800">{t('parentSetup.title')}</h1>
            </div>
            <p className="text-sm text-gray-500 mt-1">{t('parentSetup.subtitle')}</p>
          </div>
          <button onClick={logout} className="text-xs text-gray-500 hover:text-gray-700 underline transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-400 rounded">
            {t('parentSetup.logOut')}
          </button>
        </div>

        {/* System status */}
        <div className={`rounded-xl border px-4 py-3 mb-6 flex items-center gap-4 flex-wrap text-xs ${
          statusError
            ? 'border-red-200 bg-red-50 text-red-700'
            : systemStatus
            ? 'border-green-200 bg-green-50 text-green-800'
            : 'border-gray-200 bg-gray-50 text-gray-500'
        }`}>
          {statusError ? (
            <span className="flex items-center gap-1.5"><Database size={13} /> {t('parentSetup.cannotReachServer')}</span>
          ) : systemStatus ? (
            <>
              <span className="flex items-center gap-1.5 font-medium"><Database size={13} /> {t('parentSetup.dbConnected')}</span>
              <span className="flex items-center gap-1.5"><Shield size={13} /> {systemStatus.encryption}</span>
              <span className="flex items-center gap-1.5">
                <Users size={13} />
                {systemStatus.voice_profiles_enrolled === 0
                  ? t('parentSetup.noVoicesEnrolled')
                  : t('parentSetup.voicesEnrolled', { count: systemStatus.voice_profiles_enrolled })}
              </span>
              <span className="flex items-center gap-1.5" title={t('parentSetup.usageEstimateTooltip')}>
                <DollarSign size={13} />
                {t('parentSetup.usageEstimate', { cost: systemStatus.usage.estimated_cost_usd.toFixed(2) })}
              </span>
              {systemStatus.license && (
                <span
                  className={`flex items-center gap-1.5 ${
                    systemStatus.license.tier === 'trial' &&
                    systemStatus.license.days_remaining != null &&
                    systemStatus.license.days_remaining <= 7
                      ? 'text-amber-700 font-medium'
                      : ''
                  }`}
                  title={t('parentSetup.licenseTooltip', { licensee: systemStatus.license.licensee, seats: systemStatus.license.seats })}
                >
                  {systemStatus.license.tier === 'trial' &&
                  systemStatus.license.days_remaining != null &&
                  systemStatus.license.days_remaining <= 7 ? (
                    <AlertTriangle size={13} />
                  ) : (
                    <KeyRound size={13} />
                  )}
                  {systemStatus.license.tier === 'trial'
                    ? systemStatus.license.days_remaining != null && systemStatus.license.days_remaining >= 0
                      ? t('parentSetup.trialDaysLeft', { count: systemStatus.license.days_remaining })
                      : t('parentSetup.trialExpired')
                    : systemStatus.license.tier === 'coop' ? t('parentSetup.coopLicense') : t('parentSetup.coreLicense')}
                </span>
              )}
            </>
          ) : (
            <span>{t('parentSetup.checkingStatus')}</span>
          )}
        </div>

        <ParentSecuritySettings token={token!} />
        <DeviceSettings token={token!} />
        <LicenseSettings token={token!} />
        <AIProviderSettings token={token!} />
        <AgenticLoopInsights token={token!} />

        {/* Student cards */}
        <div className="space-y-4">
          {students.map((student, i) => (
            <StudentCard
              key={i}
              index={i}
              student={student}
              total={students.length}
              isEnrolled={isEnrolled(student.student_name.trim())}
              requireSex={requireSex}
              onUpdate={(patch) => update(i, patch)}
              onToggleSubject={(id) => toggleSubject(i, id)}
              onEnrolled={() => listVoiceProfiles(token!).then(setEnrolledProfiles).catch(() => {})}
              onRemove={() => removeStudent(i)}
            />
          ))}
        </div>

        {/* Add student */}
        {students.length < 8 && (
          <button
            onClick={addStudent}
            className="mt-4 w-full py-3 border-2 border-dashed border-navy-300 rounded-xl text-navy-600 hover:border-navy-400 hover:bg-navy-50 transition-colors flex items-center justify-center gap-2 text-sm font-medium"
          >
            <Plus size={16} /> {t('parentSetup.addAnotherStudent')}
          </button>
        )}

        {/* Parent HITL consent acknowledgment */}
        <label className="mt-6 flex items-start gap-3 cursor-pointer group">
          <input
            type="checkbox"
            checked={hitlConsent}
            onChange={(e) => setHitlConsent(e.target.checked)}
            className="mt-0.5 w-4 h-4 accent-navy-600 flex-shrink-0"
          />
          <span className="text-xs text-gray-600 leading-relaxed">
            <Trans i18nKey="parentSetup.hitlConsent" components={{ strong: <strong /> }} />
          </span>
        </label>

        {/* Save */}
        {saveError && (
          <p className="mt-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
            {saveError}
          </p>
        )}
        <button
          onClick={handleSavePod}
          disabled={!canSave || saving}
          className="mt-6 w-full py-4 bg-navy-500 text-white rounded-xl font-semibold text-base hover:bg-navy-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
        >
          {saving ? (
            <><Loader2 size={18} className="animate-spin" /> {t('parentSetup.saving')}</>
          ) : students.length === 1 ? (
            <>{t('parentSetup.beginSession')}</>
          ) : (
            <>{t('parentSetup.openPodDashboard', { count: students.length })}</>
          )}
        </button>
      </div>

      {pendingFirstSaveConfigs && token && (
        <BetaIntakeModal
          token={token}
          onDone={() => {
            const configs = pendingFirstSaveConfigs
            setPendingFirstSaveConfigs(null)
            proceedAfterSave(configs)
          }}
        />
      )}
    </div>
  )
}

interface StudentCardProps {
  index: number
  student: StudentForm
  total: number
  isEnrolled: boolean
  requireSex: boolean
  onUpdate: (patch: Partial<StudentForm>) => void
  onToggleSubject: (id: Subject) => void
  onEnrolled: () => void
  onRemove: () => void
}

function StudentCard({
  index, student, total, isEnrolled, requireSex,
  onUpdate, onToggleSubject, onEnrolled, onRemove,
}: StudentCardProps) {
  const { t } = useTranslation()
  // Both the grid and the minutes total read from this, so a student moved
  // down to K-2 after picking Logic stops showing it AND stops being
  // billed 15 minutes for a subject the backend will drop on save.
  const availableSubjects = subjectsForStage(student.grade_stage)
  const totalMin = student.selected_subjects.reduce((acc, s) => {
    const info = availableSubjects.find((x) => x.id === s)
    return acc + (info?.durationMin ?? 0)
  }, 0)
  // Intent vs. capacity, reconciled in front of the parent rather than left
  // for the timer to resolve by hard-stopping mid-subject. `totalMin` is
  // instruction time; the cap is wall-clock and includes the mandatory break
  // each hour, so the two are never directly comparable — see
  // studyMinutesWithinCap in utils/gradeTimer.ts.
  const availableStudyMin = studyMinutesWithinCap(student.session_cap_minutes)
  const overSubscribedBy = Math.max(0, totalMin - availableStudyMin)
  const capNeededForPlan = capForStudyMinutes(totalMin)

  const label = student.student_name.trim() || t('parentSetup.studentFallbackLabel', { n: index + 1 })

  const addResume = () => onUpdate({ lesson_resume: [...student.lesson_resume, blankResume()] })
  const removeResume = (ri: number) =>
    onUpdate({ lesson_resume: student.lesson_resume.filter((_, k) => k !== ri) })
  const updateResume = (ri: number, patch: Partial<ResumeForm>) =>
    onUpdate({
      lesson_resume: student.lesson_resume.map((r, k) => (k === ri ? { ...r, ...patch } : r)),
    })

  return (
    <div className="bg-white rounded-xl border border-navy-100 shadow-sm overflow-hidden">
      {/* Card header */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100">
        <div className="w-8 h-8 rounded-full bg-navy-100 flex items-center justify-center text-navy-700 font-semibold text-sm flex-shrink-0">
          {index + 1}
        </div>
        <span className="font-semibold text-gray-800 flex-1 truncate">{label}</span>
        {total > 1 && (
          <button
            onClick={onRemove}
            className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
            title={t('parentSetup.removeStudent')}
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>

      <div className="p-5 space-y-5">
        {/* Name + grade */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">{t('parentSetup.studentsName')}</label>
            <input
              type="text"
              value={student.student_name}
              onChange={(e) => onUpdate({ student_name: e.target.value })}
              placeholder={t('parentSetup.namePlaceholder')}
              className="input"
            />
          </div>
          <div>
            <label className="label">{t('parentSetup.grade')}</label>
            <input
              type="text"
              value={student.grade}
              onChange={(e) => onUpdate({ grade: e.target.value })}
              placeholder={t('parentSetup.gradePlaceholder')}
              className="input"
            />
          </div>
        </div>

        {/* Grade stage */}
        <div className="grid grid-cols-3 gap-2">
          {GRADE_STAGES.map((s) => (
            <button
              key={s.value}
              onClick={() => onUpdate({ grade_stage: s.value })}
              className={`rounded-xl border-2 p-2.5 text-left transition-all ${
                student.grade_stage === s.value
                  ? 'border-navy-500 bg-navy-50'
                  : 'border-gray-200 bg-white hover:border-navy-200'
              }`}
            >
              <div className="text-lg mb-0.5">{s.emoji}</div>
              <div className="font-semibold text-xs text-gray-800">{s.label}</div>
              <div className="text-xs text-gray-400 leading-tight">{t(s.descriptionKey)}</div>
            </button>
          ))}
        </div>

        {/* Companion mode — a starting point, not a lock; picking one fills
            in subjects + session length below, both still freely editable
            afterward. Meets the family where they are: new to homeschooling
            or easing into AI deliberately, wanting more structure, or ready
            for the full rotation. */}
        <div>
          <label className="label">{t('parentSetup.companionModeLabel')}</label>
          <div className="grid grid-cols-3 gap-2">
            {COMPANION_MODES.map((m) => (
              <button
                key={m.value}
                onClick={() => onUpdate({
                  companion_mode: m.value,
                  selected_subjects: m.subjects,
                  session_cap_minutes: m.sessionCapMinutes,
                })}
                className={`rounded-xl border-2 p-2.5 text-left transition-all ${
                  student.companion_mode === m.value
                    ? 'border-navy-500 bg-navy-50'
                    : 'border-gray-200 bg-white hover:border-navy-200'
                }`}
              >
                <div className="text-lg mb-0.5">{m.emoji}</div>
                <div className="font-semibold text-xs text-gray-800">{t(m.labelKey)}</div>
                <div className="text-xs text-gray-400 leading-tight">{t(m.descriptionKey)}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Sex — only asked when the deployment's locale needs it for
            grammatically correct address (Spanish, Italian, Polish so far;
            an English-only deployment never sees this). */}
        {requireSex && (
          <div>
            <label className="label">{t('parentSetup.sex')}</label>
            <div className="grid grid-cols-2 gap-2">
              {(['male', 'female'] as const).map((value) => (
                <button
                  key={value}
                  onClick={() => onUpdate({ sex: value })}
                  className={`rounded-xl border-2 py-2.5 text-sm font-medium transition-all ${
                    student.sex === value
                      ? 'border-navy-500 bg-navy-50 text-navy-800'
                      : 'border-gray-200 bg-white text-gray-600 hover:border-navy-200'
                  }`}
                >
                  {value === 'male' ? t('parentSetup.sexMale') : t('parentSetup.sexFemale')}
                </button>
              ))}
            </div>
            <p className="text-xs text-gray-400 mt-1.5">
              {student.student_name.trim()
                ? t('parentSetup.sexHelpNamed', { name: student.student_name.trim() })
                : t('parentSetup.sexHelpUnnamed')}
            </p>
          </div>
        )}

        {/* Subjects */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="label mb-0">{t('parentSetup.subjects')}</label>
            <span className={`text-xs ${overSubscribedBy > 0 ? 'text-amber-700 font-medium' : 'text-gray-400'}`}>
              {t('parentSetup.minutesShort', { count: totalMin })} / {t('parentSetup.minutesShort', { count: availableStudyMin })}
            </span>
          </div>
          {overSubscribedBy > 0 && (
            <div className="mb-2 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2">
              <AlertTriangle size={14} className="mt-0.5 flex-shrink-0 text-amber-600" />
              <p className="text-xs text-amber-800">
                {t('parentSetup.subjectsOverCap', {
                  over: overSubscribedBy,
                  cap: student.session_cap_minutes,
                  needed: capNeededForPlan,
                })}
              </p>
            </div>
          )}
          {/* Single column, not a 2-up grid: several labels (Greek & New
              Testament Foundations, Latin & Christian Foundations, Scripture
              & Bible Study) don't fit a half-width card on one line, and
              wrapping to two lines read as unpolished. Full width comfortably
              fits every current label on one line; truncate + title remain
              as a safety net for a future label that doesn't. The left
              border is each subject's own color from SUBJECTS, matching
              agnusdei.io's curriculum color binder — see that field's own
              comment in types/index.ts. */}
          <div className="grid grid-cols-1 gap-1.5">
            {availableSubjects.map((s) => {
              const active = student.selected_subjects.includes(s.id)
              return (
                <button
                  key={s.id}
                  onClick={() => onToggleSubject(s.id)}
                  style={{ borderLeftColor: s.color, borderLeftWidth: '4px' }}
                  className={`flex items-center gap-2 rounded-xl border-2 pl-2 pr-3 py-2 text-left transition-all hover:scale-[1.02] active:scale-[0.98] min-w-0 ${
                    active ? 'border-navy-400 bg-navy-50 shadow-sm' : 'border-gray-200 bg-white opacity-50'
                  }`}
                >
                  <s.Icon size={16} className="flex-shrink-0 text-current" />
                  <div className="flex-1 min-w-0 flex items-baseline gap-2">
                    <span className="text-xs font-medium text-gray-800 truncate" title={s.label}>{s.label}</span>
                    <span className="text-xs text-gray-400 flex-shrink-0">{t('parentSetup.minutesShort', { count: s.durationMin })}</span>
                  </div>
                </button>
              )
            })}
          </div>
        </div>

        {/* Voice / accessibility */}
        <div className="flex items-center justify-between p-3 bg-gray-50 rounded-xl">
          <div>
            <p className="text-sm font-medium text-gray-700">{t('parentSetup.voiceVerification')}</p>
            <p className="text-xs text-gray-500 mt-0.5">
              {student.voice_required
                ? t('parentSetup.voiceVerificationOn')
                : t('parentSetup.voiceVerificationOff')}
            </p>
          </div>
          <button
            onClick={() => onUpdate({ voice_required: !student.voice_required })}
            className={`relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ${
              student.voice_required ? 'bg-navy-500' : 'bg-gray-300'
            }`}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${
                student.voice_required ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>

        {/* Appearance lock — hides the chat theme/bubble picker in this
            student's sessions. For children who find open-ended
            customization a distraction magnet, choice happens here with
            the parent, not mid-lesson. */}
        <div className="flex items-center justify-between p-3 bg-gray-50 rounded-xl">
          <div>
            <p className="text-sm font-medium text-gray-700">{t('parentSetup.lockChatAppearance')}</p>
            <p className="text-xs text-gray-500 mt-0.5">
              {student.appearance_locked
                ? t('parentSetup.appearanceLockedOn')
                : t('parentSetup.appearanceLockedOff')}
            </p>
          </div>
          <button
            onClick={() => onUpdate({ appearance_locked: !student.appearance_locked })}
            className={`relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ${
              student.appearance_locked ? 'bg-navy-500' : 'bg-gray-300'
            }`}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${
                student.appearance_locked ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>

        {/* Session hard stop — on by default and there by design; the
            parent (already behind the parent password to be on this page)
            may extend it, but never beyond 4 hours, and every hour of
            session time still gets its mandatory 10-minute break. */}
        <div className="p-3 bg-gray-50 rounded-xl">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-gray-700">{t('parentSetup.sessionLength')}</p>
              <p className="text-xs text-gray-500 mt-0.5">
                {t('parentSetup.sessionLengthHelp')}
              </p>
            </div>
            <div className="w-24 flex-shrink-0">
              <input
                type="number"
                min={30}
                max={240}
                step={15}
                value={student.session_cap_minutes}
                onChange={(e) =>
                  onUpdate({ session_cap_minutes: Math.max(30, Math.min(240, Number(e.target.value) || 120)) })
                }
                className="input"
              />
              <p className="text-xs text-gray-400 mt-1 text-center">{t('parentSetup.minutes')}</p>
            </div>
          </div>
        </div>

        {/* Screen time limit + eye-rest break */}
        <div className="p-3 bg-gray-50 rounded-xl space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-700">{t('parentSetup.limitScreenTime')}</p>
              <p className="text-xs text-gray-500 mt-0.5">
                {student.screen_time_limit_enabled
                  ? t('parentSetup.screenTimeOn', { minutes: student.screen_time_limit_minutes })
                  : t('parentSetup.screenTimeOff')}
              </p>
            </div>
            <button
              onClick={() => onUpdate({ screen_time_limit_enabled: !student.screen_time_limit_enabled })}
              className={`relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ${
                student.screen_time_limit_enabled ? 'bg-navy-500' : 'bg-gray-300'
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${
                  student.screen_time_limit_enabled ? 'translate-x-5' : 'translate-x-0'
                }`}
              />
            </button>
          </div>

          {student.screen_time_limit_enabled && (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="label">{t('parentSetup.screenTimeCapLabel')}</label>
                <input
                  type="number"
                  min={15}
                  max={480}
                  step={5}
                  value={student.screen_time_limit_minutes}
                  onChange={(e) =>
                    onUpdate({ screen_time_limit_minutes: Math.max(15, Math.min(480, Number(e.target.value) || 15)) })
                  }
                  className="input"
                />
              </div>
              <div>
                <label className="label">{t('parentSetup.eyeRestBreakLabel')}</label>
                <input
                  type="number"
                  min={30}
                  max={120}
                  step={5}
                  value={student.eye_rest_break_minutes}
                  onChange={(e) =>
                    onUpdate({ eye_rest_break_minutes: Math.max(30, Math.min(120, Number(e.target.value) || 30)) })
                  }
                  className="input"
                />
                <p className="text-xs text-gray-400 mt-1">{t('parentSetup.eyeRestMinimum')}</p>
              </div>
            </div>
          )}
        </div>

        {/* Voice enrollment */}
        {student.student_name.trim() && student.voice_required && (
          <div className="flex items-center justify-between">
            <p className="text-sm text-gray-600">
              {isEnrolled
                ? <><CheckCircle size={13} className="inline text-navy-500 mr-1" />{t('parentSetup.voiceEnrolled')}</>
                : t('parentSetup.noVoiceProfile')}
            </p>
            <button
              onClick={() => onUpdate({ showEnrollment: true })}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border-2 border-navy-300 text-navy-700 hover:bg-navy-50 text-xs font-medium transition-colors"
            >
              <Mic size={12} />
              {isEnrolled ? t('parentSetup.reEnrol') : t('parentSetup.enrolVoice')}
            </button>
          </div>
        )}

        {/* Term & mastery outcomes */}
        <div className="p-3 bg-gray-50 rounded-xl space-y-3">
          <div className="flex items-center justify-between gap-2">
            <div>
              <p className="text-sm font-medium text-gray-700">{t('parentSetup.termMasteryOutcomes')}</p>
              <p className="text-xs text-gray-500 mt-0.5">
                {student.term_schedule === 'trimester'
                  ? t('parentSetup.trimesterYear')
                  : t('parentSetup.quarterYear')} · {t('parentSetup.termMasterySuffix')}
              </p>
              {/* current_term also drives Art & Music's one-artist-per-term
                  picture study (services/ai_service.py's _TERM_ARTISTS) —
                  nothing else in the UI says so, so a parent who never
                  advances this sees the same handful of pictures for
                  months without knowing why. */}
              <p className="text-xs text-gray-400 mt-0.5">{t('parentSetup.termAdvanceHint')}</p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <select
                value={student.term_schedule}
                onChange={(e) => {
                  const term_schedule = e.target.value as TermSchedule
                  onUpdate({
                    term_schedule,
                    current_term: Math.min(student.current_term, term_schedule === 'trimester' ? 3 : 4),
                  })
                }}
                className="input !w-auto text-xs py-1.5"
              >
                <option value="trimester">{t('parentSetup.termsOption')}</option>
                <option value="quarterly">{t('parentSetup.quartersOption')}</option>
              </select>
              <select
                value={student.current_term}
                onChange={(e) => onUpdate({ current_term: Number(e.target.value) })}
                className="input !w-auto text-xs py-1.5"
              >
                {Array.from({ length: student.term_schedule === 'trimester' ? 3 : 4 }, (_, i) => i + 1).map((n) => (
                  <option key={n} value={n}>
                    {student.term_schedule === 'trimester' ? t('parentSetup.termN', { n }) : t('parentSetup.quarterN', { n })}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div className="space-y-2">
            {CORE_AREAS.map(({ id, label }) => (
              <div key={id}>
                <label className="label text-xs">{label}</label>
                <input
                  type="text"
                  value={student.term_topics[id]}
                  onChange={(e) => onUpdate({ term_topics: { ...student.term_topics, [id]: e.target.value } })}
                  placeholder={t('parentSetup.termTopicsPlaceholder')}
                  className="input text-xs"
                />
              </div>
            ))}
            <p className="text-xs text-gray-400">
              {t('parentSetup.termTopicsHelp')}
            </p>
          </div>

          {/* Travel mode — the ONLY control over the mastery-cycle window.
              With it off there is exactly one honest window (28 actual
              days, what the guarantee is written against), so a family that
              doesn't travel is never asked to pick a number. Turning it on
              is the parent saying "our weeks aren't regular", and the
              choice appears then and only then. This changes nothing about
              how the child is taught — it widens how far back Progress
              looks so the same evidence has room to accumulate. */}
          <div className="pt-3 border-t border-gray-200">
            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={student.travel_mode}
                onChange={(e) => onUpdate({
                  travel_mode: e.target.checked,
                  // Coming home resets the window, so a parent never has to
                  // remember what it used to be. Mirrors the backend
                  // validator, which does the same thing authoritatively.
                  mastery_cycle_days: e.target.checked ? student.mastery_cycle_days : DEFAULT_MASTERY_CYCLE_DAYS,
                })}
                className="mt-0.5"
              />
              <span className="min-w-0">
                <span className="text-sm font-medium text-gray-700">{t('parentSetup.travelMode')}</span>
                <span className="block text-xs text-gray-500 mt-0.5">{t('parentSetup.travelModeHelp')}</span>
              </span>
            </label>
            {student.travel_mode && (
              <div className="mt-2 flex items-center gap-2 pl-6">
                <label htmlFor={`cycle-${student.student_name}`} className="text-xs text-gray-600">
                  {t('parentSetup.masteryWindowLabel')}
                </label>
                <select
                  id={`cycle-${student.student_name}`}
                  value={student.mastery_cycle_days}
                  onChange={(e) => onUpdate({ mastery_cycle_days: Number(e.target.value) })}
                  className="input !w-auto text-xs py-1.5"
                >
                  {[21, 28, 35, 42].map((d) => (
                    <option key={d} value={d}>{t('parentSetup.weeksN', { n: d / 7 })}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </div>

        {/* Pick up where we left off — the parent tells Bede where an
            interrupted lesson stopped, so the subject resumes mid-thread
            instead of opening as though it were new. A note can only ever
            attach to a subject chosen above; there's no free-text topic
            field, by design. */}
        <div className="p-3 bg-gray-50 rounded-xl space-y-3">
          <div>
            <p className="text-sm font-medium text-gray-700 flex items-center gap-1.5">
              <BookMarked size={14} className="text-navy-500" /> {t('parentSetup.resumeTitle')}
            </p>
            <p className="text-xs text-gray-500 mt-0.5">{t('parentSetup.resumeHelp')}</p>
          </div>

          {student.lesson_resume.map((entry, ri) => {
            const takenElsewhere = student.lesson_resume
              .filter((_, k) => k !== ri)
              .map((r) => r.subject)
            // The row's own subject stays in the list even if it was later
            // deselected above, so the parent can see what it points at
            // rather than the select silently blanking.
            const options = [
              ...student.selected_subjects.filter((s) => !takenElsewhere.includes(s)),
              ...(entry.subject && !student.selected_subjects.includes(entry.subject)
                ? [entry.subject]
                : []),
            ]
            const notScheduled = !!entry.subject && !student.selected_subjects.includes(entry.subject)
            return (
              <div key={ri} className="bg-white border border-gray-200 rounded-xl p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <select
                    value={entry.subject}
                    onChange={(e) => updateResume(ri, { subject: e.target.value as Subject | '' })}
                    className="input !w-auto flex-1 text-xs py-1.5"
                  >
                    <option value="">{t('parentSetup.resumeChooseSubject')}</option>
                    {options.map((s) => (
                      <option key={s} value={s}>{SUBJECT_MAP[s].label}</option>
                    ))}
                  </select>
                  <input
                    type="date"
                    value={entry.recorded_on}
                    onChange={(e) => updateResume(ri, { recorded_on: e.target.value })}
                    title={t('parentSetup.resumeDate')}
                    className="input !w-auto text-xs py-1.5"
                  />
                  <button
                    onClick={() => removeResume(ri)}
                    title={t('parentSetup.resumeRemove')}
                    className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors flex-shrink-0"
                  >
                    <X size={14} />
                  </button>
                </div>

                {notScheduled && (
                  <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-2 py-1.5">
                    {t('parentSetup.resumeSubjectNotScheduled')}
                  </p>
                )}

                <div>
                  <label className="label text-xs">{t('parentSetup.resumeStoppedAt')}</label>
                  <textarea
                    value={entry.stopped_at}
                    onChange={(e) => updateResume(ri, { stopped_at: e.target.value })}
                    placeholder={t('parentSetup.resumeStoppedAtPlaceholder')}
                    rows={2}
                    maxLength={300}
                    className="input text-xs resize-none"
                  />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="label text-xs">{t('parentSetup.resumeNextStep')}</label>
                    <input
                      type="text"
                      value={entry.next_step}
                      onChange={(e) => updateResume(ri, { next_step: e.target.value })}
                      placeholder={t('parentSetup.resumeNextStepPlaceholder')}
                      maxLength={300}
                      className="input text-xs"
                    />
                  </div>
                  <div>
                    <label className="label text-xs">{t('parentSetup.resumeStickingPoint')}</label>
                    <input
                      type="text"
                      value={entry.sticking_point}
                      onChange={(e) => updateResume(ri, { sticking_point: e.target.value })}
                      placeholder={t('parentSetup.resumeStickingPointPlaceholder')}
                      maxLength={300}
                      className="input text-xs"
                    />
                  </div>
                </div>
              </div>
            )
          })}

          {student.lesson_resume.length < student.selected_subjects.length && (
            <button
              onClick={addResume}
              className="flex items-center gap-1.5 text-xs font-medium text-navy-600 hover:text-navy-800"
            >
              <Plus size={13} /> {t('parentSetup.resumeAdd')}
            </button>
          )}
          <p className="text-xs text-gray-400">{t('parentSetup.resumeOnlyChosenSubjects')}</p>
        </div>

        {/* Optional context — collapsed by default */}
        <div>
          <button
            onClick={() => onUpdate({ expandedContext: !student.expandedContext })}
            className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700"
          >
            {student.expandedContext ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            {t('parentSetup.sessionContextOptional')}
          </button>
          {student.expandedContext && (
            <div className="mt-3 space-y-3">
              <div>
                <label className="label">{t('parentSetup.currentUnit')}</label>
                <input
                  type="text"
                  value={student.current_unit}
                  onChange={(e) => onUpdate({ current_unit: e.target.value })}
                  placeholder={t('parentSetup.currentUnitPlaceholder')}
                  className="input"
                />
              </div>
              <div>
                <label className="label">{t('parentSetup.faithFocus')}</label>
                <input
                  type="text"
                  value={student.faith_emphasis}
                  onChange={(e) => onUpdate({ faith_emphasis: e.target.value })}
                  placeholder={t('parentSetup.faithFocusPlaceholder')}
                  className="input"
                />
              </div>
              {(student.selected_subjects.includes('scripture') || student.selected_subjects.includes('saints')) && (
                <div>
                  <label className="label">{t('parentSetup.faithTradition')}</label>
                  <input
                    type="text"
                    value={student.faith_tradition}
                    onChange={(e) => onUpdate({ faith_tradition: e.target.value })}
                    placeholder={t('parentSetup.faithTraditionPlaceholder')}
                    maxLength={60}
                    className="input"
                  />
                  <p className="text-xs text-gray-400 mt-1">{t('parentSetup.faithTraditionHint')}</p>
                </div>
              )}
              {/* Latin is included here but deliberately NOT in the church-tradition
                  gate above: the subject quotes Scripture in English alongside its
                  Vulgate text, so the translation preference applies — but its content
                  is the shared Christian inheritance by design, so it never needs a
                  denominational label to teach. See services/latin_catalog.py. */}
              {(student.selected_subjects.includes('scripture') || student.selected_subjects.includes('saints')
                || student.selected_subjects.includes('morning_time')
                || student.selected_subjects.includes('latin')
                || student.selected_subjects.includes('greek')) && (
                <div>
                  <label className="label">{t('parentSetup.bibleTranslation')}</label>
                  <select
                    value={student.bible_translation}
                    onChange={(e) => onUpdate({ bible_translation: e.target.value })}
                    className="input bg-white cursor-pointer"
                  >
                    <option value="">{t('parentSetup.bibleTranslationDefault')}</option>
                    {BIBLE_TRANSLATIONS.map((v) => (
                      <option key={v} value={v}>{v}</option>
                    ))}
                  </select>
                  <p className="text-xs text-gray-400 mt-1">{t('parentSetup.bibleTranslationHint')}</p>
                </div>
              )}
              <div>
                <label className="label">{t('parentSetup.curriculumResources')}</label>
                <input
                  type="text"
                  value={student.curriculum_resources}
                  onChange={(e) => onUpdate({ curriculum_resources: e.target.value })}
                  placeholder={t('parentSetup.curriculumResourcesPlaceholder')}
                  className="input"
                />
                <div className="flex flex-wrap gap-1.5 mt-1.5">
                  {CURRICULUM_RESOURCE_SUGGESTIONS.map((name) => {
                    const already = student.curriculum_resources
                      .split(',').map((r) => r.trim().toLowerCase()).includes(name.toLowerCase())
                    return (
                      <button
                        key={name}
                        type="button"
                        disabled={already}
                        onClick={() => onUpdate({
                          curriculum_resources: [student.curriculum_resources, name].filter(Boolean).join(', '),
                        })}
                        className={`text-xs px-2 py-1 rounded-full border ${
                          already
                            ? 'bg-navy-50 border-navy-200 text-navy-400 cursor-default'
                            : 'bg-white border-navy-200 text-navy-600 hover:bg-navy-50 cursor-pointer'
                        }`}
                      >
                        {already ? `✓ ${name}` : `+ ${name}`}
                      </button>
                    )
                  })}
                </div>
                <p className="text-xs text-gray-400 mt-1">{t('parentSetup.curriculumResourcesHint')}</p>
              </div>
              <div>
                <label className="label">{t('parentSetup.noteForBede')}</label>
                <textarea
                  value={student.lesson_focus}
                  onChange={(e) => onUpdate({ lesson_focus: e.target.value })}
                  placeholder={t('parentSetup.noteForBedePlaceholder')}
                  rows={2}
                  className="input resize-none"
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {student.showEnrollment && student.student_name.trim() && (
        <VoiceEnrollment
          studentName={student.student_name.trim()}
          onEnrolled={onEnrolled}
          onClose={() => onUpdate({ showEnrollment: false })}
        />
      )}
    </div>
  )
}
