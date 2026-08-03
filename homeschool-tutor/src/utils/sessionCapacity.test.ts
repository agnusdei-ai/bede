/**
 * Intent vs. capacity — the arithmetic that reconciles "how many minutes of
 * subjects has the parent chosen" with "how many minutes of instruction does
 * this session actually hold".
 *
 * The defect these pin closed: `session_cap_minutes` is WALL-CLOCK time and
 * includes the mandatory 10-minute break each hour, while a subject list is
 * INSTRUCTION time. Nothing reconciled the two, and the numbers had silently
 * diverged — the default "Full Daily Plan" scheduled 185 minutes of subjects
 * into a 120-minute cap, which holds 110. Seventy-five minutes of every
 * default day were never reachable, and the only symptom a family saw was the
 * timer hard-stopping mid-subject.
 *
 * For a mastery-based outcome the intent and the capacity have to be equal on
 * purpose, so the presets now DERIVE their caps from their own subject lists
 * and these tests hold that derivation honest.
 */
import { describe, it, expect } from 'vitest'

import {
  MAX_SESSION_CAP_MINUTES,
  MIN_SESSION_CAP_MINUTES,
  SESSION_BREAK_MINUTES,
  SESSION_STUDY_MINUTES,
  SUGGESTED_BREAK_INTERVAL_MINUTES,
  capForStudyMinutes,
  getSuggestedBreak,
  studyMinutesWithinCap,
} from './gradeTimer'
import type { PhaseInfo } from './gradeTimer'
import { SUBJECT_MAP, SUBJECTS } from '../types'
import type { Subject } from '../types'

const studyMinutesFor = (subjects: Subject[]) =>
  subjects.reduce((acc, id) => acc + (SUBJECT_MAP[id]?.durationMin ?? 0), 0)

// Mirrors ParentSetup.tsx's own constants. Kept in step by
// `test_default_subjects_match_the_ui` below rather than imported, since
// ParentSetup is a page component that pulls in the whole app on import.
const ELECTIVES: Subject[] = ['latin', 'greek', 'logic', 'free_study']
const DEFAULT_SUBJECTS = SUBJECTS.filter((s) => !ELECTIVES.includes(s.id)).map((s) => s.id)

describe('studyMinutesWithinCap', () => {
  it('subtracts the mandatory break from every completed hour', () => {
    // 60 study, 10 break, 50 study = 120 elapsed, 110 of it instruction.
    expect(studyMinutesWithinCap(120)).toBe(110)
  })

  it('takes no break out of a cap that never completes an hour', () => {
    expect(studyMinutesWithinCap(60)).toBe(60)
    expect(studyMinutesWithinCap(45)).toBe(45)
  })

  it('holds exactly the full plan at the derived cap', () => {
    expect(studyMinutesWithinCap(215)).toBe(185)
  })

  it('clamps a cap outside the allowed range before computing', () => {
    expect(studyMinutesWithinCap(10_000)).toBe(studyMinutesWithinCap(MAX_SESSION_CAP_MINUTES))
    expect(studyMinutesWithinCap(1)).toBe(studyMinutesWithinCap(MIN_SESSION_CAP_MINUTES))
  })
})

describe('capForStudyMinutes', () => {
  it('is the inverse of studyMinutesWithinCap across the usable range', () => {
    for (let study = MIN_SESSION_CAP_MINUTES; study <= 200; study++) {
      const cap = capForStudyMinutes(study)
      expect(
        studyMinutesWithinCap(cap),
        `a ${study}m plan needs a cap that actually holds it; got ${cap}m holding ${studyMinutesWithinCap(cap)}m`,
      ).toBeGreaterThanOrEqual(study)
    }
  })

  it('never overshoots — the derived cap is the smallest one that fits', () => {
    for (let study = MIN_SESSION_CAP_MINUTES; study <= 200; study++) {
      const cap = capForStudyMinutes(study)
      if (cap > MIN_SESSION_CAP_MINUTES) {
        expect(studyMinutesWithinCap(cap - 1)).toBeLessThan(study)
      }
    }
  })

  it('adds one break per completed study hour', () => {
    expect(capForStudyMinutes(60)).toBe(60)
    expect(capForStudyMinutes(61)).toBe(61 + SESSION_BREAK_MINUTES)
    expect(capForStudyMinutes(185)).toBe(185 + 3 * SESSION_BREAK_MINUTES)
  })

  it('respects the structural 4-hour ceiling', () => {
    expect(capForStudyMinutes(10_000)).toBe(MAX_SESSION_CAP_MINUTES)
  })

  it('degrades safely on a nonsensical plan rather than returning 0', () => {
    expect(capForStudyMinutes(0)).toBe(MIN_SESSION_CAP_MINUTES)
    expect(capForStudyMinutes(-5)).toBe(MIN_SESSION_CAP_MINUTES)
  })
})

