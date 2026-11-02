import { useCallback, useEffect, useState } from 'react'
import {
  createOfficialAssessment, decideOfficialProposal, enterOfficialScores,
  fetchTeacherArtifact, fetchTeacherFollowUps, recordTeacherFollowUp,
  fetchOfficialAssessment, fetchOfficialAssessments, fetchOfficialDataDay,
  recordOfficialObservation, recordOfficialPlan, requestOfficialProposal,
  supersedeOfficialAssessment, transitionOfficialAssessment,
} from '../services/api'
import type {
  DibelsGrade, OfficialAssessment,
  OfficialMeasureStatus, OfficialProposal, OfficialScoreEntry, TeacherObservation,
  OfficialTeacherArtifact, OfficialTeacherFollowUp,
} from '../services/api'
import { describeFailure } from '../utils/requestFailure'
import { SchoolAuthorizationRequiredError } from '../services/api'

/** Separate official record and teacher interpretation; never renders DIBELS test items. */
const input = 'block w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm'
const grades: DibelsGrade[] = ['K', '1', '2', '3', '4', '5', '6', '7', '8']
const measures = ['LNF', 'PSF', 'NWF_CLS', 'NWF_WRC', 'WRF', 'ORF_WC', 'ORF_ACCURACY', 'MAZE']
const units: Record<string, string> = {
  LNF: 'correct_per_minute', PSF: 'correct_per_minute',
  NWF_CLS: 'correct_per_minute', NWF_WRC: 'correct_per_minute',
  WRF: 'correct_per_minute', ORF_WC: 'correct_per_minute',
  ORF_ACCURACY: 'percent', MAZE: 'points',
}
const noScore: OfficialMeasureStatus[] = [
  'skipped', 'not_applicable', 'not_administered_by_rule',
  'not_administered_other', 'interrupted', 'invalid', 'voided',
]
const blankObservation: TeacherObservation = {
  accuracy_fluency: '', error_patterns: '', administration_circumstances: '',
  narration_comprehension: '', curriculum_already_taught: '',
  teacher_interpretation: '', suggested_next_step: '',
}
const dateOnly = () => {
  const d = new Date()
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
}
const optionalNumber = (value: string) => value.trim() === '' ? null : Number(value)
const readable = (text: string) => text.replaceAll('_', ' ').toLowerCase()
const hasObservation = (note: TeacherObservation) =>
  Object.values(note).some(v => Boolean(v?.trim()))

