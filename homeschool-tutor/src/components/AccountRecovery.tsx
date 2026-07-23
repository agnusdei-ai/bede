import { useEffect, useState } from 'react'
import { KeyRound, Loader2, ShieldAlert, ShieldCheck } from 'lucide-react'
import {
  fetchRecoveryMethods, recoveryWebauthnOptions, verifyRecovery, resetPasswordRecovery,
  type RecoveryMethods, type RecoveryVerifyPayload,
} from '../services/api'
import { authenticateSecurityKey, webauthnSupported } from '../services/webauthn'

// Not currently localized (plain English strings) — same disclosed,
// deliberate gap as FeedbackModal.tsx, not an oversight. This is a rare,
// emergency-only flow (a parent who's lost both their password and a
// second factor); worth a native-speaker pass alongside FeedbackModal's,
// not blocking this feature's release.

interface Props {
  onDone: () => void
}

type Stage = 'loading' | 'unavailable' | 'collect' | 'reset' | 'success'

// >=2 of these must verify — mirrors routers/recovery.py's own
// _REQUIRED_FACTORS. Not user-configurable; kept here only so the UI can
// show "N of 2 collected" without hardcoding the number twice.
const REQUIRED_FACTORS = 2

export default function AccountRecovery({ onDone }: Props) {
  const [stage, setStage] = useState<Stage>('loading')
  const [methods, setMethods] = useState<RecoveryMethods | null>(null)
  const [recoverySecret, setRecoverySecret] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [webauthnCredential, setWebauthnCredential] = useState<object | null>(null)
  const [recoveryToken, setRecoveryToken] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fetchRecoveryMethods()
      .then((m) => setMethods(m))
      .then(() => setStage((s) => (s === 'loading' ? 'collect' : s)))
      .catch(() => setStage('unavailable'))
  }, [])

  useEffect(() => {
    if (methods && !methods.recovery_possible) setStage('unavailable')
  }, [methods])

  const collectedCount =
    (recoverySecret ? 1 : 0) + (totpCode ? 1 : 0) + (webauthnCredential ? 1 : 0)

  const handleWebauthn = async () => {
    setError('')
    setBusy(true)
    try {
      const options = await recoveryWebauthnOptions()
      const credential = await authenticateSecurityKey(options)
      setWebauthnCredential(credential)
    } catch (err: unknown) {
      setError(err instanceof Error && err.name === 'NotAllowedError'
        ? 'Cancelled, or no matching security key was presented.'
        : err instanceof Error ? err.message : 'Security key verification failed')
    } finally {
      setBusy(false)
    }
  }

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault()
    if (collectedCount < REQUIRED_FACTORS) return
    setError('')
    setBusy(true)
    try {
      const payload: RecoveryVerifyPayload = {}
      if (recoverySecret) payload.recovery_secret = recoverySecret
      if (totpCode) payload.totp_code = totpCode
      if (webauthnCredential) payload.webauthn_credential = webauthnCredential
      const result = await verifyRecovery(payload)
      setRecoveryToken(result.recovery_token)
      setStage('reset')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not verify those recovery factors')
    } finally {
      setBusy(false)
    }
  }

  const handleReset = async (e: React.FormEvent) => {
    e.preventDefault()
    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('Passwords do not match')
      return
    }
    setError('')
    setBusy(true)
    try {
      await resetPasswordRecovery(recoveryToken, newPassword)
      setStage('success')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not reset the password')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-parchment-100 via-navy-50 to-gold-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-sm p-8">
        <div className="text-center mb-6">
          <div className="w-14 h-14 rounded-full bg-navy-50 border-2 border-navy-200 flex items-center justify-center mx-auto mb-3">
            {stage === 'success'
              ? <ShieldCheck size={26} className="text-green-600" />
              : stage === 'unavailable'
                ? <ShieldAlert size={26} className="text-amber-600" />
                : <KeyRound size={26} className="text-navy-500" />}
          </div>
          <h1 className="text-xl font-display font-bold text-gray-800">Account recovery</h1>
        </div>

        {stage === 'loading' && (
          <p className="text-sm text-gray-500 text-center">Checking what's available…</p>
        )}

        {stage === 'unavailable' && (
          <div className="space-y-3">
            <p className="text-sm text-gray-600">
              Recovery isn't set up on this instance yet — it needs at least two of a recovery code,
              authenticator app, or security key enrolled ahead of time (Settings → Security). Without
              that, regaining access requires direct access to the server itself.
            </p>
            <button
              onClick={onDone}
              className="w-full py-2.5 border border-navy-300 text-navy-700 rounded-lg font-medium hover:bg-navy-50 transition-colors"
            >
              Back to login
            </button>
          </div>
        )}

        {stage === 'collect' && methods && (
          <form onSubmit={handleVerify} className="space-y-4">
            <p className="text-sm text-gray-500 text-center">
              Prove {REQUIRED_FACTORS} of the methods below ({collectedCount}/{REQUIRED_FACTORS} collected)
            </p>

            {methods.recovery_secret === 'pin' && (
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Recovery PIN</label>
                <input
                  inputMode="numeric"
                  value={recoverySecret}
                  onChange={(e) => setRecoverySecret(e.target.value.replace(/\D/g, '').slice(0, 12))}
                  placeholder="Your recovery PIN"
                  className="w-full text-center tracking-widest text-sm border border-navy-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-navy-400"
                />
              </div>
            )}

            {methods.recovery_secret === 'code' && (
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Recovery code</label>
                <input
                  value={recoverySecret}
                  onChange={(e) => setRecoverySecret(e.target.value.toUpperCase())}
                  placeholder="XXXXX-XXXXX-XXXXX-XXXXX"
                  className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 tracking-wide focus:outline-none focus:ring-2 focus:ring-navy-400"
                />
              </div>
            )}

            {methods.totp && (
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Authenticator app code</label>
                <input
                  type="text"
                  inputMode="numeric"
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
                  placeholder="6-digit code"
                  className="w-full text-center tracking-widest text-sm border border-navy-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-navy-400"
                />
              </div>
            )}

            {methods.webauthn && (
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Security key</label>
                <button
                  type="button"
                  onClick={handleWebauthn}
                  disabled={busy || !webauthnSupported() || !!webauthnCredential}
                  className="w-full py-2 border border-navy-300 text-navy-700 rounded-lg text-sm font-medium hover:bg-navy-50 disabled:opacity-40 transition-colors flex items-center justify-center gap-2"
                >
                  {webauthnCredential ? 'Security key verified ✓' : 'Tap security key'}
                </button>
              </div>
            )}

            {error && (
              <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</div>
            )}

            <button
              type="submit"
              disabled={busy || collectedCount < REQUIRED_FACTORS}
              className="w-full py-3 bg-navy-500 text-white rounded-lg font-medium hover:bg-navy-600 disabled:opacity-40 transition-colors flex items-center justify-center gap-2"
            >
              {busy ? <Loader2 size={16} className="animate-spin" /> : null} Continue
            </button>
            <button type="button" onClick={onDone} className="w-full text-center text-xs text-gray-500 hover:text-gray-700">
              Back to login
            </button>
          </form>
        )}

        {stage === 'reset' && (
          <form onSubmit={handleReset} className="space-y-4">
            <p className="text-sm text-gray-500 text-center">Set a new password</p>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="New password (8+ characters)"
              autoFocus
              className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-navy-400"
            />
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Confirm new password"
              className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-navy-400"
            />
            {error && (
              <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</div>
            )}
            <button
              type="submit"
              disabled={busy || !newPassword || !confirmPassword}
              className="w-full py-3 bg-navy-500 text-white rounded-lg font-medium hover:bg-navy-600 disabled:opacity-40 transition-colors flex items-center justify-center gap-2"
            >
              {busy ? <Loader2 size={16} className="animate-spin" /> : null} Set new password
            </button>
          </form>
        )}

        {stage === 'success' && (
          <div className="space-y-4">
            <p className="text-sm text-gray-600 text-center">
              Your password has been changed. Every other device that was signed in as parent has been
              signed out — log in again with your new password.
            </p>
            <button
              onClick={onDone}
              className="w-full py-3 bg-navy-500 text-white rounded-lg font-medium hover:bg-navy-600 transition-colors"
            >
              Back to login
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
