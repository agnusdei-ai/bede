import { useCallback, useEffect, useState } from 'react'
import {
  createOfficialAssessment, decideOfficialProposal, fetchOfficialAssessment,
  fetchOfficialAssessments, fetchOfficialDataDay, fetchPilotLearners,
  recordOfficialEvidence, recordOfficialPlan, recordOfficialScores,
  requestOfficialProposal, supersedeOfficialAssessment, transitionOfficialAssessment,
  updateOfficialMarks,
} from '../services/api'
import type {
  DibelsGrade, OfficialAdministrationLog, OfficialAssessment,
  OfficialDataDay, OfficialMeasureStatus, OfficialProposal,
  OfficialTeacherObservation, PilotLearner,
} from '../services/api'

/**
 * Canonical teacher-only DIBELS form, independent of the legacy family
 * assessment flow. Uses campus + learner UUIDs and the real G1/G2 routes.
 * Never renders proprietary form items or starts learner instruction.
 */
const input = 'block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm'
const label = (text: string) => text.replaceAll('_', ' ').toLowerCase()
const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10)
const units: Record<string, string> = {
  LNF: 'correct_per_minute', PSF: 'correct_per_minute', NWF_CLS: 'correct_per_minute',
  NWF_WRC: 'correct_per_minute', WRF: 'correct_per_minute',
  ORF_WC: 'correct_per_minute', ORF_ACCURACY: 'percent', MAZE: 'points', COMPOSITE: 'points',
}
const measures = Object.keys(units)
const skipStatuses: OfficialMeasureStatus[] = ['skipped', 'not_applicable', 'invalid', 'voided']
const numberOrNull = (value: string) => value.trim() ? Number(value) : null
const isoOrNull = (value: string) => value.trim() ? new Date(value).toISOString() : null
const localDateTime = (iso: string) => {
  const date = new Date(iso)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}
const cleanObservation = (entries: Record<string, string>): OfficialTeacherObservation =>
  Object.fromEntries(Object.entries(entries).map(([key, value]) => [key, value.trim()])) as OfficialTeacherObservation

