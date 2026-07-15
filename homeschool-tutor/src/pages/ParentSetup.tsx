import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Trash2, Mic, CheckCircle, ChevronDown, ChevronUp, Database, Shield, Users, Loader2, DollarSign, KeyRound, AlertTriangle } from 'lucide-react'
import { useSessionStore } from '../store/sessionStore'
import type { Subject, GradeStage, SessionConfig, TermSchedule, CoreArea } from '../types'
import { SUBJECTS, CORE_AREAS } from '../types'
import VoiceEnrollment from '../components/VoiceEnrollment'
import ParentSecuritySettings from '../components/ParentSecuritySettings'
import { listVoiceProfiles } from '../services/voiceApi'
import { fetchSystemStatus, savePodConfigs, type SystemStatus } from '../services/api'

const GRADE_STAGES: Array<{ label: string; value: GradeStage; description: string; emoji: string }> = [
  { label: 'K–2', value: 'K-2', description: 'Grammar Stage', emoji: '🌱' },
  { label: '3–5', value: '3-5', description: 'Logic Stage', emoji: '🔭' },
  { label: '6–8', value: '6-8', description: 'Rhetoric Stage', emoji: '🎓' },
]

interface StudentForm {
  student_name: string
  grade: string
  grade_stage: GradeStage
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
  const navigate = useNavigate()
  const { setSessionConfig, startSession, setPodStudents, logout, token } = useSessionStore()

  const [students, setStudents] = useState<StudentForm[]>([blankStudent()])
  const [enrolledProfiles, setEnrolledProfiles] = useState<string[]>([])
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null)
  const [statusError, setStatusError] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [hitlConsent, setHitlConsent] = useState(false)

  useEffect(() => {
    if (!token) return
    listVoiceProfiles(token).then(setEnrolledProfiles).catch(() => {})
    fetchSystemStatus(token)
      .then(setSystemStatus)
      .catch(() => setStatusError(true))
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

  const canSave =
    hitlConsent &&
    students.length > 0 &&
    students.every((s) => s.student_name.trim() && s.grade.trim() && s.selected_subjects.length > 0)

  const handleSavePod = async () => {
    if (!canSave || !token) return
    setSaving(true)
    setSaveError('')
    const configs: SessionConfig[] = students.map((s) => ({
      student_name: s.student_name.trim(),
      grade: s.grade.trim(),
      grade_stage: s.grade_stage,
      subjects: s.selected_subjects,
      lesson_focus: s.lesson_focus.trim() || undefined,
      faith_emphasis: s.faith_emphasis.trim() || undefined,
      current_unit: s.current_unit.trim() || undefined,
      voice_required: s.voice_required,
      appearance_locked: s.appearance_locked,
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
    try {
      await savePodConfigs(token, configs)
      setPodStudents(configs)
      // Single-student shortcut: start session directly
      if (configs.length === 1) {
        setSessionConfig(configs[0])
        startSession()
        navigate('/session')
      } else {
        navigate('/pod')
      }
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save — check your connection.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-parchment-50 via-parchment-50 to-navy-50/40 p-4 md:p-8">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="flex justify-between items-center mb-8">
          <div>
            <div className="flex items-center gap-3">
              <img src="/bede-icon.png" alt="Bede" className="w-9 h-9 rounded-full object-cover" />
              <h1 className="text-2xl font-display font-bold text-gray-800">Plan Today's Pod</h1>
            </div>
            <p className="text-sm text-gray-500 mt-1">Add each student, then open their session on their tablet</p>
          </div>
          <button onClick={logout} className="text-xs text-gray-400 hover:text-gray-600 underline">
            Log out
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
            <span className="flex items-center gap-1.5"><Database size={13} /> Cannot reach server</span>
          ) : systemStatus ? (
            <>
              <span className="flex items-center gap-1.5 font-medium"><Database size={13} /> DB connected</span>
              <span className="flex items-center gap-1.5"><Shield size={13} /> {systemStatus.encryption}</span>
              <span className="flex items-center gap-1.5">
                <Users size={13} />
                {systemStatus.voice_profiles_enrolled === 0
                  ? 'No voices enrolled'
                  : `${systemStatus.voice_profiles_enrolled} voice${systemStatus.voice_profiles_enrolled > 1 ? 's' : ''} enrolled`}
              </span>
              <span className="flex items-center gap-1.5" title="Estimate on your own Anthropic API key — see console.anthropic.com for exact billing">
                <DollarSign size={13} />
                ${systemStatus.usage.estimated_cost_usd.toFixed(2)} AI usage (est.)
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
                  title={`Licensed to ${systemStatus.license.licensee} — ${systemStatus.license.seats} student seats`}
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
                      ? `Trial — ${systemStatus.license.days_remaining} day${systemStatus.license.days_remaining === 1 ? '' : 's'} left`
                      : 'Trial expired'
                    : `${systemStatus.license.tier === 'coop' ? 'Co-op' : 'Core'} license`}
                </span>
              )}
            </>
          ) : (
            <span>Checking system status…</span>
          )}
        </div>

        <ParentSecuritySettings token={token!} />

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
            <Plus size={16} /> Add Another Student
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
            I understand that Bede is an AI assistant that{' '}
            <strong>supports, not replaces</strong>, my role as primary educator. I remain
            responsible for my child's curriculum, wellbeing, and learning outcomes. I have
            reviewed today's plan and it reflects my intentions.
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
            <><Loader2 size={18} className="animate-spin" /> Saving…</>
          ) : students.length === 1 ? (
            <>Begin Session with Bede</>
          ) : (
            <>Open Pod Dashboard — {students.length} Students</>
          )}
        </button>
      </div>
    </div>
  )
}

