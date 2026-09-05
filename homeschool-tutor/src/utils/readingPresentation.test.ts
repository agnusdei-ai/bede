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
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  readingStyle,
  hasReadingPresentation,
  DEFAULT_TEXT_SIZE,
  DEFAULT_LINE_HEIGHT,
  TEXT_SIZE_VAR,
  LINE_HEIGHT_VAR,
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


// ── Reaching the text a child actually reads ─────────────────────────────
//
// The defect these guard against SHIPPED, and every test in the block above
// passed while it was live. `readingStyle` returned the right object and the
// right object was applied to <main> — and the lesson text carried
// `text-sm leading-relaxed`, which set font-size and line-height ON THE
// ELEMENT, and a property set on an element always beats one inherited from
// an ancestor. Measured in real Chromium: <main> at 21.6px/45.36px, the chat
// bubble rendering every word of the lesson at 16.1px/26.16px. Two of the
// four settings were reaching the surrounding chrome and nothing else.
//
// jsdom evaluates no cascade, so no test in this file can see the rendered
// result. What IS checkable is the contract that makes the cascade work, and
// that is what these assert: the consuming classes exist, they carry the
// right fallbacks, and nothing shadows them.
describe('the settings reach the lesson text, not just its container', () => {
  const chat = readFileSync(join(__dirname, '../components/SocraticChat.tsx'), 'utf8')

  // Every element that renders words a child reads. Chrome labels ("Bede",
  // the student's name) and buttons are deliberately not here.
  const READS = 'text-[length:var(--bede-text-size,1.00625rem)] leading-[var(--bede-line-height,1.625)]'

  it('emits the custom properties, not only the inherited ones', () => {
    // The inherited pair is kept for anything that genuinely does inherit
    // (break cards, MeetBede). The vars are what the lesson text reads. Both,
    // never one — dropping the vars is exactly the shipped defect.
    const style = readingStyle({ text_size: 'larger', line_spacing: 'loose' }) as Record<string, string>
    expect(style[TEXT_SIZE_VAR]).toBe('1.35rem')
    expect(style[LINE_HEIGHT_VAR]).toBe('2.2')
    expect(style.fontSize).toBe('1.35rem')
    expect(style.lineHeight).toBe('2.2')
  })

  it('still emits nothing at all when no setting is on', () => {
    // Including the vars — a var set to its own fallback is harmless but a
    // var set to a WRONG value would silently change every family's text.
    expect(readingStyle({})).toEqual({})
  })

  it('gives every lesson-text element the var-backed classes', () => {
    // Five: Bede's and the child's messages, the tool cards (hints,
    // celebrations, faith reflections), the live transcript, the "Transcribing…"
    // status, and the voice review step the child reads back before sending.
    // The status bubble is here because it sits in the same stream — one
    // bubble staying small while the rest grow reads as a rendering bug.
    const uses = chat.split(READS).length - 1
    expect(uses, `SocraticChat.tsx has ${uses} lesson-text elements reading the reading-presentation vars; expected 5`).toBe(5)
  })

  it('leaves no lesson-text element carrying a bare text-sm that would shadow the setting', () => {
    // The specific regression. A `text-sm` on a bubble looks harmless in
    // review and silently disables two of the four settings for every child.
    const bubbles = chat.split('\n').filter((l) => /max-w-\[80%\] rounded-2xl/.test(l))
    expect(bubbles.length, 'no chat bubbles found — this scan has stopped checking anything').toBeGreaterThanOrEqual(4)
    for (const line of bubbles) {
      if (/text-\[length:var\(--bede-text-size/.test(line)) continue
      expect(/\btext-(xs|sm|base|lg|xl)\b/.test(line), `a chat bubble sets its own font size and will shadow the reading-presentation setting:\n  ${line.trim()}`).toBe(false)
      expect(/\bleading-\w/.test(line), `a chat bubble sets its own line height and will shadow the reading-presentation setting:\n  ${line.trim()}`).toBe(false)
    }
  })

  it('uses fallbacks equal to what those classes used to compile to', () => {
    // Two copies of one number: the literal in the class name (Tailwind's
    // scanner needs a literal) and this project's own `text-sm`. If they
    // drift, a family with NO setting gets their text silently resized —
    // the quietest possible way to break the "nothing changes by default"
    // promise. Read from tailwind.config.js rather than restated.
    const config = readFileSync(join(__dirname, '../../tailwind.config.js'), 'utf8')
    const sm = config.match(/^\s*sm:\s*\['([^']+)'/m)
    expect(sm, "could not read text-sm out of tailwind.config.js").toBeTruthy()
    expect(DEFAULT_TEXT_SIZE).toBe(sm![1])
    expect(READS).toContain(DEFAULT_TEXT_SIZE)
    // leading-relaxed is Tailwind's own default and wins over text-sm's own
    // line height, which is what the bubbles rendered at before this.
    expect(DEFAULT_LINE_HEIGHT).toBe('1.625')
    expect(READS).toContain(DEFAULT_LINE_HEIGHT)
  })
})
