import { useEffect, useState } from 'react'
import { ShieldAlert } from 'lucide-react'
import {
  deletePilotLearner, fetchEducatorPilotMode, fetchPilotDeletionReceipts,
  fetchPilotOwnerCampuses, fetchPilotOwnerLearners, fetchPilotOwnerPlan,
  fetchPilotOwnerSessions, savePilotOwnerPlan,
} from '../services/api'
import type {
  PilotDeletionReceipt, PilotOwnerCampus, PilotOwnerLearner, PilotSessionReceipt,
} from '../services/api'
import { SUBJECTS } from '../types'
import type { Subject } from '../types'

/**
 * Owner-led Valor pilot operations, performed personally on the real build:
 * set each pilot learner's session plan, review session receipts, and delete
 * a pilot learner with a verifiable receipt.
 *
 * Shown only when the deployment has the institutional pilot enabled, and it
 * loads nothing until the owner opens it, because every call here needs the
 * administrator passkey (the global elevation prompt asks for it once).
 */
// Mirrors models/schemas.py VALID_GRADES; tests/test_valor_pilot_owner_flows.py
// fails if the two drift.
const GRADES = ['K', '1', '2', '3', '4', '5', '6', '7', '8'] as const

const field = 'block w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm'

export default function PilotOwnerPanel({ token }: { token: string }) {
  const [enabled, setEnabled] = useState(false)
  const [open, setOpen] = useState(false)
  const [campuses, setCampuses] = useState<PilotOwnerCampus[]>([])
  const [campusId, setCampusId] = useState('')
  const [learners, setLearners] = useState<PilotOwnerLearner[]>([])
  const [learnerId, setLearnerId] = useState('')
  const [grade, setGrade] = useState('1')
  const [subjects, setSubjects] = useState<Subject[]>([])
  const [sessions, setSessions] = useState<PilotSessionReceipt[]>([])
  const [confirmName, setConfirmName] = useState('')
  const [receipt, setReceipt] = useState<PilotDeletionReceipt | null>(null)
  const [receipts, setReceipts] = useState<PilotDeletionReceipt[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    fetchEducatorPilotMode().then(m => setEnabled(m.enabled)).catch(() => setEnabled(false))
  }, [])

  const run = async (work: () => Promise<void>) => {
    setBusy(true); setMessage('')
    try { await work() } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Request failed')
    } finally { setBusy(false) }
  }

  const openPanel = () => {
    setOpen(true)
    void run(async () => {
      const [cs, rs] = await Promise.all([fetchPilotOwnerCampuses(token), fetchPilotDeletionReceipts(token)])
      setCampuses(cs); setReceipts(rs)
      setCampusId(cs[0]?.campus_id ?? '')
    })
  }

  useEffect(() => {
    if (!open || !campusId) return
    void run(async () => {
      const ls = await fetchPilotOwnerLearners(token, campusId)
      setLearners(ls); setLearnerId(ls[0]?.learner_id ?? '')
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, campusId, token])

  useEffect(() => {
    if (!open || !campusId || !learnerId) return
    setConfirmName(''); setReceipt(null)
    void run(async () => {
      const [p, s] = await Promise.all([
        fetchPilotOwnerPlan(token, campusId, learnerId),
        fetchPilotOwnerSessions(token, campusId, learnerId),
      ])
      setGrade(p.plan?.grade ?? '1'); setSubjects(p.plan?.subjects ?? []); setSessions(s)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, campusId, learnerId, token])

  if (!enabled) return null
  const learner = learners.find(l => l.learner_id === learnerId)

  const savePlan = () => run(async () => {
    const out = await savePilotOwnerPlan(token, campusId, learnerId, { grade, subjects })
    setSubjects(out.plan.subjects)
    setLearners(ls => ls.map(l => l.learner_id === learnerId ? { ...l, has_plan: true } : l))
    setMessage('Session plan saved.')
  })

  const remove = () => run(async () => {
    if (!learner) return
    const out = await deletePilotLearner(token, campusId, learnerId, confirmName)
    setReceipt(out)
    setReceipts(rs => [{ ...out, hash_verified: true }, ...rs])
    const rest = learners.filter(l => l.learner_id !== learnerId)
    setLearners(rest); setLearnerId(rest[0]?.learner_id ?? '')
  })

  const copyReceipt = (r: PilotDeletionReceipt) =>
    void navigator.clipboard?.writeText(JSON.stringify(r, null, 2)).then(() => setMessage('Receipt copied.'))

  return (
    <section aria-label="Valor pilot owner" className="bg-white border rounded-2xl p-4 space-y-3">
      <button type="button" onClick={() => (open ? setOpen(false) : openPanel())}
        className="w-full text-left font-semibold text-navy-800">
        Valor pilot: learner plans and deletion {open ? '▴' : '▾'}
      </button>
      {open && <>
        <p className="text-xs text-gray-600">
          Owner-only. Every action here asks for your administrator passkey and is recorded.
        </p>
        {campuses.length === 0
          ? <p className="text-sm text-gray-500">No pilot campuses yet.</p>
          : <label className="block text-sm">Campus
              <select className={field + ' mt-1'} value={campusId} onChange={e => setCampusId(e.target.value)}>
                {campuses.map(c => <option key={c.campus_id} value={c.campus_id}>{c.title}</option>)}
              </select>
            </label>}
        {learners.length > 0 && <label className="block text-sm">Learner
          <select className={field + ' mt-1'} value={learnerId} onChange={e => setLearnerId(e.target.value)}>
            {learners.map(l => <option key={l.learner_id} value={l.learner_id}>
              {l.display_name}{l.has_plan ? '' : ' (no plan)'}
            </option>)}
          </select>
        </label>}

        {learner && <>
          <div className="rounded-xl border p-3 space-y-2">
            <h3 className="text-sm font-semibold">Session plan</h3>
            <label className="block text-sm">Grade
              <select className={field + ' mt-1'} value={grade} onChange={e => setGrade(e.target.value)}>
                {GRADES.map(g => <option key={g} value={g}>{g}</option>)}
              </select>
            </label>
            <fieldset className="grid grid-cols-2 gap-1 text-sm">
              <legend className="mb-1">Subjects a teacher may teach</legend>
              {SUBJECTS.map(s => (
                <label key={s.id} className="flex items-center gap-2">
                  <input type="checkbox" checked={subjects.includes(s.id)}
                    onChange={e => setSubjects(cur => e.target.checked ? [...cur, s.id] : cur.filter(x => x !== s.id))}/>
                  {s.label}
                </label>
              ))}
            </fieldset>
            <button type="button" disabled={busy || subjects.length === 0} onClick={() => void savePlan()}
              className="rounded-lg bg-navy-700 px-4 py-2 text-sm text-white disabled:opacity-40">Save plan</button>
          </div>

          <div className="rounded-xl border p-3 space-y-1 text-sm">
            <h3 className="font-semibold">Session receipts</h3>
            {sessions.length === 0
              ? <p className="text-gray-500">No sessions yet.</p>
              : sessions.map(s => (
                  <p key={s.pilot_session_id} className="font-mono text-xs break-all">
                    {s.started_at} · {s.turns} turns · instruction {s.instruction_sha256 ? s.instruction_sha256.slice(0, 12) : 'none'}
                  </p>))}
          </div>

          <div className="rounded-xl border border-red-200 p-3 space-y-2">
            <h3 className="text-sm font-semibold flex items-center gap-2 text-red-800">
              <ShieldAlert size={16}/> Delete this learner permanently
            </h3>
            <p className="text-xs text-gray-700">
              Removes the learner, grants, evidence, recommendations, decisions, plan and session
              receipts, then re-checks that nothing remains. Ends the assigned teachers' sessions.
              Cannot be undone.
            </p>
            <p className="text-xs font-mono break-all">Learner ID {learner.learner_id}</p>
            <label className="block text-sm">Type the learner's name to confirm
              <input className={field + ' mt-1'} value={confirmName} onChange={e => setConfirmName(e.target.value)}/>
            </label>
            <button type="button" disabled={busy || confirmName.trim() !== learner.display_name}
              onClick={() => void remove()}
              className="rounded-lg bg-red-700 px-4 py-2 text-sm text-white disabled:opacity-40">Delete learner</button>
          </div>
        </>}

        {receipt && (
          <div role="status" className="rounded-xl border border-sage-300 bg-sage-50 p-3 text-xs space-y-1">
            <p className="font-semibold text-sm">Deletion complete</p>
            <p>Removed: {Object.entries(receipt.deleted_counts).map(([k, v]) => `${k} ${v}`).join(', ')}</p>
            <p>Remaining after re-check: {Object.values(receipt.remaining_counts).every(v => v === 0) ? 'none' : 'NOT ZERO'}</p>
            <p className="font-mono break-all">Receipt {receipt.receipt_id} · SHA-256 {receipt.receipt_sha256}</p>
            <button type="button" onClick={() => copyReceipt(receipt)} className="underline">Copy receipt</button>
          </div>
        )}

        {receipts.length > 0 && (
          <div className="text-xs space-y-1">
            <h3 className="text-sm font-semibold">Deletion receipts</h3>
            {receipts.map(r => (
              <p key={r.receipt_id} className="font-mono break-all">
                {r.deleted_at} · {r.learner_id} · {r.hash_verified === false ? 'HASH MISMATCH' : 'verified'}
              </p>))}
          </div>
        )}
        {message && <p role="status" className="text-sm text-navy-800">{message}</p>}
      </>}
    </section>
  )
}
