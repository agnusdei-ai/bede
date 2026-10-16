import { useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'
import {
  deletePilotLearner, fetchEducatorPilotMode, fetchPilotDeletionReceipts,
  fetchPilotOwnerCampuses, fetchPilotOwnerLearners,
} from '../services/api'
import type { PilotDeletionReceipt, PilotOwnerCampus, PilotOwnerLearner } from '../services/api'
import { describeFailure } from '../utils/requestFailure'

/**
 * Owner-only classroom-pilot administration, performed on the real build:
 * choose a campus and learner, and delete that learner's active pilot records
 * with a verifiable receipt. It never claims erasure: backups made earlier may
 * still hold encrypted copies (see RECEIPT_COPY.backups).
 *
 * Shown only when the deployment has the institutional pilot enabled, and it
 * loads nothing until the owner opens it, because every call needs the
 * administrator passkey (the global elevation prompt asks for it).
 *
 * Plain summary first, technical detail second: the receipt's counts,
 * identifiers and SHA-256 sit behind a collapsed disclosure, unchanged, so
 * an administrator can still copy and check them.
 *
 * Deliberately absent: any session plan or "teach this" action. Delivering
 * approved instruction to a learner stays unavailable (Owner Decision 7,
 * #585; docs/EDUCATOR_CLASSROOM_PILOT.md).
 *
 * English only, like the rest of the educator pilot screens
 * (PilotTeacherJourney, EducatorDesk); those surfaces are not yet localized.
 */
const field = 'block w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm'

const PASSKEY_NEEDED =
  'This needs your administrator passkey. Choose the action again and confirm with your passkey when asked.'

// Receipt table keys, named for a reader. Unknown keys fall back to the key.
export const TABLE_LABELS: Record<string, string> = {
  learners: 'Learner record',
  roster_grants: 'Teacher assignments',
  evidence: 'Recorded evidence',
  recommendations: 'Recommendations',
  decisions: 'Decision history',
}

// What a completed deletion did and did not touch. Each sentence is a fact
// about the code: LEARNER_TABLES in routers/pilot_owner.py, the receipt row
// and the single STUDENT_DATA_DELETED audit entry (ids only, asserted by
// tests/test_valor_pilot_owner_flows.py), and `make db-backup`, which has no
// retention period of its own. docs/EDUCATOR_CLASSROOM_PILOT.md quotes these.
export const RECEIPT_COPY = {
  removed:
    "the learner's pilot record, teacher assignments, recorded evidence, recommendations and decision history.",
  remains:
    "this deletion receipt and one entry in the security audit log. Both hold only ID numbers, record counts, " +
    'the date and who performed the deletion (the audit entry also notes the network address the request came ' +
    "from, as every audit entry does), never the learner's name or any learning content. Keep a copy " +
    'of the receipt if you need to show the deletion later.',
  backups:
    'database backups made before this deletion may still hold encrypted copies of these records and could ' +
    'restore them. This deletion does not change or remove any backup, and no backup retention period has ' +
    'been approved yet.',
} as const

const when = (iso: string) => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso
    : d.toLocaleString(undefined, { dateStyle: 'long', timeStyle: 'short' })
}

const fullyRemoved = (r: PilotDeletionReceipt) =>
  Object.values(r.remaining_counts).every(v => v === 0)

function TechnicalDetails({ receipt, onCopy }: {
  receipt: PilotDeletionReceipt
  onCopy: (r: PilotDeletionReceipt) => void
}) {
  // The copied receipt is exactly what the server returned, so an exported
  // copy can be checked against the server's SHA-256.
  const exported: PilotDeletionReceipt = { ...receipt }
  delete exported.hash_verified
  return (
    <details className="mt-2 rounded-lg border bg-white p-2">
      <summary className="cursor-pointer text-xs font-medium text-gray-700">
        Technical details for administrators
      </summary>
      <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        {Object.entries(receipt.deleted_counts).map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-gray-600">{TABLE_LABELS[k] ?? k}</dt>
            <dd>{v} removed, {receipt.remaining_counts[k] ?? 0} remaining</dd>
          </div>
        ))}
        <dt className="text-gray-600">Receipt ID</dt>
        <dd className="font-mono break-all">{receipt.receipt_id}</dd>
        <dt className="text-gray-600">Learner ID</dt>
        <dd className="font-mono break-all">{receipt.learner_id}</dd>
        <dt className="text-gray-600">SHA-256</dt>
        <dd className="font-mono break-all">{receipt.receipt_sha256}</dd>
      </dl>
      <button type="button" onClick={() => onCopy(exported)}
        className="mt-2 text-xs underline">Copy receipt</button>
    </details>
  )
}