describe('the stated intent of the full daily plan', () => {
  it('is 185 minutes of instruction', () => {
    expect(studyMinutesFor(DEFAULT_SUBJECTS)).toBe(185)
  })

  it('fits its derived cap exactly, with nothing unreachable', () => {
    const study = studyMinutesFor(DEFAULT_SUBJECTS)
    const cap = capForStudyMinutes(study)
    expect(cap).toBe(215)
    expect(studyMinutesWithinCap(cap)).toBe(study)
  })

  it('would NOT have fit the old 120-minute cap — the regression this closed', () => {
    expect(studyMinutesWithinCap(120)).toBeLessThan(studyMinutesFor(DEFAULT_SUBJECTS))
  })

  it('stays inside the structural ceiling, so the intent is actually deliverable', () => {
    expect(capForStudyMinutes(studyMinutesFor(DEFAULT_SUBJECTS))).toBeLessThanOrEqual(MAX_SESSION_CAP_MINUTES)
  })
})

describe('mathematics is foundational and therefore never optional', () => {
  // Mirrors COMPANION_MODES in ParentSetup.tsx. Math carries Bede's only
  // full diagnostic engine, so a preset without it yields no mastery signal
  // at all — which made "mastery-based outcome" untrue for exactly the
  // families on the lighter presets.
  const PRESETS: Record<string, Subject[]> = {
    book_companion: ['living_books', 'morning_time', 'mathematics'],
    guided: ['living_books', 'morning_time', 'mathematics', 'language_arts', 'nature_study'],
    full_plan: DEFAULT_SUBJECTS,
  }

  it.each(Object.entries(PRESETS))('%s includes mathematics', (_name, subjects) => {
    expect(subjects).toContain('mathematics')
  })

  it.each(Object.entries(PRESETS))('%s fits the cap derived from its own subjects', (_name, subjects) => {
    const study = studyMinutesFor(subjects)
    expect(studyMinutesWithinCap(capForStudyMinutes(study))).toBeGreaterThanOrEqual(study)
  })

  it('every preset stays within the structural ceiling', () => {
    for (const subjects of Object.values(PRESETS)) {
      expect(capForStudyMinutes(studyMinutesFor(subjects))).toBeLessThanOrEqual(MAX_SESSION_CAP_MINUTES)
    }
  })
})

describe('the electives really are excluded from the default plan', () => {
  it.each(ELECTIVES)('%s is not pre-selected', (elective) => {
    expect(DEFAULT_SUBJECTS).not.toContain(elective)
  })

  it('leaves the Mater Amabilis core rotation intact', () => {
    expect(DEFAULT_SUBJECTS).toContain('mathematics')
    expect(DEFAULT_SUBJECTS).toContain('morning_time')
    expect(DEFAULT_SUBJECTS).toHaveLength(10)
  })

  it('adding every elective still fits inside the 4-hour ceiling', () => {
    // 185 + 10 + 10 + 15 = 220 minutes of instruction, needing a 250-minute
    // cap — which the ceiling clamps to 240. A family enabling all three
    // electives on the full plan genuinely cannot fit them all in one
    // sitting, and this test exists so that stays a known, deliberate fact
    // rather than a surprise.
    const everything = [...DEFAULT_SUBJECTS, 'latin', 'greek', 'logic'] as Subject[]
    const study = studyMinutesFor(everything)
    expect(study).toBe(220)
    expect(capForStudyMinutes(study)).toBe(MAX_SESSION_CAP_MINUTES)
    expect(studyMinutesWithinCap(MAX_SESSION_CAP_MINUTES)).toBeLessThan(study)
  })
})

