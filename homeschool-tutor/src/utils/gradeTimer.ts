/**
 * Session timing rules by grade:
 *   K–3  → 20-min per-subject blocks, no break (timer resets with each subject)
 *   4–8  → hard-capped at TOTAL_CAP_MINUTES per sitting: a 60-min block, a
 *          10-min break, then one final block for the remaining time —
 *          exactly one break, then the session concludes. Not a repeating
 *          cycle (unlike the optional eye-rest mechanism below) — this is a
 *          fixed screen-time ceiling per session, not per-subject pacing.
 *
 * On top of the grade-based cycle above, a parent can optionally set a total
 * on-screen time cap (SessionConfig.screen_time_limit_minutes). Reaching it
 * forces an eye-rest break — enforced to be at least MIN_EYE_REST_MINUTES
 * regardless of what's configured — modeled as its own study/break cycle via
 * getPhase(), keyed to the whole session's elapsed time rather than per-subject.
 * This is a separate, independent mechanism from the 4-8 hard cap above (it
 * calls getPhase() without a totalCapMinutes, so it keeps its own repeating
 * cycle rather than concluding the session).
 */

export const MIN_EYE_REST_MINUTES = 30

export function effectiveEyeRestMinutes(configured: number | undefined): number {
  return Math.max(MIN_EYE_REST_MINUTES, configured ?? MIN_EYE_REST_MINUTES)
}

// Grades 4-8's hard per-sitting ceiling: one 60-min block, one 10-min break,
// then a final block for whatever time remains up to this total.
export const GRADE_4_8_TOTAL_CAP_MINUTES = 120

export interface TimerConfig {
  blockMinutes: number
  breakMinutes: number
  warningMinutes: number
  isYounger: boolean
  totalCapMinutes?: number
}

export function getTimerConfig(grade: string): TimerConfig {
  const g = grade.toLowerCase().trim()
  const isYounger = g === 'k' || g === 'kindergarten' || (!isNaN(parseInt(g)) && parseInt(g) <= 3)
  return isYounger
    ? { blockMinutes: 20, breakMinutes: 0,  warningMinutes: 5,  isYounger: true  }
    : { blockMinutes: 60, breakMinutes: 10, warningMinutes: 10, isYounger: false, totalCapMinutes: GRADE_4_8_TOTAL_CAP_MINUTES }
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

  // Hard-capped, single-break mode (grades 4-8's 2-hour ceiling): one block,
  // one break, one final block, then conclude — never repeats.
  if (totalCapMinutes !== undefined) {
    const capSecs = totalCapMinutes * 60
    const block1Secs = blockMinutes * 60
    const breakSecs = breakMinutes * 60

    if (elapsedSecs >= capSecs) {
      return { phase: 'concluded', remainingSecs: 0, cycleIndex: 1, elapsedSecs }
    }
    if (elapsedSecs < block1Secs) {
      return { phase: 'study', remainingSecs: block1Secs - elapsedSecs, cycleIndex: 0, elapsedSecs }
    }
    if (elapsedSecs < block1Secs + breakSecs) {
      return { phase: 'break', remainingSecs: block1Secs + breakSecs - elapsedSecs, cycleIndex: 0, elapsedSecs }
    }
    return { phase: 'study', remainingSecs: capSecs - elapsedSecs, cycleIndex: 1, elapsedSecs }
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
