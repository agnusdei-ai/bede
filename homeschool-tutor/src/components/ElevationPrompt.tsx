import { useCallback, useEffect, useRef, useState } from 'react'
import { Lock, Loader2, X } from 'lucide-react'
import { elevateSession, fetchMfaStatus } from '../services/api'
import { useSessionStore } from '../store/sessionStore'

/**
 * Frontend half of P8 (core/elevation.py, docs/ARCHITECTURE_PRINCIPLES.md).
 *
 * The backend has required a recent, explicit re-authentication for
 * management-plane actions — the audit log, licensing, the AI provider
 * switch, any auth/recovery factor change, permanent student deletion —
 * since 2026-08-03, gated behind `settings.elevation_enforced` specifically
 * BECAUSE nothing here existed yet: flipping that flag with no frontend
 * flow would have handed every parent an unexplained 403 the first time
 * they opened the audit log or deleted a student.
 *
 * Mounted once, at the app root, next to GlobalAuthInterceptor — same
 * technique, same reason: wrapping window.fetch here means every one of the
 * ~15 raw fetch()/postJson() call sites that reach an elevation-gated
 * endpoint gets this behavior automatically, with no call site needing to
 * know elevation exists. A call site added later inherits it for free; one
 * instrumented by hand could always be forgotten.
 *
 * FLOW. A wrapped call returns 403 with `{elevation_required: true}`
 * (core/deps.py's require_elevated_parent) → this component shows a
 * password (+ TOTP, if enrolled) modal → on success it calls
 * POST /auth/elevate itself → the ORIGINAL request is retried exactly once,
 * through the same underlying fetch chain, and ITS response (not the 403)
 * is what the calling code actually sees. A cancelled or failed elevation
 * returns the original 403 unchanged, so existing error handling at each
 * call site — built when this endpoint could only ever fail for real
 * reasons — still applies as the fallback.
 *
 * COALESCING. Two elevation-gated calls firing close together (e.g. a
 * settings page loading the audit log and the AI-provider status at once)
 * must not open two modals or orphan the first request's promise while the
 * second overwrites it — requestElevation() shares one in-flight promise
 * across concurrent callers instead.
 */
export default function ElevationPrompt() {
  const token = useSessionStore((s) => s.token)
  const role = useSessionStore((s) => s.role)
  const tokenRef = useRef(token)
  tokenRef.current = token

  const [pending, setPending] = useState<{ resolve: (granted: boolean) => void } | null>(null)
  const [password, setPassword] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [totpEnrolled, setTotpEnrolled] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const pendingPromiseRef = useRef<Promise<boolean> | null>(null)

  const requestElevation = useCallback((): Promise<boolean> => {
    if (pendingPromiseRef.current) return pendingPromiseRef.current
    const p = new Promise<boolean>((resolve) => {
      setError('')
      setPassword('')
      setTotpCode('')
      setPending({ resolve })
    })
    pendingPromiseRef.current = p
    p.finally(() => {
      pendingPromiseRef.current = null
    })
    return p
  }, [])

  // Only the parent role can ever reach an elevation-gated endpoint — a
  // child session never calls one, so there is nothing to intercept and no
  // reason to hold a fetch wrapper open on a child's tablet.
  useEffect(() => {
    if (role !== 'parent') return
    const originalFetch = window.fetch.bind(window)

    window.fetch = async (...args) => {
      const response = await originalFetch(...args)
      if (response.status !== 403) return response

      // Peek at the body on a CLONE — the caller must still be able to read
      // the original response if this turns out not to be an elevation
      // prompt (or if the parent cancels it).
      let elevationRequired = false
      try {
        const data = await response.clone().json()
        elevationRequired = data?.detail?.elevation_required === true
      } catch {
        // Not JSON, or an ordinary 403 with a plain string detail — not
        // ours to handle.
      }
      if (!elevationRequired) return response

      const granted = await requestElevation()
      if (!granted) return response

      // Retry exactly once. If the retried request ALSO comes back needing
      // elevation (e.g. the grant's TTL is absurdly short, or a race with
      // password-change bumped credentials_version in between), this
      // deliberately does not loop — it returns that second 403 as-is,
      // rather than re-prompting silently forever.
      return originalFetch(...args)
    }

    return () => {
      window.fetch = originalFetch
    }
  }, [role, requestElevation])

  // Fetch once per prompt, not once per render — the field only needs to
  // know whether TOTP applies at all, not track it live.
  useEffect(() => {
    if (!pending || !tokenRef.current) return
    let cancelled = false
    fetchMfaStatus(tokenRef.current)
      .then((status) => {
        if (!cancelled) setTotpEnrolled(status.totp_enabled)
      })
      .catch(() => {
        // Best-effort — worst case the TOTP field just doesn't show, and a
        // TOTP-enrolled parent gets the server's own "enter your code"
        // error on submit instead, which still resolves correctly.
      })
    return () => {
      cancelled = true
    }
  }, [pending])

  if (!pending) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const currentToken = tokenRef.current
    if (!currentToken) return
    setSubmitting(true)
    setError('')
    try {
      await elevateSession(currentToken, password, totpEnrolled ? totpCode : undefined)
      const resolve = pending.resolve
      setPending(null)
      resolve(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not confirm your password')
    } finally {
      setSubmitting(false)
    }
  }

  const handleCancel = () => {
    const resolve = pending.resolve
    setPending(null)
    resolve(false)
  }

  return (
    <div className="fixed inset-0 z-[60] bg-black/40 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-sm p-6 relative">
        <button onClick={handleCancel} className="absolute top-3 right-3 text-gray-400 hover:text-gray-600" aria-label="Close">
          <X size={18} />
        </button>

        <div className="flex items-center gap-1.5 mb-2">
          <Lock size={16} className="text-navy-500" />
          <h2 className="text-sm font-display font-bold text-gray-800">Confirm your password</h2>
        </div>
        <p className="text-xs text-gray-500 mb-4">
          This action needs to be re-authorised — enter your password to continue.
        </p>

        <form onSubmit={handleSubmit}>
          <label htmlFor="elevation-password" className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">
            Password
          </label>
          <input
            id="elevation-password"
            type="password"
            required
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 mb-3 focus:outline-none focus:ring-2 focus:ring-navy-400"
          />

          {totpEnrolled && (
            <>
              <label htmlFor="elevation-totp" className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">
                Authenticator code
              </label>
              <input
                id="elevation-totp"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                required
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value)}
                placeholder="6-digit code"
                className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 mb-3 focus:outline-none focus:ring-2 focus:ring-navy-400"
              />
            </>
          )}

          {error && <p className="text-xs text-red-600 mb-3">{error}</p>}

          <button
            type="submit"
            disabled={submitting || !password}
            className="w-full py-2.5 bg-navy-500 text-white rounded-xl font-semibold text-sm hover:bg-navy-600 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {submitting ? <Loader2 size={16} className="animate-spin" /> : 'Confirm'}
          </button>
        </form>
      </div>
    </div>
  )
}
