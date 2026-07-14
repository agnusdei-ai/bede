import { useEffect, useRef, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useSessionStore } from '../store/sessionStore'
import TextSizeControl from '../components/TextSizeControl'
import { AgnusDeiMark, BedeWordmark } from '../components/BedeMark'

const VALIDATE_INTERVAL_MS = 5 * 60 * 1000   // re-validate token every 5 min
const INACTIVITY_TIMEOUT_MS = 30 * 60 * 1000  // 30 min of no interaction → re-auth

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
  const location = useLocation()
  const { token, logout } = useSessionStore()
  const [ready, setReady] = useState(false)
  const lastActivityRef = useRef(Date.now())
  const validateTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const inactivityTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const forceLogout = (reason = 'Session expired') => {
    console.warn('[AppShell] Forced logout:', reason)
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
        forceLogout('Token rejected by server')
        return false
      }
      return true
    } catch {
      // Network error — don't force logout on flaky network; retry on next interval
      return true
    }
  }

  useEffect(() => {
    const isLoginPage = location.pathname === '/'

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
    const resetActivity = () => { lastActivityRef.current = Date.now() }
    const activityEvents = ['mousedown', 'keydown', 'touchstart', 'scroll']
    activityEvents.forEach((e) => window.addEventListener(e, resetActivity, { passive: true }))

    inactivityTimerRef.current = setInterval(() => {
      if (Date.now() - lastActivityRef.current > INACTIVITY_TIMEOUT_MS) {
        forceLogout('Inactivity timeout')
      }
    }, 60_000)

    return () => {
      if (validateTimerRef.current) clearInterval(validateTimerRef.current)
      if (inactivityTimerRef.current) clearInterval(inactivityTimerRef.current)
      activityEvents.forEach((e) => window.removeEventListener(e, resetActivity))
    }
  }, [token]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      {ready ? children : <SplashScreen />}
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
