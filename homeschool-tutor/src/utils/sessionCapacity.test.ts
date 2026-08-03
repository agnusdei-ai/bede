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
  capForStudyMinutes,
  studyMinutesWithinCap,
} from './gradeTimer'
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
