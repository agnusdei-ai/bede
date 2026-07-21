import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation, Trans } from 'react-i18next'
import { Plus, Trash2, Mic, CheckCircle, ChevronDown, ChevronUp, Database, Shield, Users, Loader2, DollarSign, KeyRound, AlertTriangle } from 'lucide-react'
import { useSessionStore } from '../store/sessionStore'
import type { Subject, GradeStage, SessionConfig, TermSchedule, CoreArea, CompanionMode } from '../types'
import { SUBJECTS, CORE_AREAS } from '../types'
import VoiceEnrollment from '../components/VoiceEnrollment'
import ParentSecuritySettings from '../components/ParentSecuritySettings'
import LicenseSettings from '../components/LicenseSettings'
import { listVoiceProfiles } from '../services/voiceApi'
import { fetchSystemStatus, isFeedbackEnabled, savePodConfigs, type SystemStatus } from '../services/api'
import BetaIntakeModal from '../components/BetaIntakeModal'

// label is a numeric grade range, not a translated word — same across
// locales. descriptionKey resolves through i18n at render time since this
// array is module-level (no hook context to call t() here directly).
const GRADE_STAGES: Array<{ label: string; value: GradeStage; descriptionKey: string; emoji: string }> = [
  { label: 'K–2', value: 'K-2', descriptionKey: 'parentSetup.stageDescGrammar', emoji: '🌱' },
  { label: '3–5', value: '3-5', descriptionKey: 'parentSetup.stageDescLogic', emoji: '🔭' },
  { label: '6–8', value: '6-8', descriptionKey: 'parentSetup.stageDescRhetoric', emoji: '🎓' },
]

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
const COMPANION_MODES: Array<{
  value: CompanionMode
  labelKey: string
  descriptionKey: string
  emoji: string
  subjects: Subject[]
  sessionCapMinutes: number
}> = [
  {
    value: 'book_companion',
    labelKey: 'parentSetup.companionModeBookCompanion',
    descriptionKey: 'parentSetup.companionModeBookCompanionDesc',
    emoji: '📖',
    subjects: ['living_books', 'morning_time'],
    sessionCapMinutes: 60,
  },
  {
    value: 'guided',
    labelKey: 'parentSetup.companionModeGuided',
    descriptionKey: 'parentSetup.companionModeGuidedDesc',
    emoji: '🧭',
    subjects: ['living_books', 'morning_time', 'language_arts', 'nature_study'],
    sessionCapMinutes: 90,
  },
  {
    value: 'full_plan',
    labelKey: 'parentSetup.companionModeFullPlan',
    descriptionKey: 'parentSetup.companionModeFullPlanDesc',
    emoji: '🗓️',
    subjects: SUBJECTS.filter((s) => s.id !== 'free_study').map((s) => s.id),
    sessionCapMinutes: 120,
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
  voice_required: boolean
  appearance_locked: boolean
  session_cap_minutes: number
  screen_time_limit_enabled: boolean
  screen_time_limit_minutes: number
  eye_rest_break_minutes: number
  term_schedule: TermSchedule
  current_term: number
  // Comma-separated per area in the form; parsed to string[] on save.
  term_topics: Record<CoreArea, string>
  expandedContext: boolean
  showEnrollment: boolean
}

const blankStudent = (): StudentForm => ({
  student_name: '',
  grade: '',
  grade_stage: '3-5',
  sex: '',
  companion_mode: 'full_plan',
  selected_subjects: SUBJECTS.filter((s) => s.id !== 'free_study').map((s) => s.id),
  lesson_focus: '',
  faith_emphasis: '',
  current_unit: '',
  voice_required: true,
  appearance_locked: false,
  session_cap_minutes: 120,
  screen_time_limit_enabled: false,
  screen_time_limit_minutes: 90,
  eye_rest_break_minutes: 30,
  term_schedule: 'trimester',
  current_term: 1,
  term_topics: {
    phonics_language: '', mathematics: '', reading_literature: '',
    science: '', writing_composition: '',
  },
  expandedContext: false,
  showEnrollment: false,
})

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
      voice_required: s.voice_required,
      appearance_locked: s.appearance_locked,
      companion_mode: s.companion_mode,
      session_cap_minutes: Math.max(30, Math.min(240, s.session_cap_minutes)),
      screen_time_limit_minutes: s.screen_time_limit_enabled ? s.screen_time_limit_minutes : null,
      eye_rest_break_minutes: Math.max(30, s.eye_rest_break_minutes),
      term_schedule: s.term_schedule,
      current_term: Math.min(s.current_term, s.term_schedule === 'trimester' ? 3 : 4),
      term_mastery_topics: Object.fromEntries(
        CORE_AREAS.map(({ id }) => [
          id,
          s.term_topics[id].split(',').map((t) => t.trim()).filter(Boolean).slice(0, 3),
        ]).filter(([, topics]) => (topics as string[]).length > 0),
      ),
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
                    systemStatus.license.days_remaining !== null &&
                    systemStatus.license.days_remaining <= 7
                      ? 'text-amber-700 font-medium'
                      : ''
                  }`}
                  title={t('parentSetup.licenseTooltip', { licensee: systemStatus.license.licensee, seats: systemStatus.license.seats })}
                >
                  {systemStatus.license.tier === 'trial' &&
                  systemStatus.license.days_remaining !== null &&
                  systemStatus.license.days_remaining <= 7 ? (
                    <AlertTriangle size={13} />
                  ) : (
                    <KeyRound size={13} />
                  )}
                  {systemStatus.license.tier === 'trial'
                    ? systemStatus.license.days_remaining !== null && systemStatus.license.days_remaining >= 0
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
        <LicenseSettings token={token!} />

        {/* Student cards */}
        <div className="space-y-4">
          {students.map((student, i) => (
            <StudentCard
              key={i}
              index={i}
              student={student}
              total={students.length}
              isEnrolled={isEnrolled(student.student_name.trim())}
              token={token!}
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
  token: string
  requireSex: boolean
  onUpdate: (patch: Partial<StudentForm>) => void
  onToggleSubject: (id: Subject) => void
  onEnrolled: () => void
  onRemove: () => void
}

function StudentCard({
  index, student, total, isEnrolled, token, requireSex,
  onUpdate, onToggleSubject, onEnrolled, onRemove,
}: StudentCardProps) {
  const { t } = useTranslation()
  const totalMin = student.selected_subjects.reduce((acc, s) => {
    const info = SUBJECTS.find((x) => x.id === s)
    return acc + (info?.durationMin ?? 0)
  }, 0)

  const label = student.student_name.trim() || t('parentSetup.studentFallbackLabel', { n: index + 1 })

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
            <span className="text-xs text-gray-400">{t('parentSetup.minutesShort', { count: totalMin })}</span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            {SUBJECTS.map((s) => {
              const active = student.selected_subjects.includes(s.id)
              return (
                <button
                  key={s.id}
                  onClick={() => onToggleSubject(s.id)}
                  className={`flex items-center gap-2 rounded-xl border-2 px-3 py-2 text-left transition-all hover:scale-[1.03] active:scale-[0.97] ${
                    active ? 'border-navy-400 bg-navy-50 shadow-sm' : 'border-gray-200 bg-white opacity-50'
                  }`}
                >
                  <s.Icon size={16} className="flex-shrink-0 text-current" />
                  <div>
                    <div className="text-xs font-medium text-gray-800">{s.label}</div>
                    <div className="text-xs text-gray-400">{t('parentSetup.minutesShort', { count: s.durationMin })}</div>
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

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-xl border border-navy-100 shadow-sm p-5">
      <h2 className="text-sm font-semibold text-gray-700 mb-4">{title}</h2>
      {children}
    </div>
  )
}
