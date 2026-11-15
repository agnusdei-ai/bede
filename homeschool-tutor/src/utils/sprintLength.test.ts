/**
 * The learning sprint setting (20, 30 or 60 minutes): when a pause is
 * offered, and what it must never be able to do.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  SESSION_STUDY_MINUTES, SPRINT_MINUTES_OPTIONS, cleanSprintMinutes,
  getSuggestedBreak, suggestedBreakIntervalMinutes, type PhaseInfo,
} from './gradeTimer'

const study = (elapsedMin: number, cycle = 0): PhaseInfo => ({
  phase: 'study', cycleIndex: cycle,
  remainingSecs: (SESSION_STUDY_MINUTES - elapsedMin) * 60,
} as PhaseInfo)

describe('learning sprint length', () => {
  it('offers the three lengths the backend accepts', () => {
    const py = readFileSync(resolve(__dirname, '../../../homeschool-api/models/schemas.py'), 'utf8')
    const m = py.match(/SPRINT_MINUTES_OPTIONS = \(([^)]*)\)/)!
    expect(m[1].split(',').map((x) => Number(x.trim()))).toEqual([...SPRINT_MINUTES_OPTIONS])
    expect([...SPRINT_MINUTES_OPTIONS]).toEqual([20, 30, 60])
  })

  it('unset changes nothing, for either age group', () => {
    for (let m = 0; m < 60; m++) {
      for (const younger of [true, false]) {
        for (const frequent of [true, false]) {
          expect(getSuggestedBreak(study(m), younger, frequent, null))
            .toEqual(getSuggestedBreak(study(m), younger, frequent))
        }
      }
    }
  })

  it('a 20-minute sprint offers a pause at 20 and 40, at any grade', () => {
    expect(getSuggestedBreak(study(19), false, false, 20)).toBeNull()
    expect(getSuggestedBreak(study(20), false, false, 20)).toMatchObject({ mark: 1 })
    expect(getSuggestedBreak(study(40), false, false, 20)).toMatchObject({ mark: 2 })
  })

  it('a 30-minute sprint offers one pause, at 30, even for a younger child', () => {
    for (let m = 0; m < 30; m++) expect(getSuggestedBreak(study(m), true, true, 30)).toBeNull()
    for (let m = 30; m < 60; m++) {
      expect(getSuggestedBreak(study(m), true, false, 30)).toEqual({ mark: 1, key: '0:1' })
    }
  })

  it('a 1-hour sprint offers no pause: the required break ends it', () => {
    for (let m = 0; m < 60; m++) {
      expect(getSuggestedBreak(study(m), true, true, 60)).toBeNull()
    }
  })

  it('never offers anything during a break or after the session ends', () => {
    for (const phase of ['break', 'concluded'] as const) {
      for (const sprint of SPRINT_MINUTES_OPTIONS) {
        expect(getSuggestedBreak({ ...study(30), phase }, true, true, sprint)).toBeNull()
      }
    }
  })

  it('names the minute it is offered at from the chosen sprint', () => {
    expect(suggestedBreakIntervalMinutes(30)).toBe(30)
    expect(suggestedBreakIntervalMinutes(null)).toBe(20)
    expect(suggestedBreakIntervalMinutes()).toBe(20)
  })

  it('a stored value that is not one of the three is treated as unset', () => {
    for (const bad of [0, 15, 45, 90, '20', true, null, undefined, NaN]) {
      expect(cleanSprintMinutes(bad)).toBeNull()
    }
    for (const ok of SPRINT_MINUTES_OPTIONS) expect(cleanSprintMinutes(ok)).toBe(ok)
  })

  it('the setup screen loads and saves the setting', () => {
    const src = readFileSync(resolve(__dirname, '../pages/ParentSetup.tsx'), 'utf8')
    expect(src).toContain('sprint_minutes: cleanSprintMinutes(c.sprint_minutes)')
    expect(src).toContain('sprint_minutes: s.sprint_minutes,')
    expect(src).toContain("t('parentSetup.sprintLength')")
  })

  it('the session screen passes the setting to the timer', () => {
    const src = readFileSync(resolve(__dirname, '../pages/TutorSession.tsx'), 'utf8')
    expect(src).toMatch(/cleanSprintMinutes\(sessionConfig\?\.sprint_minutes\)/)
    expect(src).toMatch(/getSuggestedBreak\([^)]*sprintMinutes,\s*\)/s)
  })
})