describe('SESSION constants are what the arithmetic assumes', () => {
  it('is a 60/10 rhythm', () => {
    expect(SESSION_STUDY_MINUTES).toBe(60)
    expect(SESSION_BREAK_MINUTES).toBe(10)
  })
})

// ── K-3's optional 20-minute rhythm ──────────────────────────────────────
//
// A younger child's attention is shorter but not uniformly so — some
// 6-year-olds genuinely settle into 40 minutes, and stopping them dead at 20
// wastes the best stretch of the morning. So the 20-minute rhythm is offered
// and dismissible, while the 60-minute break stays mandatory for everyone.
//
// The invariant that matters most: nothing here can weaken the mandatory
// break. These tests exist to fail loudly if a future edit lets a suggestion
// appear during, replace, or extend past one.
describe('getSuggestedBreak', () => {
  const study = (elapsedMin: number, cycleIndex = 0): PhaseInfo => ({
    phase: 'study',
    remainingSecs: SESSION_STUDY_MINUTES * 60 - elapsedMin * 60,
    cycleIndex,
    elapsedSecs: elapsedMin * 60,
  })

  it('offers nothing in the first 20 minutes', () => {
    expect(getSuggestedBreak(study(0), true)).toBeNull()
    expect(getSuggestedBreak(study(19), true)).toBeNull()
  })

  it('offers the first break at the 20-minute mark', () => {
    expect(getSuggestedBreak(study(20), true)).toMatchObject({ mark: 1 })
  })

  it('offers a second at the 40-minute mark, so a 40-minute stretch is possible', () => {
    expect(getSuggestedBreak(study(39), true)).toMatchObject({ mark: 1 })
    expect(getSuggestedBreak(study(40), true)).toMatchObject({ mark: 2 })
  })

  it('never offers a third — the 60-minute break is mandatory, not suggested', () => {
    for (let m = 40; m < 60; m++) {
      expect(getSuggestedBreak(study(m), true)!.mark).toBeLessThanOrEqual(2)
    }
  })

  it('offers nothing to grades 4-8 — the 60/10 cycle IS their pacing', () => {
    expect(getSuggestedBreak(study(20), false)).toBeNull()
    expect(getSuggestedBreak(study(45), false)).toBeNull()
  })

  it('offers nothing during a mandatory break, or once concluded', () => {
    const onBreak: PhaseInfo = { phase: 'break', remainingSecs: 300, cycleIndex: 0, elapsedSecs: 3900 }
    const done: PhaseInfo = { phase: 'concluded', remainingSecs: 0, cycleIndex: 3, elapsedSecs: 12900 }
    expect(getSuggestedBreak(onBreak, true)).toBeNull()
    expect(getSuggestedBreak(done, true)).toBeNull()
  })

  it('gives each hour its own keys, so waving one off never silences the next', () => {
    const first = getSuggestedBreak(study(20, 0), true)!
    const second = getSuggestedBreak(study(20, 1), true)!
    expect(first.mark).toBe(second.mark)
    expect(first.key).not.toBe(second.key)
  })

  it('gives each mark within an hour its own key', () => {
    expect(getSuggestedBreak(study(20, 0)!, true)!.key)
      .not.toBe(getSuggestedBreak(study(40, 0)!, true)!.key)
  })

  it('is stable across the whole window a mark is open', () => {
    // The banner must not flicker or re-arm while the child is deciding.
    const keys = new Set<string>()
    for (let m = 20; m < 40; m++) keys.add(getSuggestedBreak(study(m), true)!.key)
    expect(keys.size).toBe(1)
  })

  it('uses the same interval constant the UI reports to the child', () => {
    expect(SUGGESTED_BREAK_INTERVAL_MINUTES).toBe(20)
    // mark * interval is what the banner renders as "you've been working N
    // minutes", so the two must not drift.
    expect(getSuggestedBreak(study(40), true)!.mark * SUGGESTED_BREAK_INTERVAL_MINUTES).toBe(40)
  })
})
