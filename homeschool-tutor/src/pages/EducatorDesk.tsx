import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { BookOpen, ClipboardCheck, LogOut, ShieldCheck, Users } from 'lucide-react'
import { useSessionStore } from '../store/sessionStore'
import type { SessionConfig, Subject } from '../types'
import { prepareFocusedLesson } from '../utils/focusedLesson'
import PilotTeacherJourney from '../components/PilotTeacherJourney'
import {
  fetchInstructorRoster,
  fetchInstructorFrameworks, fetchInstructorDibelsProgress,
  fetchInstructorActivity, saveInstructorAssessment,
  fetchMyEducatorPasskeys, revokeMyEducatorPasskey,
} from '../services/api'
import type {
  AssessmentFrameworkMetadata, DibelsProgress, DibelsGrade, EducatorPasskeySummary,
  DibelsWindow, EducatorAssessmentBand,
} from '../services/api'

const TODAY = () => {
  const now = new Date()
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000)
    .toISOString().slice(0, 10)
}
const field = 'block w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm'

export default function EducatorDesk() {
  const navigate = useNavigate()
  const { token, setSessionConfig, startSession, logout } = useSessionStore()
  const [roster, setRoster] = useState<SessionConfig[]>([])
  const [student, setStudent] = useState('')
  const [subject, setSubject] = useState<Subject>('mathematics')
  const [focus, setFocus] = useState('')
  const [progress, setProgress] = useState<DibelsProgress | null>(null)
  const [workTotal, setWorkTotal] = useState<number | null>(null)
  const [catalog, setCatalog] = useState<AssessmentFrameworkMetadata[]>([])
  const [measure, setMeasure] = useState('ORF_WC')
  const [grade, setGrade] = useState<DibelsGrade>('4')
  const [windowName, setWindowName] = useState<DibelsWindow>('middle_of_year')
  const [assessedOn, setAssessedOn] = useState(TODAY())
  const [score, setScore] = useState('')
  const [band, setBand] = useState<EducatorAssessmentBand>('not_reported')
  const [source, setSource] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [passkeys, setPasskeys] = useState<EducatorPasskeySummary[]>([])
  const [showPasskeys, setShowPasskeys] = useState(false)
  const [journeyStep, setJourneyStep] = useState<'roster' | 'lesson' | 'evidence' | 'recommendations'>('roster')

  useEffect(() => {
    if (!token) return
    let active = true
    Promise.all([
      fetchInstructorRoster(token),
      fetchInstructorFrameworks(token),
]).then(([students, frameworks]) => {
      if (!active) return
      setRoster(students)
      setCatalog(frameworks)
      if (students[0]) setStudent((current) => current || students[0].student_name)
    }).catch(() => { if (active) setMessage('Could not load assigned class roster') })
    return () => { active = false }
  }, [token])

  useEffect(() => {
    if (!token) return
    let active = true
    fetchMyEducatorPasskeys(token).then(keys => {
      if (active) setPasskeys(keys)
    }).catch(() => {
      if (active) setMessage('Could not verify your enrolled passkeys')
    })
    return () => { active = false }
  }, [token])

  const removePasskey = async (id: string) => {
    if (!token || passkeys.length < 2 || !window.confirm('Revoke this passkey and end all existing sessions?')) return
    setBusy(true)
    try {
      await revokeMyEducatorPasskey(token, id)
      logout()
      navigate('/')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not revoke passkey')
    } finally {
      setBusy(false)
    }
  }

  const activeConfig = roster.find((cfg) => cfg.student_name === student)
  const dibels = catalog.find((entry) => entry.id === 'dibels8')
  const measures = dibels?.supported_measures ?? []
  const unit = dibels?.measure_units?.[measure] ?? ''
  const activeSubject = activeConfig?.subjects.includes(subject)
    ? subject : activeConfig?.subjects[0] ?? 'mathematics'

  useEffect(() => {
    if (!activeConfig) return
    setSubject(activeConfig.subjects[0] ?? 'mathematics')
    setGrade(activeConfig.grade as DibelsGrade)
  }, [activeConfig?.student_name, activeConfig?.grade])

  const refreshProgress = async (name: string) => {
    if (!token) return
    const [data, activity] = await Promise.all([
      fetchInstructorDibelsProgress(token, name),
      fetchInstructorActivity(token, name),
    ])
    setProgress(data)
    setWorkTotal(activity.total)
  }

  useEffect(() => {
    if (!token || !student) return
    let active = true
    setProgress(null)
    setWorkTotal(null)
    Promise.all([
      fetchInstructorDibelsProgress(token, student),
      fetchInstructorActivity(token, student),
    ]).then(([data, activity]) => {
      if (active) {
        setProgress(data)
        setWorkTotal(activity.total)
      }
    }).catch(() => { if (active) setMessage('Could not load learner evidence') })
    return () => { active = false }
  }, [token, student])

  const teach = () => {
    if (!activeConfig) return
    const prepared = prepareFocusedLesson(activeConfig, activeSubject, focus)
    if (!prepared) return
    setSessionConfig(prepared)
    startSession()
    navigate('/session')
  }

  const saveDibels = async () => {
    if (!token || !activeConfig || !dibels || !unit || !score.trim()
        || !source.trim() || busy || !grade || !windowName) {
      setMessage('Complete the independent assessment report fields')
      return
    }
    setBusy(true)
    setMessage('')
    try {
      await saveInstructorAssessment(token, student, {
        framework: 'dibels8', measure, assessed_on: assessedOn,
        source_name: source.trim(), score: Number(score), score_unit: unit,
        assessed_grade: grade, assessment_window: windowName,
        reported_band: band,
      })
      await refreshProgress(student)
      setScore('')
      setSource('')
      setMessage('Educator-reported assessment recorded, not independently scored by Bede')
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not record assessment')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="bg-parchment-50 min-h-screen px-4 py-8 educator-classroom">
      <div className="max-w-4xl mx-auto space-y-5">
        <header className="educator-welcome flex flex-wrap justify-between gap-3 items-start">
          <div className="educator-welcome-copy">
            <p className="text-xs uppercase tracking-widest text-sage-700 mb-2">Bede · Classical learning</p>
            <h1 className="text-2xl font-display font-bold text-gray-900">Your Classroom</h1>
            <button type="button" onClick={() => navigate('/lesson-planner')} className="mt-2 text-sm font-semibold text-navy-800 underline">Plan with Bede</button>
            <p className="text-sm text-gray-600 mt-1">A calm place to guide your learners, see their growth, and review Bede’s suggestions.</p>
          </div>
          <button type="button" className="flex items-center gap-2 text-sm text-gray-700" onClick={() => {
            logout()
            navigate('/')
          }}><LogOut size={16}/> Sign out</button>
        </header>

        {/* Account management is available on demand, not a competing classroom step. */}
        <section className="rounded-xl border bg-white p-3 space-y-3" aria-label="Account security">
          <button type="button" onClick={() => setShowPasskeys(value => !value)}
            className="text-sm font-semibold text-navy-800 underline">
            {showPasskeys ? 'Hide passkey settings' : 'Manage my passkeys'}
          </button>
          {showPasskeys && (
            <div className="space-y-2 text-sm">
              <p>Only registered passkeys can sign in. Your device PIN or biometric never goes to Bede.</p>
              {passkeys.map(key => (
                <div key={key.id} className="flex flex-wrap justify-between gap-2 border-t py-2">
                  <span>Passkey enrolled {new Date(key.created_at).toLocaleDateString()}</span>
                  <button type="button" disabled={busy || passkeys.length < 2}
                    onClick={() => void removePasskey(key.id)}
                    className="text-red-700 underline disabled:opacity-40">Revoke passkey</button>
                </div>
              ))}
              <p className="text-xs text-gray-600">
                You cannot remove your last active passkey. Ask your authorized school administrator
                for supervised recovery if all passkeys are lost.
              </p>
            </div>
          )}
        </section>

        <p className="text-sm text-gray-700">Welcome. Choose a learner, then follow the steps below at your own pace.</p>
        <nav aria-label="Educator journey" className="flex flex-wrap gap-2 rounded-xl border bg-white p-3">
          {(['roster', 'lesson', 'evidence', 'recommendations'] as const).map((step, index) => (
            <button key={step} type="button"
              aria-current={journeyStep === step ? 'step' : undefined}
              onClick={() => setJourneyStep(step)}
              className={journeyStep === step
                ? 'rounded-lg bg-navy-700 px-3 py-2 text-sm text-white'
                : 'rounded-lg border px-3 py-2 text-sm text-navy-800'}>
              {index + 1}. {step === 'roster' ? 'My learners' : step === 'lesson' ? 'Plan a lesson' : step === 'evidence' ? 'See progress' : 'Review suggestions'}
            </button>
          ))}
        </nav>
        {journeyStep === 'recommendations' && token && <PilotTeacherJourney token={token} />}
        <section hidden={journeyStep !== 'roster'} className="bg-white rounded-2xl border p-4 space-y-3">
          <div className="flex items-center gap-2 font-semibold"><Users size={17}/> Authorized class roster</div>
          <p className="text-xs text-gray-500">{roster.length} assigned learners. Your school administrator manages learner assignments.</p>
          <label className="block text-sm">Select learner
            <select value={student} onChange={e => setStudent(e.target.value)} className={field + ' mt-1'}>
              {roster.map(cfg => <option key={cfg.student_name} value={cfg.student_name}>
                {cfg.student_name} — grade {cfg.grade}
              </option>)}
            </select>
          </label>
          {activeConfig && <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => setJourneyStep('lesson')} className="rounded-lg bg-navy-700 px-4 py-2 text-white">Plan lesson</button>
            <button type="button" onClick={() => setJourneyStep('evidence')} className="rounded-lg border px-4 py-2 text-navy-800">Review progress</button>
            <button type="button" onClick={() => setJourneyStep('recommendations')} className="rounded-lg border px-4 py-2 text-navy-800">Review Bede’s suggestions</button>
          </div>}
          {!roster.length && <p className="text-sm text-gray-600">Your classroom is ready for learners. Ask your school administrator to assign your class.</p>}
        </section>

        {activeConfig && (
          <>
            <section aria-label="Guided lesson" hidden={journeyStep !== 'lesson'} className="bg-white border rounded-2xl p-4 space-y-3">
              <h2 className="font-semibold flex items-center gap-2"><BookOpen size={18}/> Classical tutoring</h2>
              <p className="text-xs text-gray-600">This starts the real tutor with the parent-approved curriculum and protections. Your short focus applies to this session only.</p>
              <label className="block text-sm">Approved subject
                <select className={field + ' mt-1'} value={activeSubject}
                  onChange={e => setSubject(e.target.value as Subject)}>
                  {activeConfig.subjects.map(s => <option key={s} value={s}>
                    {s.replaceAll('_', ' ')}
                  </option>)}
                </select>
              </label>
              <label className="block text-sm">Today's lesson focus (optional)
                <input className={field + ' mt-1'} maxLength={300}
                  value={focus} onChange={e => setFocus(e.target.value)}
                  placeholder="e.g., Narrate the next chapter or explain fractions"/>
              </label>
              <button type="button" onClick={teach} className="bg-navy-600 text-white rounded-lg px-4 py-2">
                Begin guided lesson
              </button>
            </section>

            <section aria-label="Learner evidence" hidden={journeyStep !== 'evidence'} className="bg-white border rounded-2xl p-4 space-y-3">
              <h2 className="font-semibold flex items-center gap-2"><ClipboardCheck size={18}/> Periodic DIBELS 8 evidence</h2>
              <p className="text-sm text-gray-600">Total independently reported DIBELS entries: {progress?.total_dibels_records ?? '—'}. Bede academic work observations in selected period: {workTotal ?? '—'}.</p>
              <p className="text-xs text-gray-600">These figures are educator-entered, unverified by Bede. Changes between compatible measures are descriptive; they do not establish that Bede caused a learning gain. DIBELS test administration and scoring remain outside Bede.</p>
              {progress && progress.records_excluded_from_comparison > 0 &&
                <p className="text-xs text-amber-800">{progress.records_excluded_from_comparison} older entries need report review before comparison.</p>}
              {progress?.series.length === 0 && <p className="text-sm text-gray-500">No compatible DIBELS progress series recorded yet.</p>}
              {progress?.series.map((series) => (
                <div key={series.measure + series.assessed_grade + series.unit} className="rounded-xl border p-3 space-y-2">
                  <h3 className="font-semibold text-sm">{series.measure} · grade {series.assessed_grade} · {series.unit.replaceAll('_', ' ')}</h3>
                  <div className="overflow-x-auto">
                    <table className="text-sm w-full text-left">
                      <thead><tr className="text-gray-500">
                        <th className="py-2 pr-3">Date / window</th>
                        <th className="py-2 pr-3">Reported score</th>
                        <th className="py-2 pr-3">Change*</th>
                        <th className="py-2">As-reported category</th>
                      </tr></thead>
                      <tbody>{series.points.map((point) => (
                        <tr key={point.record_id} className="border-t">
                          <td className="py-2 pr-3">{point.date} · {point.assessment_window?.replaceAll('_', ' ') || 'unspecified'}</td>
                          <td className="py-2 pr-3">{point.score_as_reported}</td>
                          <td className="py-2 pr-3">{point.difference_from_previous_same_grade_measure === null
                            ? '—' : point.difference_from_previous_same_grade_measure > 0
                              ? '+' + point.difference_from_previous_same_grade_measure
                              : point.difference_from_previous_same_grade_measure}</td>
                          <td className="py-2">{point.risk_category_as_reported?.replaceAll('_', ' ') || 'not reported'}</td>
                        </tr>
                      ))}</tbody>
                    </table>
                  </div>
                </div>
              ))}
              <p className="text-xs text-gray-500">*Difference from the preceding result for the same DIBELS measure, grade and unit only. A score difference alone is not a causal learning-efficacy estimate.</p>
            </section>

            <section aria-label="External assessment recording" hidden={journeyStep !== 'evidence'} className="bg-white border rounded-2xl p-4 space-y-3">
              <h2 className="font-semibold flex items-center gap-2"><ShieldCheck size={18}/> Record an official DIBELS 8 result</h2>
              <p className="text-xs text-gray-600">Transcribe an independently administered assessment report. Never enter test questions, passages, answers, or other proprietary materials.</p>
              <div className="grid sm:grid-cols-2 gap-3">
                <label className="text-sm">Measure
                  <select className={field + ' mt-1'} value={measures.includes(measure) ? measure : measures[0] ?? ''}
                    onChange={e => setMeasure(e.target.value)}>
                    {measures.map(value => <option key={value} value={value}>{value}</option>)}
                  </select>
                </label>
                <label className="text-sm">Unit (from official measure)
                  <p className="mt-2 text-sm text-gray-700">{unit.replaceAll('_', ' ') || 'Not available'}</p>
                </label>
                <label className="text-sm">Assessed grade
                  <select className={field + ' mt-1'} value={grade}
                    onChange={e => setGrade(e.target.value as DibelsGrade)}>
                    {(dibels?.grades ?? []).map(value => <option key={value} value={value}>{value}</option>)}
                  </select>
                </label>
                <label className="text-sm">Testing window
                  <select className={field + ' mt-1'} value={windowName}
                    onChange={e => setWindowName(e.target.value as DibelsWindow)}>
                    {(dibels?.windows ?? []).map(value => <option key={value} value={value}>{value.replaceAll('_', ' ')}</option>)}
                  </select>
                </label>
                <label className="text-sm">Assessment date
                  <input className={field + ' mt-1'} type="date" max={TODAY()} value={assessedOn}
                    onChange={e => setAssessedOn(e.target.value)}/>
                </label>
                <label className="text-sm">Reported numeric score
                  <input className={field + ' mt-1'} type="number" min={0}
                    max={unit === 'percent' ? 100 : 1000000} step="any"
                    value={score} onChange={e => setScore(e.target.value)}/>
                </label>
                <label className="text-sm">Reported category
                  <select className={field + ' mt-1'} value={band}
                    onChange={e => setBand(e.target.value as EducatorAssessmentBand)}>
                    {(dibels?.reported_bands ?? []).map(value => <option key={value} value={value}>
                      {value.replaceAll('_', ' ')}
                    </option>)}
                  </select>
                </label>
                <label className="text-sm">Independent educator report / source
                  <input className={field + ' mt-1'} value={source}
                    maxLength={120} onChange={e => setSource(e.target.value)}
                    placeholder="e.g., administered DIBELS 8 report"/>
                </label>
              </div>
              <button type="button" disabled={busy || !dibels} onClick={() => void saveDibels()}
                className="bg-navy-600 text-white rounded-lg px-4 py-2 disabled:opacity-50">
                Record external assessment
              </button>
            </section>
          </>
        )}

        {/* Legacy Pod/Locuto capacity is not part of the institutional teacher journey. */}
        {message && <p role="status" className="text-sm text-navy-700">{message}</p>}
      </div>
    </main>
  )
}
