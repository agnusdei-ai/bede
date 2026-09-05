/**
 * Guards for the reading-presentation settings — the half of a learning
 * accommodation that `SessionConfig.learning_support` structurally could not
 * reach, because that field goes to the prompt and changes only what Bede
 * SAYS.
 *
 * Three properties carry the design, and each is here because it can regress
 * silently. A style object is not something anyone eyeballs in review, and
 * every failure mode below renders a page that looks broadly fine.
 */
import { describe, it, expect } from 'vitest'
import {
  readingStyle,
  hasReadingPresentation,
  type ReadingPresentation,
} from './readingPresentation'

describe('readingStyle', () => {
  it('emits NOTHING when every setting is default', () => {
    // The load-bearing one. A family who never opens this panel must get
    // byte-for-byte today's markup — an inline style that always renders
    // would silently take over from the stylesheet for every student in
    // every deployment, and a specificity bug there is invisible until a
    // parent reports that the chat "looks different" with no setting changed.
    expect(readingStyle(undefined)).toEqual({})
    expect(readingStyle(null)).toEqual({})
    expect(readingStyle({})).toEqual({})
    expect(
      readingStyle({ letter_spacing: 'normal', line_spacing: 'normal', text_size: 'normal' }),
    ).toEqual({})
    expect(hasReadingPresentation({ letter_spacing: 'normal' })).toBe(false)
  })

  it('sets word spacing whenever it sets letter spacing, and never one alone', () => {
    // Widening letters without widening words erodes the gap that marks where
    // a word ends: the reader gains within-word clarity and loses word
    // boundaries, which for a child still assembling words is a worse trade
    // than leaving it alone. They are one setting for that reason, so a diff
    // that "tidies up" the pair into a single property is a real regression
    // rather than a simplification.
    for (const value of ['wide', 'wider'] as const) {
      const style = readingStyle({ letter_spacing: value })
      expect(style.letterSpacing, `${value} set no letter spacing`).toBeTruthy()
      expect(style.wordSpacing, `${value} set no word spacing`).toBeTruthy()
    }
    // ...and the inverse: nothing else may set either one on its own.
    for (const config of [
      { line_spacing: 'relaxed' }, { line_spacing: 'loose' },
      { text_size: 'large' }, { text_size: 'larger' },
    ] as ReadingPresentation[]) {
      const style = readingStyle(config)
      expect(style.letterSpacing).toBeUndefined()
      expect(style.wordSpacing).toBeUndefined()
    }
  })

  it('makes each step actually larger than the one below it', () => {
    // A picker whose second option renders identically to its first is worse
    // than a picker with one option: a parent tries "wider", sees no change,
    // and concludes the accommodation does not work.
    const em = (v: unknown) => parseFloat(String(v ?? '0'))
    expect(em(readingStyle({ letter_spacing: 'wider' }).letterSpacing))
      .toBeGreaterThan(em(readingStyle({ letter_spacing: 'wide' }).letterSpacing))
    expect(em(readingStyle({ letter_spacing: 'wider' }).wordSpacing))
      .toBeGreaterThan(em(readingStyle({ letter_spacing: 'wide' }).wordSpacing))
    expect(Number(readingStyle({ line_spacing: 'loose' }).lineHeight))
      .toBeGreaterThan(Number(readingStyle({ line_spacing: 'relaxed' }).lineHeight))
    expect(em(readingStyle({ text_size: 'larger' }).fontSize))
      .toBeGreaterThan(em(readingStyle({ text_size: 'large' }).fontSize))
  })

  it('keeps word spacing ahead of letter spacing at every step', () => {
    // The reason the pair exists at all: if word spacing ever fell to or
    // below letter spacing, the boundary between two words would read as no
    // wider than the boundary between two letters, which is the exact
    // failure widening letters alone produces.
    for (const value of ['wide', 'wider'] as const) {
      const style = readingStyle({ letter_spacing: value })
      expect(parseFloat(String(style.wordSpacing)))
        .toBeGreaterThan(parseFloat(String(style.letterSpacing)))
    }
  })

  it('uses relative units throughout, so a text-size choice still scales everything', () => {
    // Letter and word spacing are in `em` and line height is unitless, so
    // they are all relative to the font size in effect. Pinning any of them
    // to `px` would make a "larger" text choice widen the glyphs and leave
    // the gaps between them where they were — proportionally tighter than
    // the default the parent started from, i.e. the opposite of the ask.
    const style = readingStyle({ letter_spacing: 'wider', line_spacing: 'loose', text_size: 'larger' })
    expect(String(style.letterSpacing)).toMatch(/em$/)
    expect(String(style.wordSpacing)).toMatch(/em$/)
    expect(String(style.fontSize)).toMatch(/rem$/)
    expect(String(style.lineHeight)).not.toMatch(/[a-z]/)
  })

  it('falls back to normal rather than throwing on a value it does not know', () => {
    // These arrive from a stored config a parent may have saved under an
    // older version, or from a hand-edited one. A lesson must never fail to
    // render over a presentation preference.
    const bogus = { letter_spacing: 'enormous', line_spacing: 7, text_size: null } as unknown
    expect(() => readingStyle(bogus as ReadingPresentation)).not.toThrow()
    expect(readingStyle(bogus as ReadingPresentation)).toEqual({})
  })

  it('reports that a presentation is in effect exactly when one is', () => {
    expect(hasReadingPresentation({ letter_spacing: 'wide' })).toBe(true)
    expect(hasReadingPresentation({ line_spacing: 'relaxed' })).toBe(true)
    expect(hasReadingPresentation({ text_size: 'large' })).toBe(true)
    expect(hasReadingPresentation(undefined)).toBe(false)
  })

  it('carries no font-family setting — there is deliberately no dyslexia font', () => {
    // The most-requested accommodation in this space, and the one that does
    // not work: peer-reviewed studies of OpenDyslexic and Dyslexie find no
    // improvement in reading rate or accuracy, sometimes performing worse
    // than Arial, and the International Dyslexia Association's own position
    // is that no reliable evidence supports them. See
    // docs/ACCESSIBILITY_RESEARCH.md. If someone adds one, this fails and
    // they have to read why rather than shipping it on request.
    const style = readingStyle({ letter_spacing: 'wider', line_spacing: 'loose', text_size: 'larger' })
    expect(style.fontFamily).toBeUndefined()
  })
})