export default function PilotOfficialAssessmentForm({
  token, campusId, learnerId, learnerName, onSchoolAuthorizationRequired,
}: { token: string; campusId: string; learnerId: string; learnerName: string;
  onSchoolAuthorizationRequired?: () => void }) {
  const [records, setRecords] = useState<OfficialAssessment[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [current, setCurrent] = useState<OfficialAssessment | null>(null)
  const [proposal, setProposal] = useState<OfficialProposal | null>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [grade, setGrade] = useState<DibelsGrade>('1')
  const [measure, setMeasure] = useState('PSF')
  const [formId, setFormId] = useState('')
  const [edition, setEdition] = useState('8')
  const [date, setDate] = useState(dateOnly)
  const [purpose, setPurpose] = useState<'benchmark' | 'progress_monitoring'>('progress_monitoring')
  const [window, setWindow] = useState<'BOY' | 'MOY' | 'EOY' | 'none'>('none')
  const [cycle, setCycle] = useState('valor_q1')
  const [source, setSource] = useState('manual_official_form')
  const [accommodations, setAccommodations] = useState('')
  const [status, setStatus] = useState<OfficialMeasureStatus>('scored')
  const [rawScore, setRawScore] = useState('')
  const [reason, setReason] = useState('')
  const [label, setLabel] = useState('')
  const [started, setStarted] = useState('')
  const [ended, setEnded] = useState('')
  const [elapsed, setElapsed] = useState('')
  const [lastItem, setLastItem] = useState('')
  const [correct, setCorrect] = useState('')
  const [errors, setErrors] = useState('')
  const [selfCorrections, setSelfCorrections] = useState('')
  const [accuracy, setAccuracy] = useState('')
  const [discontinue, setDiscontinue] = useState('not_checked')
  const [interruption, setInterruption] = useState('')
  const [fidelity, setFidelity] = useState('')
  const [reviewed, setReviewed] = useState(false)
  const [correctionReason, setCorrectionReason] = useState('')
  const [observation, setObservation] = useState<TeacherObservation>(blankObservation)
  const [editText, setEditText] = useState('')
  const [approvedText, setApprovedText] = useState('')
  const [planRecorded, setPlanRecorded] = useState(false)
  const [planId, setPlanId] = useState('')
  const [artifact, setArtifact] = useState<OfficialTeacherArtifact | null>(null)
  const [followUps, setFollowUps] = useState<OfficialTeacherFollowUp[]>([])
  const [followUpText, setFollowUpText] = useState('')
  const [followUpNext, setFollowUpNext] = useState('')
  const [followUpMode, setFollowUpMode] = useState<'in_person' | 'offline'>('in_person')
  const [followUpDate, setFollowUpDate] = useState(dateOnly)

  const refresh = useCallback(async (id?: string) => {
    const items = await fetchOfficialAssessments(token, campusId, learnerId)
    setRecords(items)
    const chosen = id || selectedId || items[items.length - 1]?.assessment_id || ''
    if (!chosen) { setSelectedId(''); setCurrent(null); setProposal(null); setPlanId(''); setArtifact(null); setFollowUps([]); return }
    setSelectedId(chosen)
    const record = await fetchOfficialAssessment(token, campusId, learnerId, chosen)
    setCurrent(record)
    setReviewed(Boolean(record.scores?.[0]?.official_marks?.teacher_reviewed))
    setStatus(record.scores?.[0]?.administration_status ?? 'scored')
    setRawScore(record.scores?.[0]?.raw_score == null ? '' : String(record.scores[0].raw_score))
    try {
      const packet = await fetchOfficialDataDay(token, campusId, learnerId, record.instructional_cycle)
      setProposal(packet.proposed_next_steps.find(p => p.assessment_id === chosen) ?? null)
      const saved = packet.prior_teacher_decisions.find(d =>
        d.assessment_id === chosen && d.outcome?.plan_recorded)
      setPlanRecorded(Boolean(saved))
      setPlanId(saved?.outcome.plan_id ?? '')
    } catch { setProposal(null) }
  }, [token, campusId, learnerId, selectedId])

  useEffect(() => {
    let live = true
    setSelectedId(''); setCurrent(null); setProposal(null); setApprovedText(''); setPlanId(''); setArtifact(null); setFollowUps([])
    fetchOfficialAssessments(token, campusId, learnerId).then(items => {
      if (!live) return
      setRecords(items)
      if (items.length) setSelectedId(items[items.length - 1].assessment_id)
    }).catch(() => { if (live) setMessage('Official record unavailable for this assignment.') })
    return () => { live = false }
  }, [token, campusId, learnerId])

  useEffect(() => {
    if (!selectedId) return
    let live = true
    fetchOfficialAssessment(token, campusId, learnerId, selectedId).then(async record => {
      if (!live) return
      setCurrent(record)
      setReviewed(Boolean(record.scores?.[0]?.official_marks?.teacher_reviewed))
      setStatus(record.scores?.[0]?.administration_status ?? 'scored')
      setRawScore(record.scores?.[0]?.raw_score == null ? '' : String(record.scores[0].raw_score))
      try {
        const dataDay = await fetchOfficialDataDay(token, campusId, learnerId, record.instructional_cycle)
        if (live) {
          setProposal(dataDay.proposed_next_steps.find(p => p.assessment_id === selectedId) ?? null)
          const saved = dataDay.prior_teacher_decisions.find(d => d.assessment_id === selectedId && d.outcome?.plan_recorded)
          setPlanRecorded(Boolean(saved))
          setPlanId(saved?.outcome.plan_id ?? '')
          setArtifact(null); setFollowUps([])
        }
      } catch { if (live) setProposal(null) }
    }).catch(() => { if (live) setMessage('Assessment is unavailable or your assignment changed.') })
    return () => { live = false }
  }, [selectedId, token, campusId, learnerId])

  async function perform(work: () => Promise<void>) {
    setBusy(true); setMessage('')
    try { await work() } catch (error) {
      if (error instanceof SchoolAuthorizationRequiredError && onSchoolAuthorizationRequired) {
        onSchoolAuthorizationRequired(); return
      }
      setMessage(describeFailure(error, { action: 'save the official assessment',
        forbidden: 'Your campus assignment is no longer authorized.',
        conflict: 'The record changed. Reload it before continuing.',
        invalid: 'Review the official form fields and permitted lifecycle state.' }))
    } finally { setBusy(false) }
  }

  async function createRecord() {
    await perform(async () => {
      const created = await createOfficialAssessment(token, campusId, learnerId, {
        instrument: 'dibels8', edition, measure, grade, form_id: formId.trim(),
        administration_purpose: purpose, instructional_cycle: cycle,
        administered_at: `${date}T12:00:00Z`,
        report_source: source.trim(), official_benchmark_window: purpose === 'benchmark' ? window : 'none',
        accommodations: accommodations.trim() ? [accommodations.trim()] : [],
      })
      setMessage('Official record created. The teacher must advance its administration state.')
      await refresh(created.assessment_id)
    })
  }

  async function advance(action: string, resolution?: string) {
    if (!current) return
    await perform(async () => {
      const updated = await transitionOfficialAssessment(
        token, campusId, learnerId, current.assessment_id, action, current.state, resolution)
      setCurrent(updated)
      setMessage(`Assessment: ${readable(updated.state)}.`)
      await refresh(current.assessment_id)
    })
  }

  async function supersede() {
    if (!current || correctionReason.trim().length < 3) return
    await perform(async () => {
      const replacement = await supersedeOfficialAssessment(
        token, campusId, learnerId, current.assessment_id, correctionReason.trim())
      setCorrectionReason('')
      setMessage('Correction draft created. The prior finalized assessment remains immutable and audit-linked.')
      await refresh(replacement.assessment_id)
    })
  }

  async function saveScore() {
    if (!current) return
    await perform(async () => {
      const isScored = status === 'scored'
      const raw = isScored ? optionalNumber(rawScore) : null
      const entry: OfficialScoreEntry = {
        measure: current.measure, administration_status: status,
        raw_score: raw, score_unit: isScored ? units[current.measure] : null,
        reason: isScored ? null : reason.trim(),
        benchmark_label: isScored && label ? label as OfficialScoreEntry['benchmark_label'] : null,
        calculation_version: 'as_printed_on_source_report',
        official_marks: {
          started_at: started ? new Date(started).toISOString() : null,
          ended_at: ended ? new Date(ended).toISOString() : null,
          elapsed_seconds: optionalNumber(elapsed), last_item_attempted: optionalNumber(lastItem),
          correct_marks: optionalNumber(correct), error_marks: optionalNumber(errors),
          self_corrections: optionalNumber(selfCorrections), accuracy_percent: optionalNumber(accuracy),
          discontinue_rule_result: discontinue as 'not_checked',
          interruption: interruption.trim() || null,
          administration_fidelity_note: fidelity.trim() || null, teacher_reviewed: reviewed,
        },
      }
      const updated = await enterOfficialScores(token, campusId, learnerId, current.assessment_id, [entry])
      setCurrent(updated)
      setMessage('Measure status and transcribed marks saved. No official score was calculated.')
    })
  }

  async function saveObservation() {
    if (!current) return
    await perform(async () => {
      await recordOfficialObservation(token, campusId, learnerId, current.assessment_id, observation)
      setMessage('Teacher observation attached to the immutable official result, separately.')
      await refresh(current.assessment_id)
    })
  }

  async function draft() {
    if (!current) return
    await perform(async () => {
      const p = await requestOfficialProposal(token, campusId, learnerId, current.assessment_id)
      if ('abstained' in p && p.abstained) {
        setMessage(p.reason)
        return
      }
      setProposal(p as OfficialProposal)
      setEditText((p as OfficialProposal).proposed_next_step)
      await refresh(current.assessment_id)
    })
  }

  async function decide(action: 'approve' | 'edit' | 'reject') {
    if (!current || !proposal) return
    await perform(async () => {
      const result = await decideOfficialProposal(token, campusId, learnerId, current.assessment_id,
        proposal.proposal_id, { action, expected_version: proposal.version,
          ...(action === 'edit' ? { edited_text: editText.trim() } : {}) })
      setProposal(null)
      setApprovedText(result.authorized_text || '')
      setMessage('Teacher decision recorded. Nothing was sent to a learner.')
      await refresh(current.assessment_id)
    })
  }

  async function savePlan() {
    if (!current || !approvedText.trim()) return
    await perform(async () => {
      const result = await recordOfficialPlan(token, campusId, learnerId, current.assessment_id, approvedText)
      setPlanRecorded(true)
      setPlanId(result.plan_id)
      setMessage(`Instructional plan saved; delivery state: ${result.delivery_state}.`)
      await refresh(current.assessment_id)
    })
  }

  async function prepareTeacherArtifact() {
    if (!current || !planId) return
    await perform(async () => {
      const content = await fetchTeacherArtifact(token, campusId, learnerId, current.assessment_id, planId)
      setArtifact(content)
      setMessage('Teacher-approved material ready for your in-person or offline instruction. Nothing was sent to the learner.')
    })
  }

  async function loadFollowUps() {
    if (!current || !planId) return
    await perform(async () => {
      setFollowUps(await fetchTeacherFollowUps(token, campusId, learnerId, current.assessment_id, planId))
    })
  }

  async function saveFollowUp() {
    if (!current || !planId || followUpText.trim().length < 3) return
    await perform(async () => {
      await recordTeacherFollowUp(token, campusId, learnerId, current.assessment_id, planId, {
        observed_on: followUpDate, teaching_mode: followUpMode,
        observation: followUpText.trim(),
        ...(followUpNext.trim() ? { next_step: followUpNext.trim() } : {}),
      })
      setFollowUpText(''); setFollowUpNext('')
      setFollowUps(await fetchTeacherFollowUps(token, campusId, learnerId, current.assessment_id, planId))
      setMessage('Your follow-up was saved as a teacher observation, not an official reassessment.')
    })
  }

  const canScore = current?.state === 'IN_PROGRESS' || current?.state === 'COMPLETED_PENDING_REVIEW'
  const scored = status === 'scored'
  const goodScore = !scored ? reason.trim().length > 0 :
    rawScore.trim().length > 0 && Number.isFinite(Number(rawScore)) && Number(rawScore) >= 0 &&
    (current?.measure !== 'ORF_ACCURACY' || Number(rawScore) <= 100)
  const markFields = [
    { name: 'Elapsed seconds', value: elapsed, set: setElapsed },
    { name: 'Last item attempted', value: lastItem, set: setLastItem },
    { name: 'Correct marks', value: correct, set: setCorrect },
    { name: 'Error marks', value: errors, set: setErrors },
    { name: 'Self-corrections', value: selfCorrections, set: setSelfCorrections },
    { name: 'Accuracy (%)', value: accuracy, set: setAccuracy },
  ]

  return (
    <section aria-label="Official assessment and teacher observation" className="border rounded-xl p-4 space-y-4 bg-slate-50">
      <header className="space-y-1">
        <h3 className="font-semibold">Official assessment record + teacher observation</h3>
        <p className="text-xs text-slate-700">
          Use <a className="underline" href="https://dibels.uoregon.edu/materials/dibels" target="_blank" rel="noopener noreferrer">
          authorized official DIBELS 8 materials</a> separately. Bede records educator-entered marks and decisions,
          never test passages, prompts, student responses or proprietary forms.
        </p>
      </header>
      <div className="grid lg:grid-cols-2 gap-4">
        <div className="rounded-xl border p-3 bg-white space-y-3">
          <h4 className="font-semibold text-sm">1. Official assessment record</h4>
          <p className="text-xs text-slate-600">Learner: {learnerName} · Campus UUID: {campusId}</p>
          <div className="grid sm:grid-cols-2 gap-2">
            <label className="text-xs">Grade
              <select className={input} value={grade} onChange={e => setGrade(e.target.value as DibelsGrade)}>
                {grades.map(g => <option key={g} value={g}>{g}</option>)}
              </select>
            </label>
            <label className="text-xs">DIBELS measure
              <select className={input} value={measure} onChange={e => setMeasure(e.target.value)}>
                {measures.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
            </label>
            <label className="text-xs">Edition
              <input className={input} maxLength={32} value={edition} onChange={e => setEdition(e.target.value)} />
            </label>
            <label className="text-xs">Official form identifier
              <input className={input} maxLength={64} value={formId} onChange={e => setFormId(e.target.value)} />
            </label>
            <label className="text-xs">Assessment date
              <input type="date" className={input} value={date} onChange={e => setDate(e.target.value)} />
            </label>
            <label className="text-xs">Purpose
              <select className={input} value={purpose} onChange={e => { setPurpose(e.target.value as typeof purpose); setWindow('none') }}>
                <option value="progress_monitoring">Progress monitoring</option><option value="benchmark">Benchmark</option>
              </select>
            </label>
            <label className="text-xs">Benchmark period
              <select className={input} value={window} disabled={purpose !== 'benchmark'}
                onChange={e => setWindow(e.target.value as typeof window)}>
                <option value="none">Not set</option><option value="BOY">Beginning</option>
                <option value="MOY">Middle</option><option value="EOY">End</option>
              </select>
            </label>
            <label className="text-xs">Valor Data Day cycle
              <select className={input} value={cycle} onChange={e => setCycle(e.target.value)}>
                {['valor_q1', 'valor_q2', 'valor_q3', 'valor_q4'].map(x => <option key={x} value={x}>{x.replace('valor_', 'Valor ').toUpperCase()}</option>)}
              </select>
            </label>
            <label className="text-xs">Source system
              <select className={input} value={source} onChange={e => setSource(e.target.value)}>
                <option value="manual_official_form">Official form (manual entry)</option>
                <option value="mclass_official_report">mCLASS official report</option>
                <option value="dds_official_report">DIBELS Data System report</option>
              </select>
            </label>
            <label className="text-xs">Accommodation (if any)
              <input className={input} maxLength={120} value={accommodations} onChange={e => setAccommodations(e.target.value)} />
            </label>
          </div>
          <p className="text-xs text-slate-600">Administrator is the verified signed-in educator. Benchmark records require campus-approved forms; the server enforces this.</p>
          <button type="button" className="rounded-lg border px-3 py-2 text-sm disabled:opacity-40" disabled={busy || !formId.trim() || !edition.trim()}
            onClick={() => void createRecord()}>Create official record</button>
          {records.length > 0 && (
            <label className="block text-xs">Existing official records
              <select className={input} value={selectedId} onChange={e => { setSelectedId(e.target.value); setApprovedText('') }}>
                {records.map(r => <option key={r.assessment_id} value={r.assessment_id}>{r.measure} · {r.grade} · {r.form_id} · {readable(r.state)}</option>)}
              </select>
            </label>
          )}
          {current && <>
            <p className="text-xs font-semibold">Administration: {readable(current.state)} · {current.measure} · {current.form_id}</p>
            <p className="text-xs text-slate-600">Teacher-reviewed status: {reviewed ? 'reviewed' : 'pending review'} · snapshot: {current.snapshot_sha256 ? 'immutable' : 'not finalized'}</p>
            <div className="flex flex-wrap gap-2">
              {current.state === 'DRAFT' && <button className="border rounded-lg px-3 py-2 text-xs" type="button" disabled={busy} onClick={() => void advance('mark_ready')}>Mark ready</button>}
              {current.state === 'READY_FOR_ADMINISTRATION' && <button className="border rounded-lg px-3 py-2 text-xs" type="button" disabled={busy} onClick={() => void advance('start')}>Start record</button>}
              {current.state === 'IN_PROGRESS' && <button className="border rounded-lg px-3 py-2 text-xs" type="button" disabled={busy} onClick={() => void advance('submit')}>Complete pending review</button>}
              {current.state === 'COMPLETED_PENDING_REVIEW' && <button className="border rounded-lg px-3 py-2 text-xs" type="button" disabled={busy || !current.scores?.length || !reviewed}
                onClick={() => void advance('finalize')}>Finalize official record</button>}
              {current.state === 'IN_PROGRESS' && <button className="border rounded-lg px-3 py-2 text-xs" type="button" disabled={busy}
                onClick={() => void advance('interrupt')}>Mark interrupted</button>}
              {(current.state === 'IN_PROGRESS' || current.state === 'COMPLETED_PENDING_REVIEW') &&
                <button className="border rounded-lg px-3 py-2 text-xs disabled:opacity-40" type="button"
                  disabled={busy || correctionReason.trim().length < 3}
                  onClick={() => void advance('invalidate', correctionReason)}>Mark invalid</button>}
              {current.state === 'INTERRUPTED' && <button className="border rounded-lg px-3 py-2 text-xs disabled:opacity-40"
                type="button" disabled={busy || correctionReason.trim().length < 3}
                onClick={() => void advance('resume', correctionReason)}>Resume with resolution</button>}
              {current.state === 'INVALID_ADMINISTRATION' && <button className="border rounded-lg px-3 py-2 text-xs disabled:opacity-40"
                type="button" disabled={busy || correctionReason.trim().length < 3}
                onClick={() => void advance('resolve_invalid', correctionReason)}>Resolve invalid record</button>}
              {(['DRAFT', 'READY_FOR_ADMINISTRATION', 'IN_PROGRESS', 'COMPLETED_PENDING_REVIEW', 'INTERRUPTED', 'INVALID_ADMINISTRATION']
                .includes(current.state)) && <button className="border border-red-200 rounded-lg px-3 py-2 text-xs disabled:opacity-40"
                  type="button" disabled={busy || correctionReason.trim().length < 3}
                  onClick={() => void advance('void', correctionReason)}>Void with reason</button>}
            </div>
            <label className="text-xs block">Resolution or correction reason
              <textarea className={input} maxLength={500} value={correctionReason} onChange={e => setCorrectionReason(e.target.value)}
                placeholder="Required for voids, corrections and interrupted/invalid resolutions"/>
            </label>
            {(['FINALIZED', 'EVIDENCE_AVAILABLE', 'TEACHER_DECISION_PENDING',
              'TEACHER_DECISION_RECORDED', 'INSTRUCTIONAL_PLAN_READY',
              'PROGRESS_MONITORING_SCHEDULED'].includes(current.state)) &&
              <button type="button" className="border rounded-lg px-3 py-2 text-xs disabled:opacity-40"
                disabled={busy || correctionReason.trim().length < 3} onClick={() => void supersede()}>
                Supersede finalized record with audited correction
              </button>}
            {canScore && <div className="space-y-2 border-t pt-3">
              <h5 className="font-semibold text-xs">Live marks and transcribed score</h5>
              <label className="text-xs block">Measure administration status
                <select className={input} value={status} onChange={e => { setStatus(e.target.value as OfficialMeasureStatus); setRawScore('') }}>
                  <option value="scored">Scored</option>{noScore.map(s => <option key={s} value={s}>{readable(s)}</option>)}
                </select>
              </label>
              {scored ? <>
                <label className="text-xs block">Official raw score ({units[current.measure]})
                  <input type="number" min="0" step="any" className={input} value={rawScore} onChange={e => setRawScore(e.target.value)} />
                </label>
                <label className="text-xs block">Risk / benchmark classification as printed
                  <select className={input} value={label} onChange={e => setLabel(e.target.value)}>
                    <option value="">Not provided</option>
                    {['Well Below Benchmark', 'Below Benchmark', 'At Benchmark', 'Above Benchmark'].map(x => <option key={x}>{x}</option>)}
                  </select>
                </label>
              </> : <label className="text-xs block">Reason (required; never a numeric zero)
                <textarea className={input} maxLength={300} value={reason} onChange={e => setReason(e.target.value)}/>
              </label>}
              <div className="grid sm:grid-cols-2 gap-2">
                <label className="text-xs">Start time<input className={input} type="datetime-local" value={started} onChange={e => setStarted(e.target.value)}/></label>
                <label className="text-xs">End time<input className={input} type="datetime-local" value={ended} onChange={e => setEnded(e.target.value)}/></label>
                {markFields.map(f => <label className="text-xs" key={f.name}>{f.name}
                  <input type="number" step="any" min="0" className={input} value={f.value} onChange={e => f.set(e.target.value)}/>
                </label>)}
                <label className="text-xs">Discontinue rule (official result)
                  <select className={input} value={discontinue} onChange={e => setDiscontinue(e.target.value)}>
                    {['not_checked', 'met', 'not_met', 'not_applicable'].map(x => <option key={x} value={x}>{readable(x)}</option>)}
                  </select>
                </label>
                <label className="text-xs">Interruption
                  <input className={input} maxLength={300} value={interruption} onChange={e => setInterruption(e.target.value)}/>
                </label>
              </div>
              <label className="text-xs block">Administration fidelity note
                <textarea className={input} maxLength={500} value={fidelity} onChange={e => setFidelity(e.target.value)}/>
              </label>
              <label className="text-xs flex items-center gap-2">
                <input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)}/> Teacher reviewed transcription
              </label>
              <button type="button" className="border rounded-lg px-3 py-2 text-xs disabled:opacity-40" disabled={busy || !goodScore}
                onClick={() => void saveScore()}>Save official measure result</button>
              <p className="text-xs text-slate-600">Blank or skipped is never zero. Bede does not calculate composites or risk bands. Use the official report for a composite after required subtests are complete.</p>
            </div>}
            {current.scores?.length ? <ul className="text-xs border-t pt-2">{current.scores.map(s =>
              <li key={s.measure}>{s.measure}: {readable(s.administration_status)} — {s.raw_score ?? 'no score'} {s.score_unit ?? ''}</li>)}</ul> : null}
          </>}
        </div>
        <div className="rounded-xl border p-3 bg-white space-y-3">
          <h4 className="font-semibold text-sm">2. Teacher observation and decision</h4>
          <p className="text-xs text-slate-600">Separate educator interpretation; never changes the official scoring record.</p>
          {Object.entries({
            accuracy_fluency: 'Accuracy and fluency notes',
            error_patterns: 'Error patterns',
            administration_circumstances: 'Attention / administration circumstances',
            narration_comprehension: 'Narration and comprehension',
            curriculum_already_taught: 'Curriculum already taught',
            teacher_interpretation: 'Teacher interpretation',
            suggested_next_step: 'Suggested next step',
          }).map(([key, name]) => <label key={key} className="block text-xs">{name}
            <textarea className={input} rows={2} maxLength={key === 'teacher_interpretation' || key === 'suggested_next_step' ? 350 : 250}
              value={observation[key as keyof TeacherObservation] ?? ''}
              onChange={e => setObservation(v => ({ ...v, [key]: e.target.value }))}/>
          </label>)}
          <button className="border rounded-lg px-3 py-2 text-sm disabled:opacity-40" type="button"
            disabled={busy || current?.state !== 'FINALIZED' || !hasObservation(observation)}
            onClick={() => void saveObservation()}>Record teacher observation</button>
          <p className="text-xs text-slate-600">Finalize the standardized record before recording interpretation. Observations are bound to its immutable snapshot.</p>
          {current?.state === 'EVIDENCE_AVAILABLE' &&
            <button type="button" className="border rounded-lg px-3 py-2 text-sm" disabled={busy} onClick={() => void draft()}>
              Request evidence-linked recommendation</button>}
          {proposal && <div className="border border-amber-300 rounded-lg p-3 space-y-2">
            <p className="text-xs font-semibold">Bede draft — teacher approval required</p>
            <p className="text-sm">{proposal.proposed_next_step}</p>
            <label className="block text-xs">Edit the proposed instruction
              <textarea className={input} maxLength={1200} value={editText || proposal.proposed_next_step}
                onChange={e => setEditText(e.target.value)}/>
            </label>
            <div className="flex flex-wrap gap-2">
              {(['approve', 'edit', 'reject'] as const).map(a =>
                <button className="border rounded-lg px-3 py-2 text-xs disabled:opacity-40" type="button" key={a} disabled={busy}
                  onClick={() => void decide(a)}>{a[0].toUpperCase() + a.slice(1)}</button>)}
            </div>
          </div>}
          {(approvedText || (current?.state === 'TEACHER_DECISION_RECORDED' && !proposal)) &&
            <div className="border rounded-lg p-2">
              <p className="text-xs font-semibold">Teacher-approved plan</p>
              <textarea className={input} maxLength={2000} value={approvedText}
                onChange={e => setApprovedText(e.target.value)} placeholder="Enter the teacher-approved plan text"/>
              <button type="button" className="border rounded-lg px-3 py-2 text-xs mt-2 disabled:opacity-40"
                disabled={busy || !approvedText.trim() || planRecorded} onClick={() => void savePlan()}>
                {planRecorded ? 'Plan recorded' : 'Record instructional plan'}</button>
            </div>}
          {planRecorded && planId && <div className="rounded-xl border p-3 space-y-3" aria-label="Teacher artifact and follow-up">
            <h4 className="font-semibold text-sm">3. Prepare, teach, and follow up</h4>
            <p className="text-xs text-slate-600">Only an authorized teacher can prepare this material after recording a plan.
              It is for teacher use during offline or in-person lessons. Bede will not distribute it or change any roster.</p>
            <button type="button" disabled={busy} onClick={() => void prepareTeacherArtifact()}
              className="border rounded-lg px-3 py-2 text-sm disabled:opacity-40">Prepare teacher-use artifact</button>
            {artifact && <article className="rounded-lg border bg-white p-3 space-y-2" aria-label="Teacher-approved instructional handout">
              <p className="font-semibold">Bede · Teacher instructional plan</p>
              <p className="text-xs">Learner: {learnerName} · Approved decision: {artifact.approval_action} · Offline only</p>
              <p className="text-sm whitespace-pre-wrap">{artifact.plan_text}</p>
              <p className="text-xs text-slate-600">{artifact.disclaimer}</p>
              <button type="button" className="border rounded-lg px-3 py-2 text-xs" onClick={() => document.defaultView?.print()}>
                Print teacher material</button>
            </article>}
            <div className="border-t pt-3 space-y-2">
              <h5 className="font-semibold text-sm">After teaching: record your observation</h5>
              <p className="text-xs text-slate-600">This is your observation of an in-person or offline lesson, not a new DIBELS score or automatic placement decision.</p>
              <label className="block text-xs">Date taught
                <input className={input} type="date" max={dateOnly()} value={followUpDate}
                  onChange={e => setFollowUpDate(e.target.value)}/></label>
              <label className="block text-xs">Teaching method
                <select className={input} value={followUpMode}
                  onChange={e => setFollowUpMode(e.target.value as 'in_person' | 'offline')}>
                  <option value="in_person">In person</option><option value="offline">Offline activity</option>
                </select></label>
              <label className="block text-xs">What you observed
                <textarea className={input} maxLength={1200} rows={3} value={followUpText}
                  onChange={e => setFollowUpText(e.target.value)}/></label>
              <label className="block text-xs">Possible next step (optional, not assigned)
                <textarea className={input} maxLength={600} value={followUpNext}
                  onChange={e => setFollowUpNext(e.target.value)}/></label>
              <div className="flex flex-wrap gap-2">
                <button type="button" disabled={busy || followUpText.trim().length < 3 || !followUpDate || followUpDate > dateOnly()}
                  onClick={() => void saveFollowUp()} className="border rounded-lg px-3 py-2 text-sm disabled:opacity-40">Save teacher follow-up</button>
                <button type="button" disabled={busy} onClick={() => void loadFollowUps()}
                  className="border rounded-lg px-3 py-2 text-sm disabled:opacity-40">Review follow-ups</button>
              </div>
              {followUps.length > 0 && <ul className="text-sm space-y-2">{followUps.map(item =>
                <li key={item.follow_up_id} className="rounded-lg border p-2">
                  <strong>{item.observed_on} · {item.teaching_mode === 'in_person' ? 'In person' : 'Offline'}</strong>
                  <p className="whitespace-pre-wrap">{item.observation}</p>
                  {item.next_step && <p className="text-xs">Suggested teacher next step: {item.next_step}</p>}
                </li>)}</ul>}
            </div>
          </div>}
          <p className="text-xs font-medium text-emerald-800">Teacher delivers instruction. Bede never launches learner sessions. Delivery state: NOT_REQUESTED.</p>
        </div>
      </div>
      {message && <p role="status" className="text-xs text-slate-700">{message}</p>}
    </section>
  )
}