interface StudentCardProps {
  index: number
  student: StudentForm
  total: number
  isEnrolled: boolean
  token: string
  onUpdate: (patch: Partial<StudentForm>) => void
  onToggleSubject: (id: Subject) => void
  onEnrolled: () => void
  onRemove: () => void
}

function StudentCard({
  index, student, total, isEnrolled, token,
  onUpdate, onToggleSubject, onEnrolled, onRemove,
}: StudentCardProps) {
  const totalMin = student.selected_subjects.reduce((acc, s) => {
    const info = SUBJECTS.find((x) => x.id === s)
    return acc + (info?.durationMin ?? 0)
  }, 0)

  const label = student.student_name.trim() || `Student ${index + 1}`

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
            title="Remove student"
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>

      <div className="p-5 space-y-5">
        {/* Name + grade */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">Student's Name</label>
            <input
              type="text"
              value={student.student_name}
              onChange={(e) => onUpdate({ student_name: e.target.value })}
              placeholder="e.g. Emma"
              className="input"
            />
          </div>
          <div>
            <label className="label">Grade</label>
            <input
              type="text"
              value={student.grade}
              onChange={(e) => onUpdate({ grade: e.target.value })}
              placeholder="e.g. 4 or K"
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
              <div className="text-xs text-gray-400 leading-tight">{s.description}</div>
            </button>
          ))}
        </div>

        {/* Subjects */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="label mb-0">Subjects</label>
            <span className="text-xs text-gray-400">{totalMin} min</span>
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
                    <div className="text-xs text-gray-400">{s.durationMin} min</div>
                  </div>
                </button>
              )
            })}
          </div>
        </div>

        {/* Voice / accessibility */}
        <div className="flex items-center justify-between p-3 bg-gray-50 rounded-xl">
          <div>
            <p className="text-sm font-medium text-gray-700">Voice verification</p>
            <p className="text-xs text-gray-500 mt-0.5">
              {student.voice_required
                ? 'Student says passphrase at session start'
                : 'PIN-only — no voice check (mute / accessibility)'}
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
            <p className="text-sm font-medium text-gray-700">Lock chat appearance</p>
            <p className="text-xs text-gray-500 mt-0.5">
              {student.appearance_locked
                ? 'Theme & bubble-color picker hidden during this student’s sessions'
                : 'Student may change the background theme and bubble color'}
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
              <p className="text-sm font-medium text-gray-700">Session length (hard stop)</p>
              <p className="text-xs text-gray-500 mt-0.5">
                Ends automatically after {student.session_cap_minutes} min — 2 hours by default, 4 hours at most.
                A 10-minute off-screen break is required after each hour.
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
              <p className="text-xs text-gray-400 mt-1 text-center">minutes</p>
            </div>
          </div>
        </div>

        {/* Screen time limit + eye-rest break */}
        <div className="p-3 bg-gray-50 rounded-xl space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-700">Limit total screen time today</p>
              <p className="text-xs text-gray-500 mt-0.5">
                {student.screen_time_limit_enabled
                  ? `Mandatory eye-rest break after ${student.screen_time_limit_minutes} min on screen`
                  : 'Off — only the grade-based block/break cycle applies'}
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
                <label className="label">Screen time cap (min)</label>
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
                <label className="label">Eye-rest break (min)</label>
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
                <p className="text-xs text-gray-400 mt-1">30-minute minimum, for eye health</p>
              </div>
            </div>
          )}
        </div>

        {/* Voice enrollment */}
        {student.student_name.trim() && student.voice_required && (
          <div className="flex items-center justify-between">
            <p className="text-sm text-gray-600">
              {isEnrolled
                ? <><CheckCircle size={13} className="inline text-navy-500 mr-1" />Voice enrolled</>
                : 'No voice profile yet'}
            </p>
            <button
              onClick={() => onUpdate({ showEnrollment: true })}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border-2 border-navy-300 text-navy-700 hover:bg-navy-50 text-xs font-medium transition-colors"
            >
              <Mic size={12} />
              {isEnrolled ? 'Re-enrol' : 'Enrol Voice'}
            </button>
          </div>
        )}

        {/* Term & mastery outcomes */}
        <div className="p-3 bg-gray-50 rounded-xl space-y-3">
          <div className="flex items-center justify-between gap-2">
            <div>
              <p className="text-sm font-medium text-gray-700">Term & mastery outcomes</p>
              <p className="text-xs text-gray-500 mt-0.5">
                {student.term_schedule === 'trimester'
                  ? 'Mater Amabilis 3-term year'
                  : '4-quarter year'} · exposure to all topics, mastery of up to 3 per area
              </p>
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
                <option value="trimester">Terms (3/yr)</option>
                <option value="quarterly">Quarters (4/yr)</option>
              </select>
              <select
                value={student.current_term}
                onChange={(e) => onUpdate({ current_term: Number(e.target.value) })}
                className="input !w-auto text-xs py-1.5"
              >
                {Array.from({ length: student.term_schedule === 'trimester' ? 3 : 4 }, (_, i) => i + 1).map((n) => (
                  <option key={n} value={n}>
                    {student.term_schedule === 'trimester' ? 'Term' : 'Quarter'} {n}
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
                  placeholder="Up to 3 mastery topics, comma-separated"
                  className="input text-xs"
                />
              </div>
            ))}
            <p className="text-xs text-gray-400">
              Bede weaves these into lessons, tracks each learner's progress on them, and shows
              you where they stand on the Progress page — the child never sees them as objectives.
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
            Session context (optional)
          </button>
          {student.expandedContext && (
            <div className="mt-3 space-y-3">
              <div>
                <label className="label">Current Unit of Study</label>
                <input
                  type="text"
                  value={student.current_unit}
                  onChange={(e) => onUpdate({ current_unit: e.target.value })}
                  placeholder="e.g. Ancient Egypt, Fractions"
                  className="input"
                />
              </div>
              <div>
                <label className="label">Faith / Virtue Focus</label>
                <input
                  type="text"
                  value={student.faith_emphasis}
                  onChange={(e) => onUpdate({ faith_emphasis: e.target.value })}
                  placeholder="e.g. Proverbs 3:5-6, Patience"
                  className="input"
                />
              </div>
              <div>
                <label className="label">Note for Bede</label>
                <textarea
                  value={student.lesson_focus}
                  onChange={(e) => onUpdate({ lesson_focus: e.target.value })}
                  placeholder="e.g. Focus on multiplication facts 6–9 today."
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
