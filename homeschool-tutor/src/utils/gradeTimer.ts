/**
 * Session timing rules by grade:
 *   K–3  → 20-min per-subject blocks, no break (timer resets with each subject)
 *   4–8  → 60-min continuous block, then 10-min break, then another 60-min block
 */

export interface TimerConfig {
  blockMinutes: number
  breakMinutes: number
  warningMinutes: number
  isYounger: boolean
}

export function getTimerConfig(grade: string): TimerConfig {
  const g = grade.toLowerCase().trim()
  const isYounger = g === 'k' || g === 'kindergarten' || (!isNaN(parseInt(g)) && parseInt(g) <= 3)
  return isYounger
    ? { blockMinutes: 20, breakMinutes: 0,  warningMinutes: 5,  isYounger: true  }
    : { blockMinutes: 60, breakMinutes: 10, warningMinutes: 10, isYounger: false }
}

export type Phase = 'study' | 'break'

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
): PhaseInfo {
  if (!startedAt) {
    return { phase: 'study', remainingSecs: blockMinutes * 60, cycleIndex: 0, elapsedSecs: 0 }
  }
  const elapsedSecs = Math.floor((Date.now() - startedAt.getTime()) / 1000)
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