export default function PilotOfficialAssessmentPanels({ token }: { token: string }) {
  const [learners, setLearners] = useState<PilotLearner[]>([])
  const [learnerId, setLearnerId] = useState('')
  const learner = learners.find(l => l.learner_id === learnerId)
  const [assessments, setAssessments] = useState<OfficialAssessment[]>([])
  const [assessmentId, setAssessmentId] = useState('')
  const [record, setRecord] = useState<OfficialAssessment | null>(null)
  const [packet, setPacket] = useState<OfficialDataDay | null>(null)
  const [proposal, setProposal] = useState<OfficialProposal | null>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [grade, setGrade] = useState<DibelsGrade>('1')
  const [date, setDate] = useState(today())
  const [measure, setMeasure] = useState('PSF')
  const [purpose, setPurpose] = useState<'benchmark' | 'progress_monitoring'>('progress_monitoring')
  const [windowName, setWindowName] = useState<'BOY' | 'MOY' | 'EOY' | 'none'>('none')
  const [cycle, setCycle] = useState('valor_q1')
  const [formId, setFormId] = useState('')
  const [source, setSource] = useState('teacher_administered')
  const [accommodation, setAccommodation] = useState('')
  const [startTime, setStartTime] = useState('')
  const [endTime, setEndTime] = useState('')
  const [elapsed, setElapsed] = useState('')
  const [lastItem, setLastItem] = useState('')
  const [correct, setCorrect] = useState('')
  const [errors, setErrors] = useState('')
  const [corrections, setCorrections] = useState('')
  const [discontinue, setDiscontinue] = useState<'not_recorded' | 'met' | 'not_met' | 'not_applicable'>('not_recorded')
  const [fidelity, setFidelity] = useState('')
  const [interrupted, setInterrupted] = useState(false)
  const [interruptionNote, setInterruptionNote] = useState('')
  const [scoreStatus, setScoreStatus] = useState<OfficialMeasureStatus>('scored')
  const [rawScore, setRawScore] = useState('')
  const [accuracy, setAccuracy] = useState('')
  const [reason, setReason] = useState('')
  const [reviewed, setReviewed] = useState(false)
  const [observation, setObservation] = useState<Record<string, string>>({
    accuracy_fluency_notes: '', error_patterns: '', attention_circumstances: '',
    narration_comprehension: '', curriculum_concepts_taught: '',
    teacher_interpretation: '', suggested_next_step: '',
  })
  const [summary, setSummary] = useState('')
  const [editText, setEditText] = useState('')
  const [rationale, setRationale] = useState('')
  const [planText, setPlanText] = useState('')
  const [resolution, setResolution] = useState('')
  const [abstention, setAbstention] = useState('')
  const [decidedText, setDecidedText] = useState('')

  useEffect(() => {
    let alive = true
    fetchPilotLearners(token).then(items => {
      if (!alive) return
      setLearners(items)
      setLearnerId(items[0]?.learner_id ?? '')
    }).catch(() => { if (alive) setMessage('No authorized pilot learners are available.') })
    return () => { alive = false }
  }, [token])

  const refresh = useCallback(async (id: string, selectedId?: string) => {
    const l = learners.find(row => row.learner_id === id)
    if (!l) return
    const rows = await fetchOfficialAssessments(token, l.campus_id, l.learner_id)
    setAssessments(rows)
    const target = selectedId || rows[rows.length - 1]?.assessment_id || ''
    setAssessmentId(target)
    const [detail, day] = await Promise.all([
      target ? fetchOfficialAssessment(token, l.campus_id, l.learner_id, target) : Promise.resolve(null),
      fetchOfficialDataDay(token, l.campus_id, l.learner_id, cycle),
    ])
    setRecord(detail)
    setPacket(day)
    setProposal(day.proposed_next_steps.find(p => p.assessment_id === target) ?? null)
  }, [learners, token, cycle])

  useEffect(() => {
    if (!learnerId) return
    let alive = true
    setRecord(null); setPacket(null); setAssessmentId(''); setAssessments([])
    const l = learners.find(row => row.learner_id === learnerId)
    if (!l) return
    Promise.all([
      fetchOfficialAssessments(token, l.campus_id, l.learner_id),
      fetchOfficialDataDay(token, l.campus_id, l.learner_id, cycle),
    ]).then(async ([rows, day]) => {
      if (!alive) return
      setAssessments(rows); setPacket(day)
      const id = rows[rows.length - 1]?.assessment_id
      if (id) {
        const detail = await fetchOfficialAssessment(token, l.campus_id, l.learner_id, id)
        if (alive) {
          setRecord(detail); setAssessmentId(id)
          setProposal(day.proposed_next_steps.find(p => p.assessment_id === id) ?? null)
        }
      }
    }).catch(() => { if (alive) setMessage('Could not load official records. Check your campus assignment.') })
    return () => { alive = false }
  }, [learnerId, learners, cycle, token])

  const run = async (job: () => Promise<string | void>) => {
    if (!learner) return
    setBusy(true); setMessage(''); setAbstention('')
    try {
      const result = await job()
      if (result) setMessage(result)
    } catch (error) {
      // Error responses from the authorized pilot API contain actionable
      // field/permission failures, but never render raw instrument content.
      setMessage(error instanceof Error ? error.message : 'The operation did not complete.')
    } finally { setBusy(false) }
  }

  const log: OfficialAdministrationLog = {
    start_time: isoOrNull(startTime), end_time: isoOrNull(endTime),
    elapsed_seconds: numberOrNull(elapsed), last_item_attempted: numberOrNull(lastItem),
    correct_marks: numberOrNull(correct), error_marks: numberOrNull(errors),
    self_corrections: numberOrNull(corrections), discontinue_rule_result: discontinue,
    interrupted, interruption_note: interrupted ? interruptionNote : null,
    administration_fidelity_note: fidelity || null,
  }
  // Restore saved live marks when an educator opens a record. Never copy marks
  // from a different campus/learner into the currently selected draft.
  useEffect(() => {
    const marks = record?.administration_log
    setStartTime(marks?.start_time ? localDateTime(marks.start_time) : '')
    setEndTime(marks?.end_time ? localDateTime(marks.end_time) : '')
    setElapsed(marks?.elapsed_seconds == null ? '' : String(marks.elapsed_seconds))
    setLastItem(marks?.last_item_attempted == null ? '' : String(marks.last_item_attempted))
    setCorrect(marks?.correct_marks == null ? '' : String(marks.correct_marks))
    setErrors(marks?.error_marks == null ? '' : String(marks.error_marks))
    setCorrections(marks?.self_corrections == null ? '' : String(marks.self_corrections))
    setDiscontinue(marks?.discontinue_rule_result ?? 'not_recorded')
    setFidelity(marks?.administration_fidelity_note ?? '')
    setInterrupted(marks?.interrupted ?? false)
    setInterruptionNote(marks?.interruption_note ?? '')
    const score = record?.scores?.[0]
    setScoreStatus(score?.administration_status ?? 'scored')
    setRawScore(score?.raw_score == null ? '' : String(score.raw_score))
    setAccuracy(score?.accuracy_percent == null ? '' : String(score.accuracy_percent))
    setReason(score?.reason ?? '')
    setReviewed(score?.teacher_reviewed ?? false)
  }, [record])

  const selectedEvidence = packet?.cited_evidence.find(e => e.assessment_id === assessmentId)
  const decided = packet?.prior_teacher_decisions.find(d =>
    d.administration_id === assessmentId && d.authorized_text && !d.outcome.plan_recorded)
  const planRecorded = packet?.prior_teacher_decisions.some(d =>
    d.administration_id === assessmentId && d.outcome.plan_recorded) ?? false
  const locked = Boolean(record?.finalized_at || record?.state === 'VOIDED_BY_TEACHER' ||
    record?.state === 'SUPERSEDED_WITH_AUDIT_LINK')
  const canScore = record?.state === 'IN_PROGRESS' || record?.state === 'COMPLETED_PENDING_REVIEW'
  const hasScore = scoreStatus !== 'scored' || rawScore.trim() !== ''
  const unit = units[record?.measure ?? measure] ?? 'correct_per_minute'

  const create = () => run(async () => {
    if (!learner || !formId.trim()) return 'Enter the identifier printed on the authorized official form.'
    const result = await createOfficialAssessment(token, learner.campus_id, learner.learner_id, {
      instrument: 'dibels8', edition: '8th', measure, grade, form_id: formId.trim(),
      administration_purpose: purpose, instructional_cycle: cycle,
      administered_at: new Date(`${date}T12:00:00`).toISOString(),
      report_source: source, official_benchmark_window: purpose === 'benchmark' ? windowName : 'none',
      accommodations: accommodation.trim() ? [accommodation.trim()] : [],
      administration_log: log,
    })
    await refresh(learnerId, result.assessment_id)
    return 'Official record created as a draft. No assessment material was copied.'
  })

  const step = (action: string, detail?: string) => run(async () => {
    if (!learner || !record) return
    await transitionOfficialAssessment(token, learner.campus_id, learner.learner_id,
      record.assessment_id, record.state, action, detail)
    await refresh(learnerId, record.assessment_id)
    return 'Assessment state recorded.'
  })

  const updateMarks = () => run(async () => {
    if (!learner || !record) return
    await updateOfficialMarks(token, learner.campus_id, learner.learner_id,
      record.assessment_id, record.state, log)
    await refresh(learnerId, record.assessment_id)
    return 'Administration marks saved with audit history.'
  })

  const saveScore = () => run(async () => {
    if (!learner || !record) return
    if (!hasScore) return 'Enter a reported score. A skipped measure must never be entered as zero.'
    if (scoreStatus !== 'scored' && !reason.trim()) return 'Record the reason this measure was not scored.'
    await recordOfficialScores(token, learner.campus_id, learner.learner_id,
      record.assessment_id, [{
        measure: record.measure, administration_status: scoreStatus,
        ...(scoreStatus === 'scored' ? {
          raw_score: Number(rawScore), score_unit: unit,
          ...(correct.trim() ? { correct_count: Number(correct) } : {}),
          ...(errors.trim() ? { error_count: Number(errors) } : {}),
          ...(accuracy.trim() ? { accuracy_percent: Number(accuracy) } : {}),
        } : { reason: reason.trim() }),
        teacher_reviewed: reviewed,
        ...(record.measure === 'COMPOSITE' ? { composite_eligibility: 'not_verified' as const } : {}),
      }])
    await refresh(learnerId, record.assessment_id)
    return 'Reported measure saved; no automatic score, cut point, risk category or composite calculated.'
  })

  const storeObservation = () => run(async () => {
    if (!learner || !record) return
    await recordOfficialEvidence(token, learner.campus_id, learner.learner_id,
      record.assessment_id, cleanObservation(observation), summary.trim() || undefined)
    await refresh(learnerId, record.assessment_id)
    return 'Teacher observation saved separately from the finalized official record.'
  })

  const request = () => run(async () => {
    if (!learner || !record) return
    const result = await requestOfficialProposal(token, learner.campus_id, learner.learner_id,
      record.assessment_id)
    if (result.abstained) { setAbstention(result.reason); return }
    setProposal(result)
    await refresh(learnerId, record.assessment_id)
    return 'Bede suggestion recorded as a draft, not an instruction.'
  })

  const decide = (action: 'approve' | 'edit' | 'reject') => run(async () => {
    if (!learner || !record || !proposal) return
    const result = await decideOfficialProposal(token, learner.campus_id, learner.learner_id,
      record.assessment_id, proposal.proposal_id, {
        action, expected_version: proposal.version,
        ...(action === 'edit' ? { edited_text: editText.trim() } : {}),
        ...(rationale.trim() ? { rationale: rationale.trim() } : {}),
      })
    setDecidedText(result.authorized_text ?? '')
    if (result.authorized_text) setPlanText(result.authorized_text)
    await refresh(learnerId, record.assessment_id)
    return action === 'reject' ? 'Rejection recorded; nothing delivered.' :
      'Teacher decision recorded. Instruction is not sent to a learner.'
  })

  const plan = () => run(async () => {
    if (!learner || !record || !planText.trim()) return
    const result = await recordOfficialPlan(token, learner.campus_id, learner.learner_id,
      record.assessment_id, planText.trim())
    if (result.delivery_state !== 'NOT_REQUESTED') throw new Error('Unexpected delivery state')
    await refresh(learnerId, record.assessment_id)
    return 'Teaching plan recorded. Delivery remains NOT_REQUESTED.'
  })

  const supersede = () => run(async () => {
    if (!learner || !record || resolution.trim().length < 3) return 'Give a correction reason (at least 3 characters).'
    const replacement = await supersedeOfficialAssessment(token, learner.campus_id, learner.learner_id,
      record.assessment_id, resolution.trim())
    await refresh(learnerId, replacement.assessment_id)
    return 'Correction draft created. Original finalized record remains immutable.'
  })

  if (learners.length === 0) {
    return <section aria-label="Official assessment and teacher observation" className="rounded-xl border p-4 text-sm">
      {message || 'No assigned learners for this pilot.'}
    </section>
  }

  return (
    <section aria-label="Official assessment and teacher observation" className="space-y-4">
      <div className="rounded-xl border bg-white p-4">
        <h2 className="text-lg font-semibold text-navy-800">Assessment and teacher review</h2>
        <p className="mt-1 text-sm text-slate-600">
          Official record on the left; your observations and decisions on the right.
          Bede records reported results, not test passages or calculated DIBELS scores.
        </p>
        <label className="mt-3 block text-sm font-medium">Authorized learner
          <select className={input + ' mt-1'} value={learnerId}
            onChange={e => { setLearnerId(e.target.value); setMessage(''); setDecidedText(''); setPlanText('') }}>
            {learners.map(l => <option key={l.learner_id} value={l.learner_id}>
              {l.display_name} — {l.campus_id.slice(0, 8)}
            </option>)}
          </select>
        </label>
      </div>
      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-2">
        <section aria-label="Official assessment record" className="space-y-4 rounded-xl border bg-white p-4">
          <header>
            <h3 className="text-base font-semibold">1. Official assessment record</h3>
            <p className="mt-1 text-xs text-slate-600">DIBELS 8 · Authorized official form or educator-entered report</p>
            <a href="https://dibels.uoregon.edu/materials/dibels" target="_blank" rel="noopener noreferrer"
              className="text-xs underline text-navy-700">Open University of Oregon official materials</a>
          </header>

          <div className="grid grid-cols-2 gap-3">
            <label className="text-sm">Grade
              <select className={input + ' mt-1'} value={grade}
                onChange={e => setGrade(e.target.value as DibelsGrade)}>
                {['K','1','2','3','4','5','6','7','8'].map(g => <option key={g} value={g}>{g}</option>)}
              </select>
            </label>
            <label className="text-sm">Date
              <input className={input + ' mt-1'} type="date" value={date} max={today()}
                onChange={e => setDate(e.target.value)}/>
            </label>
            <label className="text-sm">Measure
              <select className={input + ' mt-1'} value={measure} onChange={e => setMeasure(e.target.value)}>
                {measures.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
            </label>
            <label className="text-sm">Purpose
              <select className={input + ' mt-1'} value={purpose}
                onChange={e => { const p = e.target.value as typeof purpose; setPurpose(p); if (p !== 'benchmark') setWindowName('none') }}>
                <option value="progress_monitoring">Progress monitoring</option>
                <option value="benchmark">Benchmark</option>
              </select>
            </label>
            {purpose === 'benchmark' && <label className="text-sm">Official benchmark period
              <select className={input + ' mt-1'} value={windowName}
                onChange={e => setWindowName(e.target.value as typeof windowName)}>
                <option value="none">Not reported</option>
                <option value="BOY">BOY</option><option value="MOY">MOY</option>
                <option value="EOY">EOY</option>
              </select>
            </label>}
            <label className="text-sm">Valor Data Day cycle
              <select className={input + ' mt-1'} value={cycle} onChange={e => setCycle(e.target.value)}>
                {['valor_q1','valor_q2','valor_q3','valor_q4'].map(key =>
                  <option key={key} value={key}>{key.replace('valor_', 'Valor ').toUpperCase()}</option>)}
              </select>
            </label>
            <label className="text-sm col-span-2">Official form identifier
              <input className={input + ' mt-1'} value={formId} maxLength={64}
                onChange={e => setFormId(e.target.value)} placeholder="Identifier on approved form"/>
            </label>
            <label className="text-sm">Report source
              <select className={input + ' mt-1'} value={source} onChange={e => setSource(e.target.value)}>
                <option value="teacher_administered">Teacher-administered official form</option>
                <option value="vendor_report">Official vendor report</option>
              </select>
            </label>
            <label className="text-sm">Accommodation (if recorded)
              <input className={input + ' mt-1'} value={accommodation} maxLength={120}
                onChange={e => setAccommodation(e.target.value)}/>
            </label>
          </div>
          <p className="text-xs text-slate-600">Benchmark records require campus authorization for this exact form. Bede does not display, modify, or license DIBELS items.</p>
          <button type="button" disabled={busy || !formId.trim() || !date} onClick={() => void create()}
            className="rounded-lg bg-navy-700 px-3 py-2 text-sm font-medium text-white disabled:opacity-50">
            Create official record
          </button>
          <label className="block text-sm">Open administration
            <select className={input + ' mt-1'} value={assessmentId}
              onChange={e => { setAssessmentId(e.target.value); setMessage(''); setDecidedText(''); setPlanText(''); if (learner) void refresh(learnerId, e.target.value) }}>
              <option value="">Choose a saved record</option>
              {assessments.map(a => <option key={a.assessment_id} value={a.assessment_id}>
                {a.measure} · {a.administered_at.slice(0, 10)} · {label(a.state)}
              </option>)}
            </select>
          </label>
          {record && <>
            <p role="status" className="text-sm font-semibold">Administration: {label(record.state)}</p>
            {record.snapshot_sha256 && <p className="break-all text-xs text-slate-500">
              Finalized snapshot SHA-256: {record.snapshot_sha256}</p>}
            <fieldset disabled={busy || locked} className="space-y-3">
              <legend className="text-sm font-semibold">Administration marks and fidelity</legend>
              <div className="grid grid-cols-2 gap-3">
                <label className="text-sm">Start time
                  <input type="datetime-local" className={input + ' mt-1'} value={startTime} onChange={e => setStartTime(e.target.value)}/>
                </label>
                <label className="text-sm">End time
                  <input type="datetime-local" className={input + ' mt-1'} value={endTime} onChange={e => setEndTime(e.target.value)}/>
                </label>
                {([
                  ['Elapsed seconds', elapsed, setElapsed],
                  ['Last item attempted (number only)', lastItem, setLastItem],
                  ['Correct marks', correct, setCorrect],
                  ['Error marks', errors, setErrors],
                  ['Self-corrections', corrections, setCorrections],
                ] as const).map(([text,value,set]) => (
                  <label key={text} className="text-sm">{text}
                    <input type="number" min="0" step="1" className={input + ' mt-1'}
                      value={value} onChange={e => set(e.target.value)}/>
                  </label>
                ))}
                <label className="text-sm">Discontinue rule
                  <select className={input + ' mt-1'} value={discontinue}
                    onChange={e => setDiscontinue(e.target.value as typeof discontinue)}>
                    <option value="not_recorded">Not recorded</option>
                    <option value="met">Met</option><option value="not_met">Not met</option>
                    <option value="not_applicable">Not applicable</option>
                  </select>
                </label>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={interrupted} onChange={e => setInterrupted(e.target.checked)}/>
                Administration interrupted
              </label>
              {interrupted && <label className="block text-sm">Interruption details
                <input className={input + ' mt-1'} value={interruptionNote} maxLength={500}
                  onChange={e => setInterruptionNote(e.target.value)}/>
              </label>}
              <label className="block text-sm">Administration fidelity note
                <textarea className={input + ' mt-1'} rows={2} value={fidelity} maxLength={500}
                  onChange={e => setFidelity(e.target.value)}/>
              </label>
              <button type="button" onClick={() => void updateMarks()} disabled={busy}
                className="rounded-lg border px-3 py-2 text-sm">Save live marks</button>
            </fieldset>
            <div className="flex flex-wrap gap-2">
              {record.state === 'DRAFT' && <button type="button" disabled={busy}
                onClick={() => void step('mark_ready')} className="rounded-lg border px-3 py-2 text-sm">
                Mark ready</button>}
              {record.state === 'READY_FOR_ADMINISTRATION' && <button type="button" disabled={busy}
                onClick={() => void step('start')} className="rounded-lg border px-3 py-2 text-sm">
                Start administration</button>}
              {record.state === 'IN_PROGRESS' && <button type="button" disabled={busy || !resolution.trim()}
                onClick={() => void step('interrupt', resolution.trim())} className="rounded-lg border px-3 py-2 text-sm">
                Mark interrupted</button>}
              {record.state === 'INTERRUPTED' && <button type="button" disabled={busy || !resolution.trim()}
                onClick={() => void step('resume', resolution.trim())} className="rounded-lg border px-3 py-2 text-sm">
                Resume with explanation</button>}
              {record.state === 'INVALID_ADMINISTRATION' && <button type="button" disabled={busy || !resolution.trim()}
                onClick={() => void step('resolve_invalid', resolution.trim())} className="rounded-lg border px-3 py-2 text-sm">
                Resolve invalid status</button>}
              {record.state === 'DRAFT' && <button type="button" disabled={busy || resolution.trim().length < 3}
                onClick={() => void step('void', resolution.trim())} className="rounded-lg border px-3 py-2 text-sm">
                Void draft</button>}
            </div>
            {['DRAFT','IN_PROGRESS','INTERRUPTED','INVALID_ADMINISTRATION'].includes(record.state) &&
              <label className="block text-sm">Reason for interruption, resolution or void
                <input className={input + ' mt-1'} value={resolution} maxLength={500}
                  onChange={e => setResolution(e.target.value)} placeholder="Required for interrupted/invalid records"/>
              </label>}
            {canScore && <>
              <h4 className="text-sm font-semibold">Measure result as reported</h4>
              <div className="grid grid-cols-2 gap-3">
                <label className="text-sm">Measure status
                  <select className={input + ' mt-1'} value={scoreStatus}
                    onChange={e => setScoreStatus(e.target.value as OfficialMeasureStatus)}>
                    <option value="scored">Completed — score reported</option>
                    {skipStatuses.map(s => <option key={s} value={s}>{label(s)}</option>)}
                  </select>
                </label>
                {scoreStatus === 'scored' ? <>
                  <label className="text-sm">Raw score ({label(unit)})
                    <input type="number" min="0" step="any" className={input + ' mt-1'}
                      value={rawScore} onChange={e => setRawScore(e.target.value)}/>
                  </label>
                  <label className="text-sm">Accuracy % (if reported)
                    <input type="number" min="0" max="100" step="any" className={input + ' mt-1'}
                      value={accuracy} onChange={e => setAccuracy(e.target.value)}/>
                  </label>
                </> : <label className="text-sm col-span-2">Reason no score exists
                  <input className={input + ' mt-1'} value={reason} maxLength={300}
                    onChange={e => setReason(e.target.value)}/>
                </label>}
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)}/>
                I reviewed this result against the authorized official report
              </label>
              {record.measure === 'COMPOSITE' && <p className="text-xs text-amber-900">
                Composite recorded as reported only; eligibility is unverified until every required grade-level measure
                is confirmed through an authorized source. No composite is calculated by Bede.
              </p>}
              {scoreStatus !== 'scored' && <p className="text-xs text-amber-900">
                Skipped, invalid, or unadministered is a status; it is never a numeric zero.
              </p>}
              <button type="button" disabled={busy || !hasScore} onClick={() => void saveScore()}
                className="rounded-lg border px-3 py-2 text-sm">Save measure result</button>
              {record.state === 'IN_PROGRESS' && <button type="button" disabled={busy || !record.scores?.length}
                onClick={() => void step('submit')} className="ml-2 rounded-lg border px-3 py-2 text-sm">
                Submit for teacher review</button>}
              {record.state === 'COMPLETED_PENDING_REVIEW' && <button type="button" disabled={busy || !record.scores?.length || !reviewed}
                onClick={() => void step('finalize')} className="ml-2 rounded-lg bg-navy-700 px-3 py-2 text-sm text-white">
                Finalize official record</button>}
            </>}
            {locked && record.state !== 'VOIDED_BY_TEACHER' && <div className="space-y-2">
              <p className="text-xs text-slate-600">Finalized entries are immutable. Corrections create a linked draft.</p>
              <label className="block text-sm">Correction reason
                <input className={input + ' mt-1'} maxLength={500} value={resolution}
                  onChange={e => setResolution(e.target.value)}/>
              </label>
              <button type="button" className="rounded-lg border px-3 py-2 text-sm"
                disabled={busy || resolution.trim().length < 3} onClick={() => void supersede()}>
                Create correction record
              </button>
            </div>}
          </>}
        </section>

        <section aria-label="Teacher observation" className="space-y-4 rounded-xl border bg-white p-4">
          <header>
            <h3 className="text-base font-semibold">2. Teacher observation and decision</h3>
            <p className="mt-1 text-xs text-slate-600">
              Your interpretation is separate from the official scores. No learner sessions are started.
            </p>
          </header>
          {!record || !record.finalized_at
            ? <p className="text-sm text-slate-600">Select and finalize an official record to enter teacher observations.</p>
            : <>
              {selectedEvidence ? <div role="status" className="rounded-lg bg-sage-50 p-3 text-sm">
                Teacher observation recorded. Official assessment snapshot unchanged.
              </div> : <fieldset disabled={busy} className="space-y-3">
                <legend className="text-sm font-semibold">Independent teacher observations</legend>
                {([
                  ['accuracy_fluency_notes', 'Accuracy and fluency notes'],
                  ['error_patterns', 'Error patterns'],
                  ['attention_circumstances', 'Attention or administration circumstances'],
                  ['narration_comprehension', 'Narration and comprehension'],
                  ['curriculum_concepts_taught', 'Concepts already taught'],
                  ['teacher_interpretation', 'Teacher interpretation'],
                  ['suggested_next_step', 'Suggested next step'],
                ] as const).map(([key, heading]) =>
                  <label className="block text-sm" key={key}>{heading}
                    <textarea className={input + ' mt-1'} rows={2} maxLength={key === 'teacher_interpretation' || key === 'suggested_next_step' ? 800 : 600}
                      value={observation[key]} onChange={e =>
                        setObservation(prev => ({ ...prev, [key]: e.target.value }))}/>
                  </label>)}
                <label className="block text-sm">Review summary (optional)
                  <input className={input + ' mt-1'} value={summary} maxLength={600}
                    onChange={e => setSummary(e.target.value)}/>
                </label>
                <button type="button" onClick={() => void storeObservation()}
                  className="rounded-lg bg-navy-700 px-3 py-2 text-sm text-white">
                  Save teacher observation
                </button>
              </fieldset>}
              <div className="space-y-2 border-t pt-3">
                <h4 className="text-sm font-semibold">Bede recommendation · teacher-controlled</h4>
                <button type="button" disabled={busy || !selectedEvidence || Boolean(proposal)}
                  onClick={() => void request()} className="rounded-lg border px-3 py-2 text-sm disabled:opacity-50">
                  Request evidence-linked suggestion
                </button>
                {abstention && <p role="status" className="text-sm text-amber-900">{abstention}</p>}
                {proposal && <div className="space-y-3 rounded-lg border border-amber-200 p-3">
                  <p className="text-sm font-medium">Draft — teacher decision required</p>
                  <p className="text-sm">{proposal.proposed_next_step}</p>
                  <p className="text-xs text-slate-600">Evidence reference: {proposal.evidence_id}</p>
                  <ul className="list-disc pl-5 text-xs">{proposal.rationale.map((text, i) =>
                    <li key={i}>{text}</li>)}</ul>
                  <label className="block text-sm">Edit proposed instruction (optional)
                    <textarea className={input + ' mt-1'} value={editText} rows={3} maxLength={1200}
                      onChange={e => setEditText(e.target.value)}/>
                  </label>
                  <label className="block text-sm">Teacher rationale
                    <input className={input + ' mt-1'} value={rationale} maxLength={600}
                      onChange={e => setRationale(e.target.value)}/>
                  </label>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" disabled={busy} onClick={() => void decide('approve')}
                      className="rounded-lg bg-navy-700 px-3 py-2 text-sm text-white">Approve</button>
                    <button type="button" disabled={busy || !editText.trim()} onClick={() => void decide('edit')}
                      className="rounded-lg border px-3 py-2 text-sm">Save edit</button>
                    <button type="button" disabled={busy} onClick={() => void decide('reject')}
                      className="rounded-lg border border-red-300 px-3 py-2 text-sm text-red-800">Reject</button>
                  </div>
                </div>}
                {!planRecorded && (decidedText || decided?.authorized_text) && <div className="space-y-2">
                  <p className="text-xs text-slate-600">Decision recorded. The teacher personally delivers instruction.</p>
                  <label className="block text-sm">Recorded teacher teaching plan
                    <textarea className={input + ' mt-1'} value={planText} rows={3} maxLength={2000}
                      onChange={e => setPlanText(e.target.value)} placeholder={decided?.authorized_text ?? decidedText}/>
                  </label>
                  <button type="button" disabled={busy || !planText.trim()} onClick={() => void plan()}
                    className="rounded-lg border px-3 py-2 text-sm">Record instructional plan</button>
                </div>}
                <p className="text-xs font-medium text-navy-700">Delivery state: NOT_REQUESTED · No learner launch</p>
              </div>
              {packet && <div className="border-t pt-3 text-xs text-slate-600">
                <p>Data Day: {packet.cycle.label}. Official evidence and teacher interpretation remain separate.</p>
                <p>{packet.prior_teacher_decisions.length} recorded decision(s) in this learner's authorized review packet.</p>
              </div>}
            </>}
        </section>
      </div>
      {message && <p role="status" className="rounded-lg border bg-white p-3 text-sm text-navy-800">{message}</p>}
    </section>
  )
}
