import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, ChevronUp, KeyRound, Loader2, Lock, ShieldCheck, Smartphone, Trash2 } from 'lucide-react'
import {
  fetchMfaStatus, webauthnRegisterOptions, webauthnRegisterVerify, deleteSecurityKey,
  enrollTotp, confirmTotp, disableTotp, changePassword,
  enrollRecoveryPin, disableRecoveryPin, enrollRecoveryCode, disableRecoveryCode,
  type MfaStatus,
} from '../services/api'
import { registerSecurityKey, webauthnSupported } from '../services/webauthn'
import { useSessionStore } from '../store/sessionStore'

// Not currently localized (plain English strings) — same disclosed,
// deliberate gap as FeedbackModal.tsx.

interface Props {
  token: string
}

export default function ParentSecuritySettings({ token }: Props) {
  const navigate = useNavigate()
  const logout = useSessionStore((s) => s.logout)
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

  // Change password
  const [changingPassword, setChangingPassword] = useState(false)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')

  // Recovery secret — PIN (favored, memorable) or code (alternative,
  // longer/machine-generated); mutually exclusive, see services/
  // parent_recovery.py.
  const [recoverySetup, setRecoverySetup] = useState<'closed' | 'pin' | 'code'>('closed')
  const [pinInput, setPinInput] = useState('')
  const [pinConfirmInput, setPinConfirmInput] = useState('')
  const [pinJustSet, setPinJustSet] = useState(false)
  const [pinWrittenDown, setPinWrittenDown] = useState(false)
  const [newRecoveryCode, setNewRecoveryCode] = useState<string | null>(null)
  const [codeSavedConfirmed, setCodeSavedConfirmed] = useState(false)

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

  // Changing the password bumps credentials_version (core/parent_credential.py)
  // — that invalidates every outstanding parent token, INCLUDING the one this
  // very request used, the instant it commits. There's no next click to wait
  // for: log out and send the parent back to login with their new password
  // immediately, rather than letting them hit a confusing 401 on whatever
  // they tap next.
  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('New passwords do not match')
      return
    }
    setBusy(true)
    try {
      await changePassword(token, currentPassword, newPassword)
      logout()
      navigate('/', { replace: true })
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not change password')
      setBusy(false)
    }
  }

  const handleEnrollRecoveryPin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (pinInput !== pinConfirmInput) {
      setError('PINs do not match')
      return
    }
    setBusy(true)
    try {
      await enrollRecoveryPin(token, pinInput)
      setPinJustSet(true)
      setPinInput('')
      setPinConfirmInput('')
      await load()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not set a recovery PIN')
    } finally {
      setBusy(false)
    }
  }

  const handleDisableRecoveryPin = async () => {
    setBusy(true)
    try {
      await disableRecoveryPin(token)
      await load()
    } catch {
      setError('Could not remove the recovery PIN')
    } finally {
      setBusy(false)
    }
  }

  const handleEnrollRecoveryCode = async () => {
    setError('')
    setBusy(true)
    try {
      const result = await enrollRecoveryCode(token)
      setNewRecoveryCode(result.recovery_code)
      setCodeSavedConfirmed(false)
      await load()
    } catch {
      setError('Could not generate a recovery code')
    } finally {
      setBusy(false)
    }
  }

  const handleDisableRecoveryCode = async () => {
    setBusy(true)
    try {
      await disableRecoveryCode(token)
      await load()
    } catch {
      setError('Could not remove the recovery code')
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

          {/* Account recovery — the "something you know" leg (Login.tsx's
              "Forgot password?" flow needs >=2 of: this, TOTP, a security
              key). A PIN (favored/memorable) or a recovery code (longer,
              machine-generated) — mutually exclusive, parent's choice. */}
          <div>
            <h3 className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2 flex items-center gap-1.5">
              <KeyRound size={13} /> Account recovery
            </h3>
            <p className="text-xs text-gray-500 mb-2">
              Lets you regain access if you forget your password and lose a second factor. Enroll this
              plus at least one of the two above — recovery needs any two.
            </p>

            {/* PIN just set — gentle reminder before dismissing */}
            {pinJustSet ? (
              <div className="space-y-2">
                <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                  Write this PIN down somewhere safe too — it's meant to be memorable, but a written
                  backup means you're never locked out just because you forgot it. Where and how you
                  store that backup is up to you; an encrypted password manager is recommended over a
                  plain note.
                </p>
                <label className="flex items-start gap-2 text-xs text-gray-600">
                  <input
                    type="checkbox"
                    checked={pinWrittenDown}
                    onChange={(e) => setPinWrittenDown(e.target.checked)}
                    className="mt-0.5"
                  />
                  I've written this PIN down somewhere safe
                </label>
                <button
                  onClick={() => { setPinJustSet(false); setPinWrittenDown(false); setRecoverySetup('closed') }}
                  disabled={!pinWrittenDown}
                  className="text-xs text-navy-600 hover:text-navy-800 underline disabled:opacity-40 disabled:no-underline"
                >
                  Done
                </button>
              </div>

            /* Recovery code just generated — shown once */
            ) : newRecoveryCode ? (
              <div className="space-y-2">
                <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                  Save this now — it won't be shown again.
                </p>
                <code className="block text-sm bg-navy-50 rounded-lg px-3 py-2 break-all select-all tracking-wide">{newRecoveryCode}</code>
                <label className="flex items-start gap-2 text-xs text-gray-600">
                  <input
                    type="checkbox"
                    checked={codeSavedConfirmed}
                    onChange={(e) => setCodeSavedConfirmed(e.target.checked)}
                    className="mt-0.5"
                  />
                  I've saved this code somewhere safe
                </label>
                <button
                  onClick={() => { setNewRecoveryCode(null); setCodeSavedConfirmed(false); setRecoverySetup('closed') }}
                  disabled={!codeSavedConfirmed}
                  className="text-xs text-navy-600 hover:text-navy-800 underline disabled:opacity-40 disabled:no-underline"
                >
                  Done
                </button>
              </div>

            /* Choosing/entering a new PIN */
            ) : recoverySetup === 'pin' ? (
              <form onSubmit={handleEnrollRecoveryPin} className="space-y-2">
                <input
                  type="text"
                  inputMode="numeric"
                  value={pinInput}
                  onChange={(e) => setPinInput(e.target.value.replace(/\D/g, '').slice(0, 12))}
                  placeholder="Choose a PIN (6-12 digits)"
                  autoFocus
                  className="w-full text-center tracking-widest text-sm border border-navy-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-navy-400"
                />
                <input
                  type="text"
                  inputMode="numeric"
                  value={pinConfirmInput}
                  onChange={(e) => setPinConfirmInput(e.target.value.replace(/\D/g, '').slice(0, 12))}
                  placeholder="Confirm PIN"
                  className="w-full text-center tracking-widest text-sm border border-navy-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-navy-400"
                />
                <p className="text-xs text-gray-400">
                  6 digits by default; use more (up to 12) for extra security. Choose something you'll
                  actually remember — not a sequential run (123456) or repeated pattern (111111).
                </p>
                <div className="flex gap-2">
                  <button
                    type="submit"
                    disabled={busy || pinInput.length < 6 || !pinConfirmInput}
                    className="flex-1 py-2 bg-navy-500 text-white rounded-lg text-sm font-medium hover:bg-navy-600 disabled:opacity-40 flex items-center justify-center gap-2"
                  >
                    {busy ? <Loader2 size={14} className="animate-spin" /> : null} Set PIN
                  </button>
                  <button type="button" onClick={() => setRecoverySetup('closed')} className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-400 rounded">
                    Cancel
                  </button>
                </div>
              </form>

            /* Already enrolled — PIN */
            ) : status?.recovery_secret === 'pin' ? (
              <div className="flex items-center justify-between text-sm bg-navy-50 rounded-lg px-3 py-2">
                <span className="text-gray-700">Recovery PIN enabled</span>
                <div className="flex items-center gap-3">
                  <button onClick={() => setRecoverySetup('pin')} disabled={busy} className="text-xs text-navy-600 hover:text-navy-800 underline">Change</button>
                  <button onClick={handleDisableRecoveryPin} disabled={busy} className="text-xs text-gray-500 hover:text-red-600 underline transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400 rounded">Remove</button>
                </div>
              </div>

            /* Already enrolled — recovery code */
            ) : status?.recovery_secret === 'code' ? (
              <div className="flex items-center justify-between text-sm bg-navy-50 rounded-lg px-3 py-2">
                <span className="text-gray-700">Recovery code enabled</span>
                <div className="flex items-center gap-3">
                  <button onClick={handleEnrollRecoveryCode} disabled={busy} className="text-xs text-navy-600 hover:text-navy-800 underline">Regenerate</button>
                  <button onClick={handleDisableRecoveryCode} disabled={busy} className="text-xs text-gray-500 hover:text-red-600 underline transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400 rounded">Remove</button>
                </div>
              </div>

            /* Nothing enrolled — PIN favored, code as the alternative */
            ) : (
              <div className="space-y-1.5">
                <button onClick={() => setRecoverySetup('pin')} disabled={busy} className="text-xs text-navy-600 hover:text-navy-800 underline block">
                  + Set a recovery PIN
                </button>
                <button onClick={handleEnrollRecoveryCode} disabled={busy} className="text-xs text-gray-400 hover:text-gray-600 underline block">
                  or generate a recovery code instead
                </button>
              </div>
            )}
          </div>

          {/* Change password */}
          <div>
            <h3 className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2 flex items-center gap-1.5">
              <Lock size={13} /> Password
            </h3>
            {changingPassword ? (
              <form onSubmit={handleChangePassword} className="space-y-2">
                <input
                  type="password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  placeholder="Current password"
                  className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-navy-400"
                />
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="New password (8+ characters)"
                  className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-navy-400"
                />
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Confirm new password"
                  className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-navy-400"
                />
                <p className="text-xs text-gray-400">
                  You'll be signed out of every device after this — log back in with the new password.
                </p>
                <div className="flex gap-2">
                  <button
                    type="submit"
                    disabled={busy || !currentPassword || !newPassword || !confirmPassword}
                    className="flex-1 py-2 bg-navy-500 text-white rounded-lg text-sm font-medium hover:bg-navy-600 disabled:opacity-40 flex items-center justify-center gap-2"
                  >
                    {busy ? <Loader2 size={14} className="animate-spin" /> : null} Change password
                  </button>
                  <button
                    type="button"
                    onClick={() => { setChangingPassword(false); setCurrentPassword(''); setNewPassword(''); setConfirmPassword('') }}
                    className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-400 rounded"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <button onClick={() => setChangingPassword(true)} className="text-xs text-navy-600 hover:text-navy-800 underline">
                Change password
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
