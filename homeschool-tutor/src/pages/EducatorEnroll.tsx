import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { educatorPasskeyEnroll } from '../services/api'
import { webauthnSupported, detectPasskeyReadiness, passkeyGuidance, type PasskeyReadiness } from '../services/webauthn'

/** One-time school-mailbox enrollment. Tokens stay in memory, not storage. */
export default function EducatorEnroll() {
  const [invitation, setInvitation] = useState<{ ticket: string; token: string } | null>(null)
  const [state, setState] = useState<'ready' | 'busy' | 'complete'>('ready')
  const [error, setError] = useState('')
  const [passkeyReadiness, setPasskeyReadiness] = useState<PasskeyReadiness | null>(null)

  useEffect(() => {
    const parts = new URLSearchParams(window.location.hash.slice(1))
    const ticket = parts.get('ticket') ?? ''
    const token = parts.get('token') ?? ''
    // Remove capability from the visible URL before loading any further page
    // resources or navigating. Never persist it to localStorage or analytics.
    window.history.replaceState(null, '', window.location.pathname)
    if (ticket.length === 36 && token.length >= 32) setInvitation({ ticket, token })
    else setError('Your school invitation is missing or invalid. Ask the administrator for a new one.')
  }, [])

  useEffect(() => {
    let active = true
    void detectPasskeyReadiness().then(value => { if (active) setPasskeyReadiness(value) })
    return () => { active = false }
  }, [])

  const enroll = async () => {
    if (!invitation || state !== 'ready') return
    setError('')
    setState('busy')
    try {
      if (!webauthnSupported()) throw new Error('This browser does not support passkeys.')
      await educatorPasskeyEnroll(invitation.ticket, invitation.token)
      setInvitation(null)
      setState('complete')
    } catch (reason) {
      // A canceled browser prompt must not lock an account. Starting over
      // requires another fresh challenge but may reuse an unconsumed invite.
      setError(reason instanceof DOMException && reason.name === 'NotAllowedError'
        ? 'The passkey prompt was canceled. You can try again.'
        : reason instanceof Error ? reason.message : 'Passkey enrollment failed.')
      setState('ready')
    }
  }

  return (
    <main className="min-h-screen bg-parchment-50 px-4 py-12">
      <section className="mx-auto max-w-md rounded-2xl border bg-white p-7 space-y-5">
        <h1 className="text-2xl font-display font-semibold text-navy-800">Enroll your Bede educator passkey</h1>
        <p className="text-sm text-gray-700">
          Your school authorized this invitation. Your device will ask you
          to verify with its own biometric or device PIN. Bede will never
          collect or store that PIN.
        </p>
        {passkeyReadiness && <p className="text-sm text-sage-800" role="status">{passkeyGuidance(passkeyReadiness)}</p>}
        {state === 'complete' ? (
          <div role="status" className="space-y-3">
            <p className="text-sage-800 font-semibold">Passkey enrolled successfully.</p>
            <p>Return to sign-in, choose Classical Educator, and verify your passkey.</p>
            <Link to="/" className="text-navy-700 underline">Go to sign-in</Link>
          </div>
        ) : (
          <>
            {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
            <button type="button" onClick={() => void enroll()}
              disabled={!invitation || state === 'busy'}
              className="rounded-lg bg-navy-600 px-5 py-3 text-white disabled:opacity-40">
              {state === 'busy' ? 'Verifying with your device…' : 'Enroll passkey'}
            </button>
            <p className="text-xs text-gray-600">
              If the link expired, or all your passkeys are lost, contact your
              authorized school administrator. Email alone cannot restore access.
            </p>
          </>
        )}
      </section>
    </main>
  )
}
