import { useEffect, useState } from 'react'
import { ShieldAlert, Loader2 } from 'lucide-react'
import { useSessionStore } from '../store/sessionStore'
import { acceptParentAgreement, fetchParentAgreementStatus, type ParentAgreementStatus } from '../services/api'

/**
 * Gates every parent-only page (setup, pod dashboard, progress, sandbox)
 * behind the platform-scope disclaimer/waiver in
 * homeschool-api/core/parent_agreement.py — Bede does not diagnose or
 * screen for ADHD, autism, or any other condition, and is not designed to
 * accommodate special-needs learning approaches.
 *
 * Re-shown automatically whenever the backend's CURRENT_VERSION advances
 * past what this parent already accepted (status.accepted becomes false
 * again) — this component never caches "already saw it" client-side, it
 * asks the server fresh on every mount.
 */
export default function RequireParentAgreement({ children }: { children: React.ReactNode }) {
  const token = useSessionStore((s) => s.token)
  const [status, setStatus] = useState<ParentAgreementStatus | null>(null)
  const [checked, setChecked] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!token) return
    fetchParentAgreementStatus(token)
      .then(setStatus)
      .catch(() => setError('Could not load the parent agreement — please refresh.'))
  }, [token])

  const handleAccept = async () => {
    if (!token || !checked) return
    setSubmitting(true)
    setError('')
    try {
      await acceptParentAgreement(token)
      setStatus((prev) => (prev ? { ...prev, accepted: true } : prev))
    } catch {
      setError('Could not record your acceptance — please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  if (!status) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-parchment-50">
        <Loader2 className="animate-spin text-sage-500" size={28} />
      </div>
    )
  }

  if (status.accepted) return <>{children}</>

  return (
    <div className="min-h-screen bg-parchment-50 flex items-center justify-center p-4">
      <div className="max-w-2xl w-full bg-white rounded-2xl shadow-lg border border-sage-100 p-6 sm:p-8">
        <div className="flex items-center gap-3 mb-4">
          <ShieldAlert className="text-amber-600 flex-shrink-0" size={28} />
          <h1 className="font-display text-xl font-semibold text-navy-800">Before you continue</h1>
        </div>

        <div className="max-h-[50vh] overflow-y-auto pr-2 space-y-5 mb-6 text-sm text-gray-700 leading-relaxed">
          {status.sections.map((section) => (
            <div key={section.heading}>
              <h2 className="font-semibold text-navy-700 mb-1">{section.heading}</h2>
              <p className="whitespace-pre-line">{section.body}</p>
            </div>
          ))}
        </div>

        <label className="flex items-start gap-3 mb-4 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => setChecked(e.target.checked)}
            className="mt-1 h-4 w-4 rounded border-gray-300 text-sage-600 focus:ring-sage-500"
          />
          <span className="text-sm text-gray-700">
            I have read and agree to the above, and accept full responsibility for my child's use of the platform accordingly.
          </span>
        </label>

        {error && <p className="text-sm text-red-600 mb-4">{error}</p>}

        <button
          onClick={handleAccept}
          disabled={!checked || submitting}
          className="w-full py-2.5 rounded-lg bg-sage-600 text-white font-medium hover:bg-sage-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
        >
          {submitting ? <Loader2 className="animate-spin" size={18} /> : null}
          Agree &amp; Continue
        </button>
      </div>
    </div>
  )
}
