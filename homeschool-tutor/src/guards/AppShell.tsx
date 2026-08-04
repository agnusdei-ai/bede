import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import i18n from '../i18n'
import { useSessionStore } from '../store/sessionStore'
import {
  IDLE_CHECK_INTERVAL_MS, idleStatus, isSessionBusy,
} from '../utils/idleTimeout'
import { setLogoutNotice, type LogoutReason } from '../utils/logoutNotice'
import TextSizeControl from '../components/TextSizeControl'
import { AgnusDeiMark, BedeWordmark } from '../components/BedeMark'

const VALIDATE_INTERVAL_MS = 5 * 60 * 1000   // re-validate token every 5 min
// The 30-minute window and what counts as activity both live in
// utils/idleTimeout.ts now — see that file for why input events alone were
// the wrong measure, and why the window itself is deliberately unchanged.

/**
 * AppShell — zero-trust SSO gate for the entire application.
 *
 * Rules:
 *  1. Nothing renders until a valid JWT is confirmed server-side.
 *  2. Token is validated immediately on mount and every 5 minutes.
 *  3. 30 minutes of inactivity triggers immediate logout and wipe.
 *  4. Any 401 from the API clears state and forces re-authentication.
 *  5. Token lives in React state (Zustand) only — never localStorage or cookies.
 *  6. On logout, all session state is cleared from memory.
 *
 * Unprotected paths (/): renders the login page which is the ONLY entry point.
 */
export default function AppShell({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate()
  const { token, locale, logout, isStreaming, voiceActive } = useSessionStore()
  const [ready, setReady] = useState(false)
  const [idleWarning, setIdleWarning] = useState(false)
  // Read through a ref so the monitor below sees the CURRENT value without
  // taking these as effect dependencies — they change constantly during a
  // turn, and re-running the effect would reset the idle clock every time,
  // which would silently disable the logout altogether.
  const busyRef = useRef(false)
  busyRef.current = isSessionBusy({ isStreaming, voiceActive })
  const lastActivityRef = useRef(Date.now())
  const validateTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const inactivityTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // A page refresh mid-session loses Login.tsx's live i18n.changeLanguage()
  // call (that only ran once, in memory) — the persisted store still knows
  // which language was picked at login, so restore it here rather than
  // silently falling back to VITE_LOCALE's build-time default.
  useEffect(() => {
    if (locale && i18n.language !== locale) i18n.changeLanguage(locale)
  }, [locale])

  // `notice` is what the person will actually read on the login screen;
  // `detail` is only for the console. They are separate arguments because
  // the console wording is a developer's and has never been shown to anyone
  // — "Token rejected by server" is not an explanation a parent can act on.
  const forceLogout = (notice: LogoutReason, detail: string) => {
    console.warn('[AppShell] Forced logout:', detail)
    setLogoutNotice(notice)
    logout()
    setReady(false)
    navigate('/', { replace: true })
  }

  const validateToken = async (currentToken: string) => {
    try {
      const res = await fetch('/api/auth/validate', {
        headers: { Authorization: `Bearer ${currentToken}` },
        credentials: 'same-origin',
      })
      if (!res.ok) {
        forceLogout('session-expired', 'Token rejected by server')
        return false
      }
      return true
    } catch {
      // Network error — don't force logout on flaky network; retry on next interval
      return true
    }
  }

  useEffect(() => {
    if (!token) {
      setReady(true)  // allow login page to render (RequireAuth handles redirect)
      return
    }

    // Validate immediately
    validateToken(token).then((ok) => {
      if (ok) setReady(true)
    })

    // Re-validate periodically
    validateTimerRef.current = setInterval(() => {
      if (token) validateToken(token)
    }, VALIDATE_INTERVAL_MS)

    // Inactivity monitor
    const resetActivity = () => {
      lastActivityRef.current = Date.now()
      setIdleWarning((shown) => (shown ? false : shown))
    }
    const activityEvents = ['mousedown', 'keydown', 'touchstart', 'scroll']
    activityEvents.forEach((e) => window.addEventListener(e, resetActivity, { passive: true }))

    inactivityTimerRef.current = setInterval(() => {
      // Being busy IS activity: a child sitting still while Bede reads a
      // passage aloud is the most engaged they get, and produces no input
      // events at all. Bumping here (rather than only short-circuiting the
      // status) means the full window restarts once Bede stops, instead of
      // resuming a countdown that ran underneath the reading.
      if (busyRef.current) {
        resetActivity()
        setIdleWarning(false)
        return
      }
      const status = idleStatus({ lastActiveAt: lastActivityRef.current, now: Date.now() })
      if (status === 'expired') forceLogout('inactivity', 'Inactivity timeout')
      else setIdleWarning(status === 'warning')
    }, IDLE_CHECK_INTERVAL_MS)

    return () => {
      if (validateTimerRef.current) clearInterval(validateTimerRef.current)
      if (inactivityTimerRef.current) clearInterval(inactivityTimerRef.current)
      activityEvents.forEach((e) => window.removeEventListener(e, resetActivity))
    }
  }, [token]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      {ready ? children : <SplashScreen />}
      {idleWarning && (
        // A notice, not a modal. The session has not ended and nothing is
        // blocked — a child reading quietly should be able to ignore this,
        // glance at it, or touch anything at all to clear it. The previous
        // behaviour was a cold forceLogout with no warning, which mid-lesson
        // is indistinguishable from the app crashing.
        <div
          role="status"
          aria-live="polite"
          className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 max-w-md px-4 py-3 rounded-2xl
                     bg-amber-50 text-amber-900 border border-amber-200 shadow-lg text-sm text-center"
        >
          {i18n.t('common.idleWarning')}
        </div>
      )}
      <TextSizeControl />
    </>
  )
}

function SplashScreen() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-parchment-100 via-sage-50 to-faith-100 flex items-center justify-center">
      <div className="text-center">
        <AgnusDeiMark className="w-16 h-16 mx-auto mb-4 animate-pulse-soft" />
        <p className="text-sage-600 font-display text-lg font-semibold">
          <BedeWordmark />
        </p>
        <p className="text-xs text-gray-400 mt-2">Verifying session…</p>
      </div>
    </div>
  )
}
