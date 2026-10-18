import { useCallback, useEffect, useMemo, useState } from 'react'
import { CheckCircle2, ClipboardList, FileCheck2, PencilLine, XCircle } from 'lucide-react'
import PilotOfficialAssessmentForm from './PilotOfficialAssessmentForm'
import {
  decidePilotRecommendation, fetchInstructorFrameworks, fetchPilotEvidence,
  fetchPilotLearners, fetchPilotLedger, fetchPilotRecommendations,
  recordPilotEvidence, requestPilotRecommendation,
} from '../services/api'
import { describeFailure } from '../utils/requestFailure'
import type { FailureContext } from '../utils/requestFailure'
import type {
  AssessmentFrameworkMetadata, DibelsGrade, DibelsWindow, EducatorAssessmentBand,
  PilotEvidence, PilotLearner, PilotLedger, PilotRecommendation,
} from '../services/api'

/**
 * Valor pilot G2: the complete teacher journey on campus-scoped learner IDs.
 *
 *   evidence -> source-linked draft -> approve / edit / reject -> authorized
 *   instruction, with the server's hash-chained audit status shown.
 *
 * Renders nothing unless the server returns pilot learners for this
 * educator, so a non-pilot deployment sees no change. Every call names an
 * immutable learner id; the display name is shown, never used as a key.
 * A draft is labelled a draft until a teacher decides, and only an approved
 * or edited recommendation is ever shown as instruction.
 */
const field = 'block w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm'
const TODAY = () => new Date().toISOString().slice(0, 10)
const label = (v: string | null | undefined) => (v ?? 'not reported').replaceAll('_', ' ')

// What to say when a request fails, per action. Built from the status class
// only (utils/requestFailure.ts), never from the error's own text.
const NO_ACCESS = 'You may no longer be assigned to this learner. Ask your administrator to check your assignment.'
export const FAILURES = {
  load: { action: "load this learner's records", forbidden: NO_ACCESS,
    notFound: 'This learner may no longer be assigned to you. Refresh the page to see your current list.' },
  evidence: { action: 'save the evidence', forbidden: NO_ACCESS,
    invalid: 'Check the score, unit, grade, testing window and category against the official report, then save again.' },
  draft: { action: 'draft a recommendation', forbidden: NO_ACCESS,
    conflict: 'There is already a draft awaiting your decision. Approve, edit or reject it first.' },
  decide: { action: 'record your decision', forbidden: NO_ACCESS,
    conflict: 'This draft was already decided or changed, possibly in another window. The list has been refreshed; review it before deciding again.',
    invalid: 'Your edited instruction or note was not accepted. Check its length and try again.' },
} satisfies Record<string, FailureContext>

