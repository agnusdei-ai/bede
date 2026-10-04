import { useEffect, useState } from 'react'
import { BadgeCheck, ChevronDown, ChevronUp, Loader2, ScrollText, TriangleAlert } from 'lucide-react'
import { applyLicenseKey, fetchLicenseStatus } from '../services/api'
import { licenseUrgency } from '../utils/licenseUrgency'
import type { LicenseStatus } from '../types'

/**
 * Parent-facing license card — shows the active license and lets the
 * parent paste a renewal or upgrade key. Applying takes effect
 * immediately (no .env edit, no restart): the server verifies the key
 * offline and stores it in the database, where it wins over the key the
 * deployment was installed with. Renders nothing in dev mode (no license
 * configured, none required).
 */
export default function LicenseSettings({ token }: { token: string }) {
  const [expanded, setExpanded] = useState(false)
  const [openedForUrgency, setOpenedForUrgency] = useState(false)
  const [status, setStatus] = useState<LicenseStatus | null | undefined>(undefined)
  const [keyInput, setKeyInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [applied, setApplied] = useState(false)

  useEffect(() => {
    fetchLicenseStatus(token).then(setStatus).catch(() => setStatus(undefined))
  }, [token])

  // Open the card on arrival when the license is genuinely about to stop
  // working. A chip is enough notice for a renewal a month out; it is not
  // enough for one three days out, and a parent landing on this page should
  // not have to click to discover their lessons are about to stop.
  //
  // `openedForUrgency` makes this fire ONCE rather than on every render:
  // without it, a parent who deliberately collapsed the card would have it
  // reopened under them by the next state update. Deliberately never
  // collapses the card either — the parent's own click is the last word in
  // both directions.
  useEffect(() => {
    if (openedForUrgency || !status) return
    const urgency = licenseUrgency(status)
    if (urgency === 'urgent' || urgency === 'expired') {
      setExpanded(true)
      setOpenedForUrgency(true)
    }
  }, [status, openedForUrgency])

  // Dev mode (nothing configured, nothing required) or status unavailable:
  // no card at all — a family that never thinks about licensing shouldn't
  // see a settings section demanding thought.
  if (status === undefined || (status === null)) return null

  // Proportional to the license's own term rather than a flat 30 days, which
  // was lit for the whole of a 30-day trial and so said nothing — see
  // utils/licenseUrgency.ts.
  const urgency = licenseUrgency(status)
  const needsAttention = urgency !== 'none'
  // Name the deadline instead of only its existence: "needs attention" tells
  // a parent to click, and a day count tells them whether to click now.
  const days = status.days_remaining
  const chipLabel =
    urgency === 'expired'
      ? 'expired'
      : days === 1
        ? '1 day left'
        : days !== null && days !== undefined
          ? `${days} days left`
          : 'needs attention'

  const handleApply = async () => {
    setBusy(true)
    setError('')
    setApplied(false)
    try {
      const next = await applyLicenseKey(token, keyInput.trim())
      setStatus(next)
      setKeyInput('')
      setApplied(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not apply that license key')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="bg-white rounded-2xl border border-gray-200 shadow-sm mb-6">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-4"
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-gray-800">
          <ScrollText size={16} className="text-navy-500" /> License
          {needsAttention ? (
            <span
              className={
                urgency === 'expired' || urgency === 'urgent'
                  ? 'flex items-center gap-1 text-xs font-medium text-madder-700 bg-madder-50 border border-madder-200 rounded-full px-2 py-0.5'
                  : 'flex items-center gap-1 text-xs font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2 py-0.5'
              }
            >
              <TriangleAlert size={11} /> {chipLabel}
            </span>
          ) : (
            <span className="flex items-center gap-1 text-xs font-medium text-green-700 bg-green-50 border border-green-200 rounded-full px-2 py-0.5">
              <BadgeCheck size={11} /> active
            </span>
          )}
        </span>
        {expanded ? <ChevronUp size={16} className="text-gray-400" /> : <ChevronDown size={16} className="text-gray-400" />}
      </button>

      {expanded && (
        <div className="px-5 pb-5 space-y-4">
          {status.problem && (
            <p className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">{status.problem}</p>
          )}
          {status.tier && (
            <div className="text-sm text-gray-600 space-y-1">
              <p>
                <span className="font-medium text-gray-800 capitalize">{status.tier}</span> license for{' '}
                <span className="font-medium text-gray-800">{status.licensee}</span> · {status.seats} student
                {status.seats === 1 ? '' : 's'}
              </p>
              <p className="text-xs text-gray-500">
                {status.expires
                  ? status.is_expired
                    ? `Expired ${status.expires}.`
                    : `Renews by ${status.expires} (${status.days_remaining} days left).`
                  : 'Does not expire.'}
              </p>
            </div>
          )}

          <div>
            <p className="text-sm font-medium text-gray-700 mb-1">Apply a new license key</p>
            <p className="text-xs text-gray-500 mb-2">
              Paste the key from your renewal or upgrade email. It takes effect right away.
            </p>
            <div className="flex gap-2">
              <input
                type="text"
                value={keyInput}
                onChange={(e) => { setKeyInput(e.target.value); setApplied(false) }}
                placeholder="eyJ..."
                className="input flex-1 font-mono text-xs"
              />
              <button
                onClick={handleApply}
                disabled={busy || !keyInput.trim()}
                className="px-4 py-2 rounded-lg bg-navy-500 text-white text-sm font-medium hover:bg-navy-600 disabled:opacity-40 flex items-center gap-2"
              >
                {busy && <Loader2 size={14} className="animate-spin" />} Apply
              </button>
            </div>
            {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
            {applied && <p className="text-sm text-green-700 mt-2">License applied — you're all set.</p>}
          </div>
        </div>
      )}
    </div>
  )
}
