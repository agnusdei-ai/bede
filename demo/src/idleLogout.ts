/**
 * General idle logout for the demo.
 *
 * Before this the demo had exactly one auto-logout, and it only ran while a
 * break or the end-of-session screen was showing (BREAK_INACTIVITY_LOGOUT_MS
 * in App.tsx, 5 minutes). A visitor who simply stopped using the tab mid-
 * lesson stayed logged in until the server-side code expired hours later —
 * which on a shared or kiosk device leaves someone else's session sitting
 * open on the screen.
 *
 * The whole difficulty here is what "idle" means. The naive version — reset
 * a timer on taps and keystrokes — is actively wrong for this app, because
 * the single most valuable thing a child can be doing is sitting perfectly
 * still LISTENING to Bede read a passage. Narration runs for minutes at a
 * time with no input at all, and logging a child out mid-sentence for
 * "inactivity" would be the app punishing them for paying attention.
 *
 * So activity here is the union of two things:
 *   1. real interaction  — a tap, a key, a touch
 *   2. the session doing something on the learner's behalf — Bede streaming
 *      a reply, Bede speaking, the mic listening, a transcript being made
 *
 * isSessionBusy() is (2). While it holds, the idle clock does not advance at
 * all, so a ten-minute reading is ten minutes of activity rather than ten
 * minutes of silence. That is also why the default is 10 minutes rather than
 * the 5 the break timer uses: the break timer runs when nothing at all is
 * meant to be happening, whereas this one has to leave room for a long quiet
 * stretch of genuine reading that produces no events of either kind.
 *
 * A warning appears shortly before the logout itself (see
 * IDLE_WARNING_MS) so a child who IS still there — reading silently with
 * narration muted, the one case neither signal above can see — gets a chance
 * to say so rather than losing the session without warning.
 */

/** Minutes of genuine idleness before the session ends. */
export const DEFAULT_IDLE_LOGOUT_MINUTES = 10

/**
 * Offered as fixed choices rather than a free number entry (unlike session
 * length, which is a number input): the useful range is narrow, and a
 * hand-typed 1 or 2 would fight ordinary narration no matter how carefully
 * isSessionBusy is defined. 0 means never — for a parent who is sitting with
 * their child on a private device and does not want the interruption.
 */
export const IDLE_LOGOUT_CHOICES = [0, 5, 10, 20, 30] as const

/** How often the idle check runs. Matches App.tsx's existing phase tick, so
 *  the two timers cost the same and neither needs sub-minute precision. */
export const IDLE_CHECK_INTERVAL_MS = 15_000

/** How long before the logout the "still there?" warning appears. Deliberately
 *  longer than IDLE_CHECK_INTERVAL_MS so the warning is always seen at least
 *  once before the session actually ends, never skipped between two ticks. */
export const IDLE_WARNING_MS = 60_000

export interface SessionBusySignals {
  isStreaming: boolean
  isSpeaking: boolean
  isListening: boolean
  isTranscribing: boolean
}

/**
 * Whether the session counts as active right now even with nobody touching
 * the screen. Every one of these means the learner is engaged — waiting on
 * Bede, listening to Bede, or talking to Bede — so none of them may advance
 * the idle clock.
 */
export function isSessionBusy(s: SessionBusySignals): boolean {
  return s.isStreaming || s.isSpeaking || s.isListening || s.isTranscribing
}

/** A stored/typed value coerced to one of the offered choices, falling back
 *  to the default. Guards against a stale or hand-edited sessionStorage
 *  value silently becoming a 1-minute logout. */
export function normalizeIdleMinutes(raw: unknown): number {
  // Absent values are rejected BEFORE Number(), not after. Number(null),
  // Number(undefined via ''), and Number('') all coerce to 0 — which is a
  // legitimate choice here meaning "never log out", so coercing first would
  // turn "this visitor has no stored setting" into "this visitor asked for
  // no idle logout at all", silently disabling the feature for everyone who
  // never opened the menu. sessionStorage.getItem returns null exactly that
  // often, so this is the common path, not an edge case.
  if (raw === null || raw === undefined || raw === '') return DEFAULT_IDLE_LOGOUT_MINUTES
  const n = Number(raw)
  return (IDLE_LOGOUT_CHOICES as readonly number[]).includes(n) ? n : DEFAULT_IDLE_LOGOUT_MINUTES
}

export function isIdleLogoutEnabled(minutes: number): boolean {
  return normalizeIdleMinutes(minutes) > 0
}

export function idleTimeoutMs(minutes: number): number {
  return normalizeIdleMinutes(minutes) * 60_000
}

export type IdleStatus = 'active' | 'warning' | 'expired'

/**
 * Pure: how idle is this session right now? Kept free of timers and React so
 * the boundaries can be tested directly rather than inferred from a rendered
 * component.
 *
 * `busy` short-circuits to 'active' — the caller is expected to also bump
 * lastActiveAt while busy, but returning 'active' here as well means a
 * caller that forgets cannot produce a warning banner over a child who is
 * listening to Bede right now.
 */
export function idleStatus({ lastActiveAt, now, minutes, busy = false }: {
  lastActiveAt: number
  now: number
  minutes: number
  busy?: boolean
}): IdleStatus {
  if (busy || !isIdleLogoutEnabled(minutes)) return 'active'
  const idleFor = now - lastActiveAt
  const timeout = idleTimeoutMs(minutes)
  if (idleFor >= timeout) return 'expired'
  if (idleFor >= timeout - IDLE_WARNING_MS) return 'warning'
  return 'active'
}
