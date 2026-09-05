/**
 * The demo's reading settings must BE the app's, not a lagging copy.
 *
 * This imports BOTH modules and asserts every rendered value matches, the
 * same technique `endpointing.test.ts` uses and for the same reason: a
 * spacing step that drifted apart would mean the demo was demonstrating
 * something a family would not actually get, on the one surface a
 * prospective family judges Bede by.
 *
 * jsdom evaluates no cascade, so nothing here can see the rendered result.
 * What is checkable is the contract that makes the cascade work — the
 * consuming class exists on the demo's own bubbles and nothing shadows it —
 * which is exactly the defect that shipped in the app (#487) and would have
 * shipped here too, since the demo's bubbles carry `leading-relaxed` in the
 * same place.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

import {
  DEFAULT_LINE_HEIGHT,
  DEFAULT_TIGHT_LINE_HEIGHT,
  LINE_HEIGHT_VAR,
  hasReadingPresentation,
  readingStyle,
  type ReadingPresentation,
} from './readingPresentation'
import {
  DEFAULT_LINE_HEIGHT as APP_DEFAULT_LINE_HEIGHT,
  LINE_HEIGHT_VAR as APP_LINE_HEIGHT_VAR,
  readingStyle as appReadingStyle,
} from '../../homeschool-tutor/src/utils/readingPresentation'

const EVERY_COMBINATION: ReadingPresentation[] = (['normal', 'wide', 'wider'] as const).flatMap((l) =>
  (['normal', 'relaxed', 'loose'] as const).map((n) => ({ letter_spacing: l, line_spacing: n })),
)

describe('the demo renders exactly what the app renders', () => {
  it.each(EVERY_COMBINATION)('matches the app for %o', (config) => {
    expect(readingStyle(config)).toEqual(appReadingStyle(config))
  })

  it('shares the same constants, not equal-looking copies', () => {
    expect(DEFAULT_LINE_HEIGHT).toBe(APP_DEFAULT_LINE_HEIGHT)
    expect(LINE_HEIGHT_VAR).toBe(APP_LINE_HEIGHT_VAR)
  })

  it('emits nothing when the visitor has set nothing', () => {
    // A visitor who never opens the reading panel must get byte-identical
    // markup — the same load-bearing property as the app's own copy.
    expect(readingStyle(undefined)).toEqual({})
    expect(readingStyle({ letter_spacing: 'normal', line_spacing: 'normal' })).toEqual({})
    expect(hasReadingPresentation({})).toBe(false)
  })

  it('carries no font-family — there is deliberately no dyslexia font', () => {
    // Peer-reviewed studies of OpenDyslexic find no improvement in reading
    // rate or accuracy, sometimes worse than Arial, and the International
    // Dyslexia Association's position is that no reliable evidence supports
    // them. See docs/ACCESSIBILITY_RESEARCH.md §4.2.
    expect(readingStyle({ letter_spacing: 'wider', line_spacing: 'loose' }).fontFamily).toBeUndefined()
  })

  it('carries no font size — that is useTextScale\'s job here too', () => {
    // The demo has had TextSizeControl all along, scaling the root font
    // size product-wide. A second, weaker per-visitor font size is exactly
    // what decision register entry 24 removed from the app.
    const style = readingStyle({ letter_spacing: 'wider', line_spacing: 'loose' }) as Record<string, string>
    expect(style.fontSize).toBeUndefined()
  })
})

describe('the settings reach the demo\'s own lesson text', () => {
  const app = readFileSync(join(__dirname, 'App.tsx'), 'utf8')
  const READS = `leading-[var(${LINE_HEIGHT_VAR},${DEFAULT_LINE_HEIGHT})]`
  const READS_TIGHT = `leading-[var(${LINE_HEIGHT_VAR},${DEFAULT_TIGHT_LINE_HEIGHT})]`

  it('gives every lesson-text element the var-backed class', () => {
    // Five, matching the app: Bede's and the child's messages, the tool
    // cards, the live transcript, the transcribing status, and the voice
    // review step.
    const loose = app.split(READS).length - 1
    const tight = app.split(READS_TIGHT).length - 1
    expect(loose + tight, `App.tsx has ${loose + tight} lesson-text elements reading the var; expected 5`).toBe(5)
    expect(tight, 'the three voice bubbles keep their own tighter default').toBe(3)
  })

  it('leaves no bubble carrying a bare leading-* that would shadow the setting', () => {
    const bubbles = app.split('\n').filter((l) => /max-w-\[80%\] rounded-2xl/.test(l))
    expect(bubbles.length, 'no chat bubbles found — this scan has stopped checking anything').toBeGreaterThanOrEqual(4)
    for (const line of bubbles) {
      if (line.includes(READS) || line.includes(READS_TIGHT)) continue
      expect(/\bleading-\w/.test(line), `a demo chat bubble sets its own line height and will shadow the setting:\n  ${line.trim()}`).toBe(false)
    }
  })

  it('applies the setting to <html>, so it works outside the chat too', () => {
    // A first cut applied it inside ChatScreen only, so the spacing rows
    // visibly did nothing on the code and summary screens while the text-size
    // row in the same panel worked. Caught in review. useTextScale already
    // wrote the root font size this way; this follows the sibling that got
    // it right rather than adding a wrapper.
    const hook = readFileSync(join(__dirname, 'useReadingPresentation.ts'), 'utf8')
    expect(hook).toContain('document.documentElement')
    expect(hook).toContain('applyToDocument')
    expect(app).not.toContain('style={readingStyle(')
  })

  it('reaches the demo picture-study caption too', () => {
    const card = readFileSync(join(__dirname, 'VisualAidCard.tsx'), 'utf8')
    expect(card).toContain(READS)
    expect(/\bleading-relaxed\b/.test(card), 'demo VisualAidCard has a bare leading-relaxed again').toBe(false)
  })
})
