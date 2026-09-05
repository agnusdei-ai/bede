/**
 * The demo's session rules must BE the product's, not resemble them.
 *
 * `gradeTimer.ts`'s own header has always claimed "same session rules, so the
 * demo experience matches the real one", and that claim was false for as long
 * as the optional 20/40-minute break rhythm existed in the app and not here:
 * a visitor evaluating Bede on a K-2 grade saw a session that never offered a
 * short break, while a real family's child was offered one twice an hour.
 *
 * So this file asserts the claim rather than trusting it. It imports BOTH
 * copies and compares them directly — the same technique `endpointing.test.ts`
 * and `readingPresentation.test.ts` already use, and the only kind of test
 * that can catch the two drifting apart.
 */
import { describe, expect, it } from 'vitest'

import {
  SESSION_STUDY_MINUTES,
  SESSION_BREAK_MINUTES,
  SUGGESTED_BREAK_INTERVAL_MINUTES,
  getSuggestedBreak,
  type PhaseInfo,
} from './gradeTimer'

import * as app from '../../homeschool-tutor/src/utils/gradeTimer'

/** A study phase `minutesIn` minutes into study block `cycleIndex`. */
function study(minutesIn: number, cycleIndex = 0): PhaseInfo {
  return {
    phase: 'study',
    remainingSecs: SESSION_STUDY_MINUTES * 60 - minutesIn * 60,
    cycleIndex,
    elapsedSecs: minutesIn * 60,
  }
}

describe('the demo runs the product’s session rules, not a copy of them', () => {
  it('agrees on every shared constant', () => {
    expect(SESSION_STUDY_MINUTES).toBe(app.SESSION_STUDY_MINUTES)
    expect(SESSION_BREAK_MINUTES).toBe(app.SESSION_BREAK_MINUTES)
    expect(SUGGESTED_BREAK_INTERVAL_MINUTES).toBe(app.SUGGESTED_BREAK_INTERVAL_MINUTES)
  })

  it('returns exactly what the app returns, at every minute of a study block', () => {
    // A sweep rather than a spot check: a difference in the mark arithmetic
    // or the key format would show up somewhere in the hour even if both
    // agreed at the boundaries.
    for (let cycle = 0; cycle < 3; cycle++) {
      for (let m = 0; m <= SESSION_STUDY_MINUTES; m++) {
        for (const younger of [true, false]) {
          for (const frequent of [true, false]) {
            expect(getSuggestedBreak(study(m, cycle), younger, frequent))
              .toEqual(app.getSuggestedBreak(study(m, cycle), younger, frequent))
          }
        }
      }
    }
  })
})

describe('the suggestion itself', () => {
  it('offers nothing before the first mark', () => {
    expect(getSuggestedBreak(study(0), true)).toBeNull()
    expect(getSuggestedBreak(study(19), true)).toBeNull()
  })

  it('offers the 20- and 40-minute marks', () => {
    expect(getSuggestedBreak(study(20), true)).toMatchObject({ mark: 1 })
    expect(getSuggestedBreak(study(40), true)).toMatchObject({ mark: 2 })
  })

  it('cannot reach a third mark inside one study block', () => {
    // Structural, not a rule that has to be remembered: a 60-minute block
    // divided into 20-minute marks yields at most two. Bounded EXCLUSIVELY
    // at 60 because a study block is [0, 60) — getPhase has already turned
    // the phase to 'break' by the time the 60th minute elapses, so a study
    // phase with zero seconds remaining is not a state that occurs.
    for (let m = 20; m < SESSION_STUDY_MINUTES; m++) {
      expect(getSuggestedBreak(study(m), true)!.mark).toBeLessThanOrEqual(2)
    }
  })

  it('is not offered to older grades unless the parent asked for it', () => {
    expect(getSuggestedBreak(study(20), false)).toBeNull()
    expect(getSuggestedBreak(study(45), false)).toBeNull()
    expect(getSuggestedBreak(study(20), false, true)).toMatchObject({ mark: 1 })
  })

  it('follows the same 20/40-minute path for older grades once the override is on', () => {
    for (let m = 0; m < 20; m++) expect(getSuggestedBreak(study(m), false, true)).toBeNull()
    for (let m = 20; m < 40; m++) expect(getSuggestedBreak(study(m), false, true)).toMatchObject({ mark: 1 })
    for (let m = 40; m < SESSION_STUDY_MINUTES; m++) {
      expect(getSuggestedBreak(study(m), false, true)!.mark).toBe(2)
    }
  })

  it('yields nothing during a mandatory break or once concluded', () => {
    // The safety property. A suggestion must never compete with, or look
    // like, something the child is allowed to dismiss.
    const onBreak: PhaseInfo = { phase: 'break', remainingSecs: 300, cycleIndex: 0, elapsedSecs: 3900 }
    const done: PhaseInfo = { phase: 'concluded', remainingSecs: 0, cycleIndex: 2, elapsedSecs: 7200 }
    for (const frequent of [true, false]) {
      expect(getSuggestedBreak(onBreak, true, frequent)).toBeNull()
      expect(getSuggestedBreak(done, true, frequent)).toBeNull()
    }
  })

  it('gives each hour its own keys, so waving one off does not wave off the next', () => {
    const first = getSuggestedBreak(study(20, 0), true)!
    const second = getSuggestedBreak(study(20, 1), true)!
    expect(first.key).not.toBe(second.key)
  })

  it('keeps one stable key for the whole of a mark, so a dismissal sticks', () => {
    const keys = new Set<string>()
    for (let m = 20; m < 40; m++) keys.add(getSuggestedBreak(study(m), true)!.key)
    expect(keys.size).toBe(1)
  })
})
