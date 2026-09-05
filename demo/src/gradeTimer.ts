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

// ── Suggested breaks for K-3 ─────────────────────────────────────────────
//
// A younger child's attention is shorter, but it is not uniformly shorter:
// some 6-year-olds genuinely settle into 40 minutes, and stopping them dead
// at 20 wastes the best stretch of their morning. So the 20-minute rhythm is
// OFFERED rather than imposed — a dismissible suggestion at the 20- and
// 40-minute marks of each study block, which the child (or the parent beside
// them) can wave off with one tap.
//
// The 60-minute break stays mandatory for every grade, exactly as before.
// Nothing here can extend a study block past an hour, raise the session cap,
// or dismiss a mandatory break; suggestions live strictly INSIDE the hour
// that the mandatory rhythm already governs.
export const SUGGESTED_BREAK_INTERVAL_MINUTES = 20

export interface SuggestedBreak {
  /** 1 = the 20-minute mark, 2 = the 40-minute mark. */
  mark: number
  /** Stable identity for "this one has already been waved off". Includes the
   *  cycle index so each hour's marks are independent — waving off the 20-
   *  minute suggestion before the first mandatory break must not silently
   *  wave off the one in the hour after it. */
  key: string
}

/**
 * The suggestion (if any) owed at this moment. Pure — takes the session's
 * own PhaseInfo so it can never disagree with the mandatory rhythm it sits
 * inside.
 *
 * Returns null for grades 4-8 (their pacing IS the 60/10 cycle) UNLESS the
 * parent set frequentBreakOffers for this student, during any mandatory
 * break or once concluded, and for the first 20 minutes of each study
 * block.
 */
export function getSuggestedBreak(
  phase: PhaseInfo,
  isYounger: boolean,
  frequentBreakOffers = false,
): SuggestedBreak | null {
  // The age gate was the whole availability rule, so a twelve-year-old whose
  // parent knows they do better stopping every twenty minutes could not have
  // that rhythm at all — not because anyone decided against it, but because
  // the only way in was being under nine.
  //
  // `frequentBreakOffers` is the parent saying otherwise for one student. It
  // is NOT a claim that more breaks improve attention: the ADHD literature
  // supports physical activity generally (moderate effect, cognitive
  // engagement the active ingredient) and does not support that specific
  // claim — see docs/ACCESSIBILITY_RESEARCH.md §5. What it does is remove an
  // arbitrary age gate on a choice that belongs to the parent, per the
  // constitution's authority_order.
  //
  // Everything below is unchanged, so it still cannot shorten, skip, delay
  // or extend past the mandatory hourly break — it only makes the existing
  // suggestion reachable at a grade that was previously refused it.
  if ((!isYounger && !frequentBreakOffers) || phase.phase !== 'study') return null
  const studyElapsedSecs = SESSION_STUDY_MINUTES * 60 - phase.remainingSecs
  const mark = Math.floor(studyElapsedSecs / (SUGGESTED_BREAK_INTERVAL_MINUTES * 60))
  if (mark < 1) return null
  return { mark, key: `${phase.cycleIndex}:${mark}` }
}

export function fmtTime(secs: number): string {
  const m = Math.floor(secs / 60)
  const s = secs % 60
  return `${m}:${String(s).padStart(2, '0')}`
}
