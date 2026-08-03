/**
 * The mastery-cycle read. What is pinned here is mostly what this must
 * REFUSE to say — the failure modes are all ways of turning a reporting
 * window into a verdict on a child.
 */
import { describe, expect, it } from 'vitest'

import { describeWindow, readCycle } from './masteryCycle'
import type { NarrationAssessmentData } from '../types'

const NOW = new Date('2026-08-03T12:00:00Z')
const daysAgo = (n: number) => new Date(NOW.getTime() - n * 86400_000).toISOString()

const a = (
  topic: string,
  level: 'introduced' | 'developing' | 'mastered' | null,
  assessed_at: string,
): NarrationAssessmentData =>
  ({
    subject: 'mathematics',
    completeness: 3, sequence: 3, detail: 3, language_quality: 3, synthesis: 3,
    total_score: 15, concepts_demonstrated: [], misconceptions: [],
    adaptive_signal: 'advance', bede_observation: '',
    assessed_at, term_topic: topic, term_topic_level: level,
  }) as NarrationAssessmentData

describe('readCycle — the three outcomes', () => {
  it('reports movement when the level rose inside the window', () => {
    const r = readCycle(
      [a('fractions', 'introduced', daysAgo(40)), a('fractions', 'developing', daysAgo(5))],
      'fractions', 28, NOW,
    )
    expect(r.outcome).toBe('moved')
    expect(r.atWindowStart).toBe('introduced')
    expect(r.now).toBe('developing')
  })

  it('reports held when work happened but the level did not rise', () => {
    const r = readCycle(
      [a('fractions', 'developing', daysAgo(40)), a('fractions', 'developing', daysAgo(3))],
      'fractions', 28, NOW,
    )
    expect(r.outcome).toBe('held')
    expect(r.countInWindow).toBe(1)
  })

  it('reports no_evidence when nothing landed in the window at all', () => {
    const r = readCycle([a('fractions', 'developing', daysAgo(40))], 'fractions', 28, NOW)
    expect(r.outcome).toBe('no_evidence')
    expect(r.countInWindow).toBe(0)
  })

  it('treats a first-ever assessment inside the window as movement', () => {
    const r = readCycle([a('fractions', 'introduced', daysAgo(2))], 'fractions', 28, NOW)
    expect(r.outcome).toBe('moved')
    expect(r.atWindowStart).toBeNull()
  })
})

describe('what the window must not take away', () => {
  it('never lowers a level a child already reached', () => {
    // Mastery demonstrated ten weeks ago, quiet since. The window may say
    // nothing moved; it must not say the child is no longer there.
    const r = readCycle([a('fractions', 'mastered', daysAgo(70))], 'fractions', 28, NOW)
    expect(r.outcome).toBe('no_evidence')
    expect(r.now).toBe('mastered')
  })

  it('keeps `now` a high-water mark even when recent work scored lower', () => {
    const r = readCycle(
      [a('fractions', 'mastered', daysAgo(40)), a('fractions', 'introduced', daysAgo(2))],
      'fractions', 28, NOW,
    )
    expect(r.now).toBe('mastered')
    expect(r.outcome).toBe('held') // worked in-window, but no rise above mastered
  })

  it('does not let one topic\'s evidence read as another\'s', () => {
    const r = readCycle(
      [a('decimals', 'mastered', daysAgo(1)), a('fractions', 'introduced', daysAgo(40))],
      'fractions', 28, NOW,
    )
    expect(r.outcome).toBe('no_evidence')
    expect(r.now).toBe('introduced')
  })

  it('ignores assessments carrying no level', () => {
    const r = readCycle([a('fractions', null, daysAgo(1))], 'fractions', 28, NOW)
    expect(r.outcome).toBe('no_evidence')
    expect(r.now).toBeNull()
  })

  it('counts an undateable assessment toward the picture but never toward movement', () => {
    const r = readCycle(
      [{ ...a('fractions', 'mastered', daysAgo(1)), assessed_at: 'not a date' } as NarrationAssessmentData],
      'fractions', 28, NOW,
    )
    expect(r.now).toBe('mastered')
    expect(r.outcome).toBe('no_evidence')
  })
})

describe('the window itself', () => {
  it('a wider travel window can surface work a 28-day window misses', () => {
    const evidence = [a('fractions', 'introduced', daysAgo(60)), a('fractions', 'developing', daysAgo(35))]
    expect(readCycle(evidence, 'fractions', 28, NOW).outcome).toBe('no_evidence')
    expect(readCycle(evidence, 'fractions', 42, NOW).outcome).toBe('moved')
  })

  it('includes an assessment sitting exactly on the boundary', () => {
    const r = readCycle([a('fractions', 'introduced', daysAgo(28))], 'fractions', 28, NOW)
    expect(r.countInWindow).toBe(1)
  })
})

describe('describeWindow', () => {
  it('says weeks when the window divides evenly', () => {
    expect(describeWindow(28)).toEqual({ value: 4, unit: 'week' })
    expect(describeWindow(21)).toEqual({ value: 3, unit: 'week' })
    expect(describeWindow(42)).toEqual({ value: 6, unit: 'week' })
  })

  it('does not round an uneven window into weeks', () => {
    expect(describeWindow(25)).toEqual({ value: 25, unit: 'day' })
  })
})