export default function PilotTeacherJourney({ token }: { token: string }) {
  const [learners, setLearners] = useState<PilotLearner[]>([])
  const [learnerId, setLearnerId] = useState('')
  const [evidence, setEvidence] = useState<PilotEvidence[]>([])
  const [recs, setRecs] = useState<PilotRecommendation[]>([])
  const [ledger, setLedger] = useState<PilotLedger | null>(null)
  const [catalog, setCatalog] = useState<AssessmentFrameworkMetadata | null>(null)
  const [abstention, setAbstention] = useState('')
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  // Evidence form
  const [measure, setMeasure] = useState('PSF')
  const [grade, setGrade] = useState<DibelsGrade>('1')
  const [windowName, setWindowName] = useState<DibelsWindow>('middle_of_year')
  const [assessedOn, setAssessedOn] = useState(TODAY())
  const [score, setScore] = useState('')
  const [band, setBand] = useState<EducatorAssessmentBand>('not_reported')
  const [source, setSource] = useState('')
  const [showOfficial, setShowOfficial] = useState(false)

  useEffect(() => {
    let active = true
    fetchPilotLearners(token).then(rows => {
      if (!active) return
      setLearners(rows)
      setLearnerId(rows[0]?.learner_id ?? '')
    }).catch(() => { /* pilot disabled or no campus grant: render nothing */ })
    fetchInstructorFrameworks(token).then(all => {
      if (active) setCatalog(all.find(f => f.id === 'dibels8') ?? null)
    }).catch(() => {})
    return () => { active = false }
  }, [token])

  const reload = useCallback(async (id: string) => {
    if (!id) return
    const [ev, rs, lg] = await Promise.all([
      fetchPilotEvidence(token, id), fetchPilotRecommendations(token, id), fetchPilotLedger(token, id),
    ])
    setEvidence(ev); setRecs(rs); setLedger(lg)
  }, [token])

  useEffect(() => {
    setAbstention(''); setEditing(false); setMessage('')
    reload(learnerId).catch(e => setMessage(describeFailure(e, FAILURES.load)))
  }, [learnerId, reload])

  const pending = recs.find(r => r.status === 'pending') ?? null
  const authorized = recs.find(r => r.status === 'approved' || r.status === 'edited') ?? null
  const evidenceById = useMemo(() => new Map(evidence.map(e => [e.evidence_id, e])), [evidence])
  const measures = catalog?.supported_measures.filter(m => m !== 'COMPOSITE') ?? ['PSF']
  const unit = catalog?.measure_units?.[measure] ?? 'correct_per_minute'

  if (!learners.length) return null

  const run = async (work: () => Promise<void>, failure: FailureContext, onFail?: () => Promise<void>) => {
    setBusy(true); setMessage('')
    try { await work() } catch (e) {
      setMessage(describeFailure(e, failure))
      if (onFail) await onFail().catch(() => {})
    } finally { setBusy(false) }
  }

  const saveEvidence = () => run(async () => {
    await recordPilotEvidence(token, learnerId, {
      framework: 'dibels8', measure, assessed_on: assessedOn, source_name: source.trim(),
      score: Number(score), score_unit: unit, reported_band: band,
      assessed_grade: grade, assessment_window: windowName,
    })
    setScore(''); setMessage('Evidence recorded.')
    await reload(learnerId)
  }, FAILURES.evidence)

  const draft = () => run(async () => {
    const out = await requestPilotRecommendation(token, learnerId)
    setAbstention(out.abstained ? out.reason : '')
    await reload(learnerId)
  }, FAILURES.draft)

  const decideAs = (action: 'approve' | 'edit' | 'reject') => run(async () => {
    if (!pending) return
    await decidePilotRecommendation(token, learnerId, pending.recommendation_id, {
      action, expected_version: pending.version,
      ...(action === 'edit' ? { edited_text: editText.trim() } : {}),
      ...(note.trim() ? { note: note.trim() } : {}),
    })
    setEditing(false); setEditText(''); setNote('')
    setMessage(action === 'reject' ? 'Recommendation rejected and recorded.'
      : 'Decision recorded. The instruction below is ready for teacher use.')
    await reload(learnerId)
  }, FAILURES.decide, () => reload(learnerId))

  return (
    <section aria-label="Pilot teacher journey" className="bg-white border rounded-2xl p-4 space-y-4">
      <div>
        <h2 className="font-semibold flex items-center gap-2"><ClipboardList size={18}/> Review Bede’s suggestions</h2>
        <p className="text-xs text-gray-600">
          Bede can suggest a next step based on your learner’s recorded work. You decide what is helpful.
          Suggestions are not sent to learners automatically. Your choices are saved for your records.
        </p>
      </div>

      <label className="block text-sm">Assigned learner
        <select className={field + ' mt-1'} value={learnerId} onChange={e => setLearnerId(e.target.value)}>
          {learners.map(l => <option key={l.learner_id} value={l.learner_id}>{l.display_name}</option>)}
        </select>
      </label>

      <div>
        <button type="button" className="rounded-lg border border-navy-700 px-3 py-2 text-sm" aria-expanded={showOfficial}
          onClick={() => setShowOfficial(open => !open)}>
          {showOfficial ? 'Close official record' : 'Official DIBELS record + observations'}
        </button>
        {showOfficial && <div className="mt-3">
          <PilotOfficialAssessmentForm key={learnerId} token={token}
            campusId={learners.find(l => l.learner_id === learnerId)?.campus_id ?? ''}
            learnerId={learnerId}
            learnerName={learners.find(l => l.learner_id === learnerId)?.display_name ?? ''}/>
        </div>}
      </div>

      <div className="space-y-2">
        <h3 className="text-sm font-semibold">1. Look at the learner’s work</h3>
        {evidence.length === 0
          ? <p className="text-sm text-gray-500">No evidence recorded for this learner yet.</p>
          : <ul className="text-sm divide-y border rounded-lg">{evidence.map(e => (
              <li key={e.evidence_id} className="px-3 py-2 flex flex-wrap justify-between gap-2">
                <span>{e.measure} · {e.assessed_on}</span>
                <span className="text-gray-600">{label(e.reported_band ?? e.assistance)}</span>
              </li>))}
            </ul>}
        <details className="rounded-lg border p-3">
          <summary className="text-sm font-medium cursor-pointer">Record legacy evidence for Bede draft</summary>
          <p className="text-xs text-gray-600 mt-2">For existing pilot recommendations only. Use the separate official assessment record above for lifecycle, status, marks, and teacher observation. Never enter test items or passages.</p>
          <div className="grid sm:grid-cols-2 gap-3 mt-2">
            <label className="text-sm">Measure
              <select className={field + ' mt-1'} value={measure} onChange={e => setMeasure(e.target.value)}>
                {measures.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
            </label>
            <label className="text-sm">Reported score ({label(unit)})
              <input className={field + ' mt-1'} inputMode="decimal" value={score} onChange={e => setScore(e.target.value)}/>
            </label>
            <label className="text-sm">Grade on report
              <select className={field + ' mt-1'} value={grade} onChange={e => setGrade(e.target.value as DibelsGrade)}>
                {(catalog?.grades ?? ['K', '1', '2', '3', '4', '5', '6', '7', '8']).map(g => <option key={g}>{g}</option>)}
              </select>
            </label>
            <label className="text-sm">Testing window
              <select className={field + ' mt-1'} value={windowName} onChange={e => setWindowName(e.target.value as DibelsWindow)}>
                {(catalog?.windows ?? ['beginning_of_year', 'middle_of_year', 'end_of_year', 'progress_monitoring'])
                  .map(w => <option key={w} value={w}>{label(w)}</option>)}
              </select>
            </label>
            <label className="text-sm">Category as reported
              <select className={field + ' mt-1'} value={band} onChange={e => setBand(e.target.value as EducatorAssessmentBand)}>
                {(['not_reported', 'core_negligible_risk', 'core_minimal_risk', 'strategic_some_risk', 'intensive_at_risk'] as const)
                  .map(b => <option key={b} value={b}>{label(b)}</option>)}
              </select>
            </label>
            <label className="text-sm">Date assessed
              <input type="date" className={field + ' mt-1'} max={TODAY()} value={assessedOn} onChange={e => setAssessedOn(e.target.value)}/>
            </label>
            <label className="text-sm sm:col-span-2">Report source
              <input className={field + ' mt-1'} value={source} onChange={e => setSource(e.target.value)} placeholder="e.g., Fall benchmark report"/>
            </label>
          </div>
          <button type="button" disabled={busy || !score || source.trim().length < 2} onClick={() => void saveEvidence()}
            className="mt-3 rounded-lg bg-navy-700 px-4 py-2 text-sm text-white disabled:opacity-40">Save evidence</button>
        </details>
      </div>

      <div className="space-y-2">
        <h3 className="text-sm font-semibold">2. Ask Bede for a suggestion</h3>
        {!pending && (
          <button type="button" disabled={busy} onClick={() => void draft()}
            className="rounded-lg border border-navy-700 px-4 py-2 text-sm text-navy-800 disabled:opacity-40">
            Ask Bede for a draft
          </button>
        )}
        {abstention && <p role="status" className="text-sm text-amber-800">{abstention}</p>}
        {pending && (
          <div className="rounded-xl border border-amber-300 bg-amber-50 p-3 space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-amber-800">Draft, awaiting your decision</p>
            <p className="text-sm">{pending.proposal}</p>
            <div className="text-xs text-gray-700">
              <p className="font-medium">Based on:</p>
              <ul className="list-disc pl-5">{pending.source_evidence_ids.map((id, i) => {
                const e = evidenceById.get(id)
                return <li key={id}>{e ? `${e.measure} · ${e.assessed_on} · ${label(e.reported_band ?? e.assistance)}` : 'Recorded evidence'}
                  {pending.rationale[i] ? ` (${pending.rationale[i]})` : ''}</li>
              })}</ul>
            </div>
            {editing && (
              <label className="block text-sm">Your instruction
                <textarea className={field + ' mt-1'} rows={3} maxLength={1200}
                  value={editText} onChange={e => setEditText(e.target.value)}/>
              </label>
            )}
            <label className="block text-sm">Note for the audit trail (optional)
              <input className={field + ' mt-1'} maxLength={500} value={note} onChange={e => setNote(e.target.value)}/>
            </label>
            <div className="flex flex-wrap gap-2">
              {!editing ? <>
                <button type="button" disabled={busy} onClick={() => void decideAs('approve')}
                  className="flex items-center gap-1 rounded-lg bg-navy-700 px-3 py-2 text-sm text-white disabled:opacity-40">
                  <CheckCircle2 size={16}/> Approve</button>
                <button type="button" disabled={busy} onClick={() => { setEditing(true); setEditText(pending.proposal) }}
                  className="flex items-center gap-1 rounded-lg border px-3 py-2 text-sm disabled:opacity-40">
                  <PencilLine size={16}/> Edit</button>
                <button type="button" disabled={busy} onClick={() => void decideAs('reject')}
                  className="flex items-center gap-1 rounded-lg border border-red-300 px-3 py-2 text-sm text-red-800 disabled:opacity-40">
                  <XCircle size={16}/> Reject</button>
              </> : <>
                <button type="button" disabled={busy || !editText.trim()} onClick={() => void decideAs('edit')}
                  className="rounded-lg bg-navy-700 px-3 py-2 text-sm text-white disabled:opacity-40">Save edited instruction</button>
                <button type="button" disabled={busy} onClick={() => setEditing(false)}
                  className="rounded-lg border px-3 py-2 text-sm">Cancel edit</button>
              </>}
            </div>
          </div>
        )}
      </div>

      <div className="space-y-2">
        <h3 className="text-sm font-semibold flex items-center gap-2"><FileCheck2 size={16}/> 3. Your approved teaching guidance</h3>
        {authorized?.authorized_instruction
          ? <div className="rounded-xl border border-sage-300 bg-sage-50 p-3 text-sm space-y-1">
              <p>{authorized.authorized_instruction}</p>
              <p className="text-xs text-gray-600">{authorized.status === 'edited' ? 'Edited and recorded' : 'Approved and recorded'} {authorized.decided_at ? new Date(authorized.decided_at).toLocaleDateString() : ''}</p>
              {authorized.delivery_state === 'NOT_REQUESTED' && (
                <p className="text-xs text-gray-600">Not sent to any learner session. Sending is not available in this pilot.</p>
              )}
            </div>
          : <p className="text-sm text-gray-500">No instruction authorized yet.</p>}
        {ledger && ledger.entries.length > 0 && (
          <p className={ledger.chain_valid ? 'text-xs text-gray-600' : 'text-xs font-medium text-amber-900'}>
            Audit trail: {ledger.entries.length} decision{ledger.entries.length === 1 ? '' : 's'} ·{' '}
            {ledger.chain_valid ? 'integrity check passed'
              : "the integrity check did not pass. Your decisions are still saved; tell your administrator before relying on this history."}
          </p>
        )}
      </div>

      {message && <p role="status" className="text-sm text-navy-800">{message}</p>}
    </section>
  )
}
