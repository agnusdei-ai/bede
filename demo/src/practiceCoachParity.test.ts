/**
 * The demo's Practice Coach must BE the product's, not a lagging copy of it:
 * the same pure rules, the same gates, the same wording wherever the demo does
 * not have a stated reason to differ. Two copies of one fact with nothing
 * checking they agree is the drift this repository keeps shipping, so this
 * imports BOTH sides (the technique endpointing.test.ts and
 * readingPresentation.test.ts use).
 *
 * Where the demo differs, that is listed here with its reason, so a
 * difference is a decision someone made rather than a copy that fell behind.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

import {
  CONFIDENCE_FLOOR, flaggedCount, isFlagged, MARKS, MAX_PAGES, PRACTICE_ACCEPT, teacherCount, toBase64Payload,
} from './practiceCoachLogic'
import {
  flaggedCount as appFlaggedCount,
  isFlagged as appIsFlagged,
  PRACTICE_ACCEPT as APP_ACCEPT,
  teacherCount as appTeacherCount,
  toBase64Payload as appToBase64Payload,
} from '../../homeschool-tutor/src/components/PracticeCoach'
import demoEn from './i18n/locales/en.json'
import demoEs from './i18n/locales/es.json'
import appEn from '../../homeschool-tutor/src/i18n/locales/en.json'
import appEs from '../../homeschool-tutor/src/i18n/locales/es.json'

const APP_SOURCE = readFileSync(join(__dirname, '../../homeschool-tutor/src/components/PracticeCoach.tsx'), 'utf8')
const DEMO_SOURCE = readFileSync(join(__dirname, 'PracticeCoach.tsx'), 'utf8')

const item = (over: Record<string, unknown> = {}) => ({
  number: 1, prompt: 'p', teacher_mark: 'incorrect' as const, confidence: 1, ask_parent: null, ...over,
})

describe('the pure rules are the product\'s', () => {
  it('reads the same confidence floor', () => {
    expect(APP_SOURCE).toContain(`const CONFIDENCE_FLOOR = ${CONFIDENCE_FLOOR}`)
  })

  it('offers the same marks, in the same order', () => {
    expect(APP_SOURCE).toContain(`const MARKS: TeacherMark[] = [${MARKS.map((m) => `'${m}'`).join(', ')}]`)
  })

  it('accepts exactly the same files', () => {
    expect(PRACTICE_ACCEPT).toBe(APP_ACCEPT)
  })

  it('strips a data URL to base64 the same way', () => {
    for (const raw of ['data:image/png;base64,AAAA', 'data:application/pdf;base64,QQ==', 'BBBB', '']) {
      expect(toBase64Payload(raw)).toBe(appToBase64Payload(raw))
    }
  })

  it('flags, counts flagged, and counts the teacher\'s marks identically', () => {
    const assessment = {
      subject: 'latin',
      sections: [
        { items: [item(), item({ confidence: 0.74 }), item({ confidence: 0.75 }), item({ ask_parent: 'why' })] },
        { items: [item({ teacher_mark: 'correct' }), item({ teacher_mark: 'unmarked', confidence: 0.1 }), item({ teacher_mark: 'partial' })] },
      ],
    }
    expect(flaggedCount(assessment)).toBe(appFlaggedCount(assessment as never))
    expect(teacherCount(assessment)).toEqual(appTeacherCount(assessment as never))
    for (const sec of assessment.sections) {
      for (const it of sec.items) expect(isFlagged(it)).toBe(appIsFlagged(it))
    }
    expect(flaggedCount(assessment)).toBe(3)
  })

  it('differs on the page cap only, which is the demo\'s stated preview limit', () => {
    expect(MAX_PAGES).toBe(3)
    expect(APP_SOURCE).toContain('export const MAX_PAGES = 6')
  })
})

describe('the card keeps the product\'s gates', () => {
  // Each of these is a line the app's card has. If the app drops or renames
  // one, this fails and says which gate the demo is now demonstrating alone.
  it.each([
    ['unsettled readings block planning', 'disabled={remaining > 0 || stage === \'planning\'}'],
    ['"Looks right" settles one flagged answer', 'ask_parent: null, confidence: 1'],
    ['untick before approving', 'plan.practice_set.items.filter((_, i) => keep[i])'],
    ['approve needs at least one ticked item', 'onClick={approve} disabled={!keep.some(Boolean)}'],
  ])('both cards: %s', (_name, snippet) => {
    expect(APP_SOURCE).toContain(snippet)
    expect(DEMO_SOURCE).toContain(snippet)
  })
})

// ── Wording ─────────────────────────────────────────────────────────────

function flatten(obj: Record<string, unknown>, prefix = ''): Record<string, string> {
  return Object.fromEntries(Object.entries(obj).flatMap(([k, v]) => {
    const path = prefix ? `${prefix}.${k}` : k
    return typeof v === 'object' && v !== null ? Object.entries(flatten(v as Record<string, unknown>, path)) : [[path, String(v)]]
  }))
}

/** Keys the demo words differently ON PURPOSE, each with the reason. */
const DEMO_WORDING: Record<string, string> = {
  description: 'a preview: nothing is kept and nothing reaches a child',
  routeCloud: 'no local model; the tick is per upload and names the backup provider',
  routeNone: 'no AI provider is configured, rather than no model on this install',
  privacy: 'the reading and plan are held in memory for the session, by design',
  approved: 'there is no child to deliver to and nothing is saved past the session',
  discarded: 'nothing is kept either way',
  title: 'same words today; listed so a change to either is a decision',
}
/** Keys that only exist in the demo, each with the reason. */
const DEMO_ONLY: Record<string, string> = {
  preview: 'panel heading',
  allowance: 'the per-session read allowance',
}
/** Keys the product has and the demo does not, each with the reason. */
const APP_ONLY: Record<string, string> = {
  routeLocal: 'the demo has no local model',
  recheck: 'the re-check is a promise about later; a session-long preview makes none',
}

describe.each([['en', demoEn, appEn], ['es', demoEs, appEs]] as const)('wording (%s)', (_loc, demo, app) => {
  const d = flatten((demo as { practiceCoach: Record<string, unknown> }).practiceCoach)
  const a = flatten((app as { practiceCoach: Record<string, unknown> }).practiceCoach)

  it('uses the product\'s words for every key it shares, except the listed ones', () => {
    for (const key of Object.keys(a)) {
      if (key in APP_ONLY || key in DEMO_WORDING) continue
      expect(d[key], `demo practiceCoach.${key} drifted from the app's`).toBe(a[key])
    }
  })

  it('has no key the product lacks unless it is listed with a reason', () => {
    for (const key of Object.keys(d)) {
      if (key in a || key in DEMO_ONLY) continue
      throw new Error(`demo-only practiceCoach.${key} has no stated reason`)
    }
  })

  it('omits only what it says it omits', () => {
    for (const key of Object.keys(APP_ONLY)) expect(d[key]).toBeUndefined()
    for (const key of Object.keys(DEMO_ONLY)) expect(d[key]).toBeDefined()
    for (const key of Object.keys(a)) {
      if (!(key in APP_ONLY)) expect(d[key], `demo is missing practiceCoach.${key}`).toBeDefined()
    }
  })
})
