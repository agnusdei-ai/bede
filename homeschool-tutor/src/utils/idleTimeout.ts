/**
 * The session-wide inactivity logout, and what "inactive" is allowed to mean.
 *
 * `AppShell` has always logged a session out after 30 minutes with no
 * interaction. Two things about how it did that are worth fixing rather than
 * inheriting:
 *
 * 1. IT COUNTED ONLY INPUT. The reset fired on mousedown, keydown, touchstart
 *    and scroll. Nothing about Bede *speaking* or *streaming* counted. So the
 *    most engaged a child can be — sitting still, listening to a passage read
 *    aloud, thinking — looked identical to an abandoned tab. A 30-minute fuse
 *    mostly hid that rather than fixing it, but a long Living Books reading
 *    plus quiet narration genuinely walks toward it, and being logged out
 *    mid-lesson costs a real family a password or a PIN to get back in.
 *
 * 2. IT FIRED COLD. `forceLogout('Inactivity timeout')` with no warning, no
 *    chance to say "still here". For a child mid-lesson that is indistinguish-
 *    able from the app crashing.
 *
 * Both are the same shape as the demo's own idle handling, and the reasoning
 * is identical: activity is the union of real interaction AND the session
 * doing something on the learner's behalf.
 *
 * The 30-minute window itself is deliberately UNCHANGED. It is session-wide,
 * covering reading and thinking time rather than just chat, and shortening it
 * is a product decision nobody asked for. This only makes it count the right
 * things and announce itself before acting.
 */

/** Unchanged from AppShell's original constant — see the note above. */
export const IDLE_TIMEOUT_MS = 30 * 60 * 1000

/**
 * How long before the logout the "still there?" prompt appears. Long enough
 * that a child reading quietly can notice it and respond without rushing.
 */
export const IDLE_WARNING_MS = 90_000

/** How often AppShell samples this. Must be well under IDLE_WARNING_MS so the
 *  warning can never fall between two checks and be skipped entirely. */
export const IDLE_CHECK_INTERVAL_MS = 15_000

export interface SessionBusySignals {
  /** Bede is streaming a reply. */
  isStreaming: boolean
  /** Bede is speaking aloud, or the mic is capturing/transcribing. */
  voiceActive: boolean
}

/**
 * Whether the session counts as active with nobody touching the screen.
 * Both of these mean the learner is engaged — waiting on Bede, listening to
 * Bede, or talking to Bede — so neither may advance the idle clock.
 */
export function isSessionBusy(s: SessionBusySignals): boolean {
  return s.isStreaming || s.voiceActive
}

export type IdleStatus = 'active' | 'warning' | 'expired'

/**
 * Pure: how idle is this session? Free of timers and React so the boundaries
 * are tested directly rather than inferred from a rendered component.
 *
 * `busy` short-circuits to 'active' — the caller is also expected to bump
 * lastActiveAt while busy, but returning 'active' here too means a caller
 * that forgets cannot pop a "still there?" prompt over a child who is
 * listening to Bede at that very moment.
 */
export function idleStatus({ lastActiveAt, now, busy = false, timeoutMs = IDLE_TIMEOUT_MS }: {
  lastActiveAt: number
  now: number
  busy?: boolean
  timeoutMs?: number
}): IdleStatus {
  if (busy) return 'active'
  const idleFor = now - lastActiveAt
  if (idleFor >= timeoutMs) return 'expired'
  if (idleFor >= timeoutMs - IDLE_WARNING_MS) return 'warning'
  return 'active'
}
