// Mirror of homeschool-tutor/src/utils/gradeTimer.ts for the demo app —
// same session rules, so the demo experience matches the real one.
/**
 * Session timing rules:
 *
 * SESSION LEVEL (every grade, by design):
 *   - The session is hard-capped: it concludes automatically at
 *     SessionConfig.session_cap_minutes, which defaults to 2 hours and can
 *     be raised by the parent (behind the parent password) to at most
 *     MAX_SESSION_CAP_MINUTES — 4 hours is the ceiling, structurally; no
 *     stored value can exceed it (clamped both here and in the backend
 *     schema). There is no "off".
 *   - Within the cap, a mandatory 10-minute break follows every 60 minutes
 *     of session time — away from the screen: be with nature, rest the
 *     eyes, reflect on God. The break overlay has no dismiss button.
 *
 * SUBJECT LEVEL (pacing only):
 *   K–3  → 20-min per-subject blocks (timer resets with each subject)
 *   4–8  → the session-level 60/10 cycle IS their pacing (their subject
 *          timer runs on session time, not per-subject).
 *
 * On top of both, a parent can optionally set a total on-screen time cap
 * (SessionConfig.screen_time_limit_minutes). Reaching it forces an eye-rest
 * break — enforced to be at least MIN_EYE_REST_MINUTES regardless of what's
 * configured — modeled as its own study/break cycle via getPhase(), keyed to
 * the whole session's elapsed time. Independent of the session cap above (it
 * calls getPhase() without a totalCapMinutes, so it keeps its own repeating
 * cycle rather than concluding the session).
 */

export const MIN_EYE_REST_MINUTES = 30

export function effectiveEyeRestMinutes(configured: number | undefined): number {
  return Math.max(MIN_EYE_REST_MINUTES, configured ?? MIN_EYE_REST_MINUTES)
}

// The session-level rhythm: 60 minutes of study, then a mandatory 10-minute
// break, repeating until the session cap concludes the sitting.
export const SESSION_STUDY_MINUTES = 60
export const SESSION_BREAK_MINUTES = 10
// On by default and always present: 2 hours unless the parent raises it —
// never above 4 hours, never below half an hour, never off.
export const DEFAULT_SESSION_CAP_MINUTES = 120
export const MIN_SESSION_CAP_MINUTES = 30
export const MAX_SESSION_CAP_MINUTES = 240

// Resolves whatever is stored (including configs saved before the field
// existed, and any value a bypassed client managed to save) to an enforced
// cap — absent means the 2-hour default, and the 4-hour ceiling always wins.
export function effectiveSessionCap(configured: number | null | undefined): number {
  return Math.min(MAX_SESSION_CAP_MINUTES, Math.max(MIN_SESSION_CAP_MINUTES, configured ?? DEFAULT_SESSION_CAP_MINUTES))
}

export interface TimerConfig {
  blockMinutes: number
  breakMinutes: number
  warningMinutes: number
  isYounger: boolean
  totalCapMinutes?: number
}

export function getTimerConfig(grade: string, sessionCapMinutes?: number | null): TimerConfig {
  const g = grade.toLowerCase().trim()
  const isYounger = g === 'k' || g === 'kindergarten' || (!isNaN(parseInt(g)) && parseInt(g) <= 3)
  return isYounger
    ? { blockMinutes: 20, breakMinutes: 0, warningMinutes: 5, isYounger: true }
    : {
        blockMinutes: SESSION_STUDY_MINUTES,
        breakMinutes: SESSION_BREAK_MINUTES,
        warningMinutes: 10,
        isYounger: false,
        totalCapMinutes: effectiveSessionCap(sessionCapMinutes),
      }
}

export type Phase = 'study' | 'break' | 'concluded'

export interface PhaseInfo {
  phase: Phase
  remainingSecs: number
  cycleIndex: number      // which study block we're in (0-based)
  elapsedSecs: number
}

export function getPhase(
  startedAt: Date | null,
  blockMinutes: number,
  breakMinutes: number,
  totalCapMinutes?: number,
): PhaseInfo {
  if (!startedAt) {
    return { phase: 'study', remainingSecs: blockMinutes * 60, cycleIndex: 0, elapsedSecs: 0 }
  }
  const elapsedSecs = Math.floor((Date.now() - startedAt.getTime()) / 1000)

  // Hard-capped mode (the session ceiling): repeating study/break cycles —
  // a mandatory break after every full study block — concluding the moment
  // total elapsed time reaches the cap. At the 2-hour default this is one
  // block, one break, one final block (identical to the old single-break
  // behavior); a parent-extended cap simply keeps the rhythm going, so a
  // longer sitting never means a longer unbroken stretch of screen time.
  if (totalCapMinutes !== undefined) {
    const capSecs = totalCapMinutes * 60
    const cycleSecs = (blockMinutes + breakMinutes) * 60
    const capCycleIndex = Math.floor(capSecs / cycleSecs)

    if (elapsedSecs >= capSecs) {
      return { phase: 'concluded', remainingSecs: 0, cycleIndex: capCycleIndex, elapsedSecs }
    }
    const cycleIndex = Math.floor(elapsedSecs / cycleSecs)
    const posInCycle = elapsedSecs % cycleSecs
    if (posInCycle < blockMinutes * 60) {
      // Study — but never show more time than the cap itself has left.
      const remaining = Math.min(blockMinutes * 60 - posInCycle, capSecs - elapsedSecs)
      return { phase: 'study', remainingSecs: remaining, cycleIndex, elapsedSecs }
    }
    // A break only starts if study time remains after it — elapsed < cap
    // here, so a break the cap would cut short still runs, but the session
    // concludes at the cap regardless.
    return {
      phase: 'break',
      remainingSecs: Math.min(cycleSecs - posInCycle, capSecs - elapsedSecs),
      cycleIndex,
      elapsedSecs,
    }
  }

  const cycleSecs = (blockMinutes + breakMinutes) * 60

  // No break (K-3): simple single block
  if (breakMinutes === 0) {
    return {
      phase: 'study',
      remainingSecs: Math.max(0, blockMinutes * 60 - elapsedSecs),
      cycleIndex: 0,
      elapsedSecs,
    }
  }

  const cycleIndex = Math.floor(elapsedSecs / cycleSecs)
  const posInCycle = elapsedSecs % cycleSecs

  if (posInCycle < blockMinutes * 60) {
    return {
      phase: 'study',
      remainingSecs: blockMinutes * 60 - posInCycle,
      cycleIndex,
      elapsedSecs,
    }
  } else {
    return {
      phase: 'break',
      remainingSecs: cycleSecs - posInCycle,
      cycleIndex,
      elapsedSecs,
    }
  }
}

export function fmtTime(secs: number): string {
  const m = Math.floor(secs / 60)
  const s = secs % 60
  return `${m}:${String(s).padStart(2, '0')}`
}