export default function PilotOwnerPanel({ token }: { token: string }) {
  const [enabled, setEnabled] = useState(false)
  const [open, setOpen] = useState(false)
  const [campuses, setCampuses] = useState<PilotOwnerCampus[]>([])
  const [campusId, setCampusId] = useState('')
  const [learners, setLearners] = useState<PilotOwnerLearner[]>([])
  const [learnerId, setLearnerId] = useState('')
  const [confirmName, setConfirmName] = useState('')
  const [receipt, setReceipt] = useState<{ name: string; data: PilotDeletionReceipt } | null>(null)
  const [receipts, setReceipts] = useState<PilotDeletionReceipt[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    fetchEducatorPilotMode().then(m => setEnabled(m.enabled)).catch(() => setEnabled(false))
  }, [])

  const run = async (work: () => Promise<void>, onError: (e: unknown) => string) => {
    setBusy(true); setError(''); setNotice('')
    try { await work() } catch (e) { setError(onError(e)) } finally { setBusy(false) }
  }

  const openPanel = () => {
    setOpen(true)
    void run(async () => {
      const [cs, rs] = await Promise.all([fetchPilotOwnerCampuses(token), fetchPilotDeletionReceipts(token)])
      setCampuses(cs); setReceipts(rs)
      setCampusId(cs[0]?.campus_id ?? '')
    }, e => describeFailure(e, { action: 'load the pilot campuses', forbidden: PASSKEY_NEEDED }))
  }

  useEffect(() => {
    if (!open || !campusId) return
    void run(async () => {
      const ls = await fetchPilotOwnerLearners(token, campusId)
      setLearners(ls); setLearnerId(ls[0]?.learner_id ?? '')
    }, e => describeFailure(e, {
      action: 'load the learners for this campus', forbidden: PASSKEY_NEEDED,
      notFound: 'This campus may have been disabled or removed. Refresh the page to see the current list.',
    }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, campusId, token])

  useEffect(() => { setConfirmName('') }, [learnerId])

  if (!enabled) return null
  const learner = learners.find(l => l.learner_id === learnerId)

  const remove = () => run(async () => {
    if (!learner) return
    const name = learner.display_name
    const out = await deletePilotLearner(token, campusId, learnerId, confirmName)
    setReceipt({ name, data: out })
    setReceipts(rs => [{ ...out, hash_verified: true }, ...rs])
    const rest = learners.filter(l => l.learner_id !== learnerId)
    setLearners(rest); setLearnerId(rest[0]?.learner_id ?? '')
  }, e => describeFailure(e, {
    action: "delete this learner's records",
    forbidden: PASSKEY_NEEDED,
    notFound: "This learner's records may already have been deleted. Refresh the page to see the current list.",
    invalid: "The name you typed doesn't match this learner. Check the spelling and try again.",
    server: 'Refresh the page to check whether the learner is still listed, then try again. If it keeps happening, tell your Bede support contact.',
  }))

  const copyReceipt = (r: PilotDeletionReceipt) => {
    const done = navigator.clipboard?.writeText(JSON.stringify(r, null, 2))
    if (!done) {
      setError('Could not copy the receipt. Open the technical details and copy the text by hand.')
      return
    }
    void done.then(() => { setError(''); setNotice('Receipt copied.') },
      () => setError('Could not copy the receipt. Open the technical details and copy the text by hand.'))
  }

  return (
    <section aria-label="Classroom pilot administration" className="bg-white border rounded-2xl p-4 space-y-3">
      <button type="button" aria-expanded={open} onClick={() => (open ? setOpen(false) : openPanel())}
        className="w-full text-left font-semibold text-navy-800">
        Classroom pilot: delete a learner's records {open ? '▴' : '▾'}
      </button>
      {open && <>
        <p className="text-xs text-gray-600">
          For the pilot administrator. Each action asks you to confirm with your administrator
          passkey and is recorded in the audit log.
        </p>
        {campuses.length === 0
          ? (!busy && !error && <p className="text-sm text-gray-500">There are no pilot campuses yet.</p>)
          : <label className="block text-sm">Campus
              <select className={field + ' mt-1'} value={campusId} onChange={e => setCampusId(e.target.value)}>
                {campuses.map(c => <option key={c.campus_id} value={c.campus_id}>{c.title}</option>)}
              </select>
            </label>}
        {campusId && learners.length === 0 && !busy && !error &&
          <p className="text-sm text-gray-500">This campus has no pilot learners.</p>}
        {learners.length > 0 && <label className="block text-sm">Learner
          <select className={field + ' mt-1'} value={learnerId} onChange={e => setLearnerId(e.target.value)}>
            {learners.map(l => <option key={l.learner_id} value={l.learner_id}>{l.display_name}</option>)}
          </select>
        </label>}

        {learner && (
          <div className="rounded-xl border border-gray-300 p-3 space-y-2">
            <h3 className="text-sm font-semibold flex items-center gap-2 text-gray-900">
              <Trash2 size={16} aria-hidden="true"/> Delete {learner.display_name}'s active pilot records
            </h3>
            <p className="text-xs text-gray-700">
              This removes the learner's pilot record, teacher assignments, recorded evidence,
              recommendations and decision history, then checks that nothing remains. Teachers
              assigned to this learner are signed out and will need to sign in again. Bede has no
              undo for this. Backups made earlier are not changed.
            </p>
            <label className="block text-sm">Type <strong>{learner.display_name}</strong> to confirm
              <input className={field + ' mt-1'} value={confirmName} autoComplete="off"
                onChange={e => setConfirmName(e.target.value)}/>
            </label>
            <button type="button" disabled={busy || confirmName.trim() !== learner.display_name}
              onClick={() => void remove()}
              className="rounded-lg bg-red-700 px-4 py-2 text-sm text-white disabled:opacity-40">
              Delete these records
            </button>
          </div>
        )}

        {receipt && (
          <div role="status" className={'rounded-xl border p-3 text-sm space-y-1 ' +
            (fullyRemoved(receipt.data) ? 'border-sage-300 bg-sage-50' : 'border-amber-300 bg-amber-50')}>
            {fullyRemoved(receipt.data)
              ? <>
                  <p className="font-semibold">
                    {receipt.name}'s active pilot records were removed on {when(receipt.data.deleted_at)}.
                  </p>
                  <p className="text-xs text-gray-700"><strong>Removed:</strong> {RECEIPT_COPY.removed}</p>
                  <p className="text-xs text-gray-700"><strong>What remains:</strong> {RECEIPT_COPY.remains}</p>
                  <p className="text-xs text-gray-700"><strong>Backups:</strong> {RECEIPT_COPY.backups}</p>
                </>
              : <p className="font-semibold">
                  Some records were not removed. Nothing further was deleted. Keep the receipt below
                  and send it to your Bede support contact so the remaining records can be checked;
                  do not rely on it as proof of deletion.
                </p>}
            <TechnicalDetails receipt={receipt.data} onCopy={copyReceipt}/>
          </div>
        )}

        {receipts.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-sm font-semibold">Deletion receipts</h3>
            <ul className="space-y-2">
              {receipts.map(r => (
                <li key={r.receipt_id} className="rounded-lg border p-2 text-sm">
                  <p>Pilot records deleted on {when(r.deleted_at)}</p>
                  {r.hash_verified === false
                    ? <p className="text-xs text-amber-900">
                        This receipt's integrity check failed. Keep it and report it; do not rely on it
                        as proof of deletion.
                      </p>
                    : <p className="text-xs text-gray-600">Receipt integrity check passed.</p>}
                  <TechnicalDetails receipt={r} onCopy={copyReceipt}/>
                </li>
              ))}
            </ul>
          </div>
        )}
        {error && <p role="alert" className="text-sm text-red-800">{error}</p>}
        {notice && <p role="status" className="text-sm text-navy-800">{notice}</p>}
      </>}
    </section>
  )
}
