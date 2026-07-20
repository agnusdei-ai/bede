import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, KeyRound, Loader2, ShieldCheck, Smartphone, Trash2 } from 'lucide-react'
import {
  fetchMfaStatus, webauthnRegisterOptions, webauthnRegisterVerify, deleteSecurityKey,
  enrollTotp, confirmTotp, disableTotp, type MfaStatus,
} from '../services/api'
import { registerSecurityKey, webauthnSupported } from '../services/webauthn'

interface Props {
  token: string
}

export default function ParentSecuritySettings({ token }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [status, setStatus] = useState<MfaStatus | null>(null)
  const [error, setError] = useState('')

  // Add-key flow
  const [addingKey, setAddingKey] = useState(false)
  const [nickname, setNickname] = useState('')

  // TOTP enroll flow
  const [totpEnrolling, setTotpEnrolling] = useState(false)
  const [totpSecret, setTotpSecret] = useState<{ secret: string; otpauth_uri: string } | null>(null)
  const [totpCode, setTotpCode] = useState('')
  const [busy, setBusy] = useState(false)

  const load = () => fetchMfaStatus(token).then(setStatus).catch(() => setError('Could not load security settings'))

  useEffect(() => {
    if (expanded && !status) load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expanded])

  const handleAddKey = async () => {
    setError('')
    setBusy(true)
    try {
      const options = await webauthnRegisterOptions(token)
      const credential = await registerSecurityKey(options)
      await webauthnRegisterVerify(token, credential, nickname)
      setAddingKey(false)
      setNickname('')
      await load()
    } catch (err: unknown) {
      setError(err instanceof Error && err.name === 'NotAllowedError'
        ? 'Cancelled, or the key was already registered.'
        : err instanceof Error ? err.message : 'Could not add that security key')
    } finally {
      setBusy(false)
    }
  }

  const handleRemoveKey = async (id: number) => {
    setBusy(true)
    try {
      await deleteSecurityKey(token, id)
      await load()
    } catch {
      setError('Could not remove that key')
    } finally {
      setBusy(false)
    }
  }

  const handleStartTotp = async () => {
    setError('')
    setBusy(true)
    try {
      setTotpSecret(await enrollTotp(token))
      setTotpEnrolling(true)
    } catch {
      setError('Could not start authenticator app setup')
    } finally {
      setBusy(false)
    }
  }

  const handleConfirmTotp = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      await confirmTotp(token, totpCode)
      setTotpEnrolling(false)
      setTotpSecret(null)
      setTotpCode('')
      await load()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Incorrect code')
    } finally {
      setBusy(false)
    }
  }

  const handleDisableTotp = async () => {
    setBusy(true)
    try {
      await disableTotp(token)
      await load()
    } catch {
      setError('Could not disable the authenticator app')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-xl border border-navy-100 bg-white mb-6 overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-gray-700 hover:bg-navy-50"
      >
        <span className="flex items-center gap-2"><ShieldCheck size={16} className="text-navy-500" /> Security keys & authenticator app</span>
        {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t border-navy-100 pt-4 space-y-5">
          <p className="text-xs text-gray-500">
            Optional extra step at parent login, on top of your password — a hardware
            security key (like a YubiKey) or a TOTP authenticator app code.
          </p>
          {error && <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>}

          {/* Security keys */}
          <div>
            <h3 className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2 flex items-center gap-1.5">
              <KeyRound size={13} /> Security keys
            </h3>
            {!status?.webauthn_available ? (
              <p className="text-xs text-gray-400">
                Not configured on this deployment — set WEBAUTHN_RP_ID and WEBAUTHN_ORIGIN to enable.
              </p>
            ) : (
              <>
                {status.security_keys.length > 0 && (
                  <ul className="space-y-1.5 mb-3">
                    {status.security_keys.map((k) => (
                      <li key={k.id} className="flex items-center justify-between text-sm bg-navy-50 rounded-lg px-3 py-2">
                        <span className="text-gray-700">{k.nickname}</span>
                        <button onClick={() => handleRemoveKey(k.id)} disabled={busy} title="Remove this security key" className="text-gray-500 hover:text-red-600 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400 rounded">
                          <Trash2 size={14} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {addingKey ? (
                  <div className="space-y-2">
                    <input
                      value={nickname}
                      onChange={(e) => setNickname(e.target.value)}
                      placeholder="Nickname (e.g. YubiKey 5C)"
                      className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-navy-400"
                    />
                    <div className="flex gap-2">
                      <button
                        onClick={handleAddKey}
                        disabled={busy || !webauthnSupported()}
                        className="flex-1 py-2 bg-navy-500 text-white rounded-lg text-sm font-medium hover:bg-navy-600 disabled:opacity-40 flex items-center justify-center gap-2"
                      >
                        {busy ? <Loader2 size={14} className="animate-spin" /> : null} Tap key now
                      </button>
                      <button onClick={() => setAddingKey(false)} className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-400 rounded">Cancel</button>
                    </div>
                  </div>
                ) : (
                  <button onClick={() => setAddingKey(true)} className="text-xs text-navy-600 hover:text-navy-800 underline">
                    + Add a security key
                  </button>
                )}
              </>
            )}
          </div>

          {/* TOTP */}
          <div>
            <h3 className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2 flex items-center gap-1.5">
              <Smartphone size={13} /> Authenticator app (TOTP)
            </h3>
            {status?.totp_enabled ? (
              <div className="flex items-center justify-between text-sm bg-navy-50 rounded-lg px-3 py-2">
                <span className="text-gray-700">Enabled</span>
                <button onClick={handleDisableTotp} disabled={busy} className="text-xs text-gray-500 hover:text-red-600 underline transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400 rounded">Disable</button>
              </div>
            ) : totpEnrolling && totpSecret ? (
              <form onSubmit={handleConfirmTotp} className="space-y-2">
                <p className="text-xs text-gray-500">
                  Add this key to your authenticator app (Google Authenticator, Authy, etc.), then enter the 6-digit code it shows:
                </p>
                <code className="block text-xs bg-navy-50 rounded-lg px-3 py-2 break-all select-all">{totpSecret.secret}</code>
                <input
                  type="text"
                  inputMode="numeric"
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 8))}
                  placeholder="6-digit code"
                  autoFocus
                  className="w-full text-center tracking-widest text-sm border border-navy-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-navy-400"
                />
                <div className="flex gap-2">
                  <button
                    type="submit"
                    disabled={busy || !totpCode}
                    className="flex-1 py-2 bg-navy-500 text-white rounded-lg text-sm font-medium hover:bg-navy-600 disabled:opacity-40"
                  >
                    Confirm
                  </button>
                  <button type="button" onClick={() => { setTotpEnrolling(false); setTotpSecret(null) }} className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-400 rounded">
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <button onClick={handleStartTotp} disabled={busy} className="text-xs text-navy-600 hover:text-navy-800 underline">
                + Enable authenticator app
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
