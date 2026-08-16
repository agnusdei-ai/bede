/**
 * One place that turns a 401 from anywhere in the app into a clean logout.
 *
 * Same technique as ElevationPrompt.tsx (which does this for 403s): wrap
 * window.fetch once at the root, so no individual call site has to know
 * that a rejected token means "start over at the login screen."
 *
 * Lived inside App.tsx until it grew a rule worth testing — see the token
 * check below, which is the difference between explaining a real session
 * expiry and telling a parent something false about why their password
 * didn't work.
 */
import { useEffect } from 'react'
import { useNavigate } from 'react-router'

import { useSessionStore } from '../store/sessionStore'
import { setLogoutNotice } from '../utils/logoutNotice'

/**
 * Endpoints whose 401 means "that credential was wrong", NOT "your session
 * is over" — the distinction this whole component turns on.
 *
 * Every one of these VERIFIES a freshly-typed secret against a session
 * that is still perfectly valid. Treating their 401 as an expiry ends a
 * live session over a typo and then explains it with something false.
 *
 * /auth/elevate is the one that bites hardest, and it is invisible without
 * testing the two root fetch wrappers together: ElevationPrompt calls
 * elevateSession() from inside its own modal, so that request travels this
 * same wrapper. A parent mistyping their password in a step-up prompt was
 * logged out of the app entirely and told their session had expired. See
 * interceptorComposition.test.tsx.
 *
 * The MFA verify pair is the same shape one step earlier: a wrong TOTP
 * code or a failed security-key ceremony must leave the parent_pending
 * token intact so ParentMfaVerification can say "try again" and mean it,
 * rather than silently discarding the token its retry depends on.
 */
const CREDENTIAL_CHECK_PATHS = [
  '/auth/elevate',
  '/mfa/totp/authenticate/verify',
  '/mfa/webauthn/authenticate/verify',
]

export default function GlobalAuthInterceptor() {
  const navigate = useNavigate()
  const logout = useSessionStore((s) => s.logout)

  useEffect(() => {
    const originalFetch = window.fetch.bind(window)

    window.fetch = async (...args) => {
      const response = await originalFetch(...args)
      if (response.status === 401) {
        const url = typeof args[0] === 'string' ? args[0] : (args[0] as Request).url
        const isCredentialCheck = CREDENTIAL_CHECK_PATHS.some((p) => url.includes(p))
        if (!isCredentialCheck && (url.startsWith('/api/') || url.includes(window.location.host))) {
          // Only claim a session EXPIRED if there was one. A wrong password
          // at the login screen is a 401 too, and it lands here — without
          // this check it would put "your session expired" on screen next to
          // the real "incorrect password", telling the parent a second,
          // false thing about why their login didn't work. Read through
          // getState() rather than a subscribed value: this closure is built
          // once, when the effect runs, and a subscribed token would be the
          // value from that moment rather than from the moment of the 401.
          if (useSessionStore.getState().token) setLogoutNotice('session-expired')
          logout()
          navigate('/', { replace: true })
        }
      }
      return response
    }

    return () => {
      window.fetch = originalFetch
    }
  }, [logout, navigate])

  return null
}
