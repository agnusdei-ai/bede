import { useState } from 'react'
import { KeyRound, Loader2, ShieldCheck } from 'lucide-react'
import { webauthnAuthOptions, webauthnAuthVerify, totpAuthVerify, type LoginResult, type MfaMethod } from '../services/api'
import { authenticateSecurityKey, webauthnSupported } from '../services/webauthn'

interface Props {
  pendingToken: string
  methods: MfaMethod[]
  onVerified: (result: LoginResult) => void
}

export default function ParentMfaVerification({ pendingToken, methods, onVerified }: Props) {
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const handleSecurityKey = async () => {
    setError('')
    setBusy(true)
    try {
      const options = await webauthnAuthOptions(pendingToken)
      const credential = await authenticateSecurityKey(options)
      const result = await webauthnAuthVerify(pendingToken, credential)
      onVerified(result)
    } catch (err: unknown) {
      setError(err instanceof Error && err.name === 'NotAllowedError'
        ? 'Cancelled or no matching security key was presented.'
        : err instanceof Error ? err.message : 'Security key verification failed')
    } finally {
      setBusy(false)
    }
  }

  const handleTotp = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!code) return
    setError('')
    setBusy(true)
    try {
      const result = await totpAuthVerify(pendingToken, code)
      onVerified(result)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Incorrect code')
      setCode('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-parchment-100 via-navy-50 to-gold-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-sm p-8">
        <div className="text-center mb-6">
          <div className="w-14 h-14 rounded-full bg-navy-50 border-2 border-navy-200 flex items-center justify-center mx-auto mb-3">
            <ShieldCheck size={26} className="text-navy-500" />
          </div>
          <h1 className="text-xl font-display font-bold text-gray-800">One more step</h1>
          <p className="text-sm text-gray-500 mt-1">Verify with your enrolled security key or authenticator app</p>
        </div>

        {methods.includes('webauthn') && (
          <button
            onClick={handleSecurityKey}
            disabled={busy || !webauthnSupported()}
            className="w-full py-3 bg-navy-500 text-white rounded-lg font-medium hover:bg-navy-600 disabled:opacity-40 transition-colors flex items-center justify-center gap-2 mb-4"
          >
            {busy ? <Loader2 size={16} className="animate-spin" /> : <KeyRound size={16} />}
            Use security key
          </button>
        )}
        {methods.includes('webauthn') && !webauthnSupported() && (
          <p className="text-xs text-red-500 text-center -mt-2 mb-4">This browser doesn't support security keys.</p>
        )}

        {methods.includes('totp') && (
          <>
            {methods.includes('webauthn') && (
              <div className="flex items-center gap-3 mb-4">
                <div className="flex-1 h-px bg-navy-100" />
                <span className="text-xs text-gray-400">or</span>
                <div className="flex-1 h-px bg-navy-100" />
              </div>
            )}
            <form onSubmit={handleTotp} className="space-y-3">
              <input
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
                placeholder="6-digit authenticator code"
                autoFocus={!methods.includes('webauthn')}
                className="w-full text-center tracking-widest text-lg py-2.5 border border-navy-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-navy-400"
              />
              <button
                type="submit"
                disabled={busy || !code}
                className="w-full py-2.5 border border-navy-300 text-navy-700 rounded-lg font-medium hover:bg-navy-50 disabled:opacity-40 transition-colors"
              >
                {busy ? 'Checking…' : 'Verify code'}
              </button>
            </form>
          </>
        )}

        {error && (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2 mt-4">
            {error}
          </div>
        )}
      </div>
    </div>
  )
}
