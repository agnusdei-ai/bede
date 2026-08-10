/**
 * The gate on the beta survey prompt. Three of these pin refusals rather
 * than behaviour, because the failure modes here are quiet: a prompt that
 * re-asks a parent who already answered is nagging, one that treats a
 * mid-task dismissal as a permanent no silently loses the response, and a
 * corrupted stored value that throws would take the whole Progress page
 * down for a parent who has never seen a survey.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { DEFER_DAYS, surveyIsDue } from './useBetaSurvey'

const KEY = 'bede-beta-survey-v1'
const DAY = 24 * 60 * 60 * 1000
const NOW = 1_700_000_000_000

beforeEach(() => localStorage.clear())
afterEach(() => localStorage.clear())

describe('when the prompt is due', () => {
  it('is due on a device that has never been asked', () => {
    expect(surveyIsDue(NOW)).toBe(true)
  })

  it('is never due again once answered or declined', () => {
    localStorage.setItem(KEY, JSON.stringify({ state: 'closed', at: NOW }))
    expect(surveyIsDue(NOW)).toBe(false)
    // Not even years later.
    expect(surveyIsDue(NOW + 999 * DAY)).toBe(false)
  })

  it('holds a "not now" for the full defer window', () => {
    localStorage.setItem(KEY, JSON.stringify({ state: 'deferred', at: NOW }))
    expect(surveyIsDue(NOW)).toBe(false)
    expect(surveyIsDue(NOW + (DEFER_DAYS - 1) * DAY)).toBe(false)
  })

  it('asks again after the defer window, since being busy is not a refusal', () => {
    localStorage.setItem(KEY, JSON.stringify({ state: 'deferred', at: NOW }))
    expect(surveyIsDue(NOW + DEFER_DAYS * DAY)).toBe(true)
  })
})

describe('a stored value is validated, not trusted', () => {
  it.each([
    ['not JSON at all', 'wat'],
    ['JSON of the wrong shape', '[1,2,3]'],
    ['a state it does not recognise', JSON.stringify({ state: 'maybe', at: NOW })],
    ['a missing timestamp', JSON.stringify({ state: 'deferred' })],
    ['a non-numeric timestamp', JSON.stringify({ state: 'deferred', at: 'soon' })],
    ['an infinite timestamp', JSON.stringify({ state: 'deferred', at: Infinity })],
  ])('treats %s as never asked rather than throwing', (_what, stored) => {
    localStorage.setItem(KEY, stored)
    expect(() => surveyIsDue(NOW)).not.toThrow()
    expect(surveyIsDue(NOW)).toBe(true)
  })

  it('still refuses a corrupt "closed" record rather than re-asking', () => {
    // The one asymmetry worth stating: a malformed value falls back to
    // asking, which is the safe direction for everything except a parent
    // who has said no. A well-formed closed record is the only thing that
    // can express that, so it must survive being read back exactly.
    localStorage.setItem(KEY, JSON.stringify({ state: 'closed', at: 0 }))
    expect(surveyIsDue(NOW)).toBe(false)
  })
})
