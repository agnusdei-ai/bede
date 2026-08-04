/**
 * Telling someone WHY they were signed out.
 *
 * Every automated logout in this app did the same two things — `logout()`
 * then `navigate('/')` — and said nothing. From the seat of whoever was
 * using it, the lesson simply vanished and the login screen was there
 * instead. That is indistinguishable from a crash, and it is worse for a
 * child than for a parent: a parent guesses "it timed out"; a child assumes
 * they broke it, or that Bede left.
 *
 * The idle path now warns first (utils/idleTimeout.ts, IDLE_WARNING_MS), so
 * the logout itself is no longer a surprise if anyone was looking at the
 * screen. But the whole point of an inactivity timeout is that nobody was —
 * the warning is shown to an empty chair. The notice is what's left when
 * they come back, and it is the only part of this the person actually reads.
 *
 * WHY sessionStorage AND NOT ROUTER STATE
 *
 * `navigate('/', { state })` would carry it too, but it lives in the history
 * entry: a refresh re-shows it, and a back/forward can resurrect it long
 * after it stopped being true. A notice about something that happened once
 * should be consumable exactly once. `take` reads and clears in one step,
 * so there is no path where it is displayed twice.
 *
 * The store is deliberately NOT the channel either: `logout()` wipes it by
 * design, so anything written there would have to be written after the wipe
 * and would then be a piece of session state that outlives the session.
 */

/**
 * Why a session ended without anyone asking it to.
 *
 * Only reasons a person can act on. `inactivity` and `break-inactivity` are
 * kept apart because the honest instruction differs: the first means "you
 * were away", the second means "you were away DURING a break", which is a
 * rule docs/CHILD_GUIDE.md already explains to the child in those terms.
 */
export type LogoutReason = 'inactivity' | 'break-inactivity' | 'session-expired'

const STORAGE_KEY = 'bede-logout-notice'

const VALID: readonly LogoutReason[] = ['inactivity', 'break-inactivity', 'session-expired']

/** i18n keys, one per reason. Exported so a test can prove every reason has
 *  a string in every locale rather than falling back to the raw key. */
export const LOGOUT_NOTICE_KEYS: Record<LogoutReason, string> = {
  'inactivity': 'common.loggedOutInactivity',
  'break-inactivity': 'common.loggedOutBreakInactivity',
  'session-expired': 'common.loggedOutSessionExpired',
}

/**
 * Record why the session is about to end. Call this BEFORE `logout()` — not
 * because the store touches this key (it doesn't), but so a notice can never
 * be left behind by a logout path that returns early between the two.
 *
 * Storage can throw (Safari private browsing, a full quota, a locked-down
 * embedded webview). A missing explanation is a worse login screen; a
 * failed logout is a security problem. So this swallows and moves on — it
 * must never be the reason a session fails to end.
 */
export function setLogoutNotice(reason: LogoutReason): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, reason)
  } catch {
    // Intentionally silent — see above.
  }
}

/**
 * Read the pending notice and clear it, in one step. Returns null when there
 * is none, or when the stored value isn't one this build knows about (an
 * older tab, a hand-edited value) — an unrecognised reason must not render
 * as a raw i18n key at a person who is already confused about why they're
 * looking at a login screen.
 */
export function takeLogoutNotice(): LogoutReason | null {
  let raw: string | null = null
  try {
    raw = sessionStorage.getItem(STORAGE_KEY)
    sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    return null
  }
  return VALID.includes(raw as LogoutReason) ? (raw as LogoutReason) : null
}

// There is deliberately no `clearLogoutNotice`. It would only matter if a
// notice could still be pending when someone signs out on purpose, and no
// such sequence exists: every writer sets the key immediately before a
// navigate to the login screen, and the login screen consumes it on mount.
// An unreachable guard is one nobody can tell has stopped working — the
// standing lesson from docs/GUARD_AUDIT.md — so it isn't here.
