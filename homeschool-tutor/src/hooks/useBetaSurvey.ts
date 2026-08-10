import { useCallback, useState } from 'react'

/**
 * Whether this device should show the parent the beta survey prompt (see
 * BetaSurveyModal.tsx) — plain localStorage, same convention as
 * useMeetBede.ts, independent of the auth-scoped session store so it
 * survives logins and logouts.
 *
 * Deliberately keyed per DEVICE and not per student. The survey asks about
 * the family's experience ("what happened to your own teaching time"), not
 * about one child, so asking once per child would be asking the same parent
 * the same questions three times.
 *
 * Three states rather than a boolean, because "not now" and "answered" have
 * to behave differently. A parent who dismisses a prompt mid-task has not
 * declined the survey, they were busy; asking again in a fortnight is fair,
 * and treating that dismissal as a permanent no would quietly lose the
 * response. A parent who submits, or who explicitly says no thanks, is
 * never asked again on this device.
 *
 * CONTENT_VERSION mirrors useMeetBede.ts's versioning idea: a genuinely
 * new set of survey questions can re-ask everyone by bumping this, without
 * touching anyone's stored value. Bump it only for a real new instrument,
 * never to re-ask people who already answered the same questions.
 */
const CONTENT_VERSION = 1
const STORAGE_KEY = `bede-beta-survey-v${CONTENT_VERSION}`

/** How long a "not now" holds before the prompt is offered again. */
export const DEFER_DAYS = 14

export type BetaSurveyState = 'unasked' | 'deferred' | 'closed'

type Stored = { state: Exclude<BetaSurveyState, 'unasked'>; at: number }

function read(): Stored | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<Stored>
    // Validated rather than trusted: localStorage is editable, and a
    // malformed value must mean "ask normally", never throw inside render.
    if (parsed?.state !== 'deferred' && parsed?.state !== 'closed') return null
    if (typeof parsed.at !== 'number' || !Number.isFinite(parsed.at)) return null
    return { state: parsed.state, at: parsed.at }
  } catch {
    return null
  }
}

function write(state: Stored['state'], now: number) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ state, at: now }))
  } catch {
    // Best-effort. A failed save means this device asks again, which is a
    // better failure than never asking at all.
  }
}

/**
 * Whether the prompt is due, given what this device has stored.
 * Exported separately from the hook so the rule can be tested without a
 * component, and read once at mount rather than on every render.
 */
export function surveyIsDue(now: number = Date.now()): boolean {
  const stored = read()
  if (!stored) return true
  if (stored.state === 'closed') return false
  return now - stored.at >= DEFER_DAYS * 24 * 60 * 60 * 1000
}

export function useBetaSurvey() {
  const [due, setDue] = useState<boolean>(() => surveyIsDue())

  /** Answered, or explicitly declined. Never ask again on this device. */
  const close = useCallback(() => {
    setDue(false)
    write('closed', Date.now())
  }, [])

  /** Dismissed for now. Ask again after DEFER_DAYS. */
  const defer = useCallback(() => {
    setDue(false)
    write('deferred', Date.now())
  }, [])

  return { due, close, defer }
}
