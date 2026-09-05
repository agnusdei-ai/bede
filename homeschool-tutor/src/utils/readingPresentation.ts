/**
 * How the text itself is presented, for a child whose obstacle is reading the
 * screen rather than understanding the lesson.
 *
 * WHY THIS EXISTS SEPARATELY FROM useChatTheme
 *
 * `useChatTheme` holds the CHILD's own background and bubble colours: chosen
 * by them, for fun, in localStorage, per-device. These are the PARENT's
 * settings, per-student, and they travel with the child to whatever tablet
 * they sit at — a reading accommodation that only worked on one device would
 * be worse than none, because it would fail silently at exactly the moment
 * someone changed rooms.
 *
 * WHY THIS EXISTS AT ALL
 *
 * `SessionConfig.learning_support` reaches the PROMPT and nothing else. It
 * changes what Bede SAYS. It cannot change what the screen looks like, so a
 * parent who typed "bigger text with more space between the letters" got
 * nothing — Bede might mention it, and the app rendered identically.
 *
 * WHAT THE EVIDENCE ACTUALLY SUPPORTS — see docs/ACCESSIBILITY_RESEARCH.md,
 * because the three settings here are NOT equally well founded and saying so
 * is the difference between an accommodation and folklore:
 *
 *   - letterSpacing is the strong one. Zorzi et al. (2012, PNAS) found extra
 *     letter spacing doubled accuracy and raised reading speed over 20% in
 *     dyslexic 8-14 year olds, replicated across two languages.
 *   - lineSpacing rests on general readability guidance, not a measured
 *     effect for this population. Weaker, and labelled weaker.
 *   - textSize is offered as a PREFERENCE and is never described to a parent
 *     as an accommodation: bigger is not reliably better, and the direction
 *     reverses with age (Katzir et al. 2013).
 *
 * There is deliberately NO dyslexia-specific font here. Peer-reviewed studies
 * of OpenDyslexic and Dyslexie find no improvement in reading rate or
 * accuracy, sometimes performing worse than Arial, and the International
 * Dyslexia Association's position is that no reliable evidence supports them.
 * Shipping one as the headline feature would be shipping the most-requested
 * thing that does not work.
 */

export type LetterSpacing = 'normal' | 'wide' | 'wider'
export type LineSpacing = 'normal' | 'relaxed' | 'loose'
export type TextSize = 'normal' | 'large' | 'larger'

export interface ReadingPresentation {
  letter_spacing?: LetterSpacing
  line_spacing?: LineSpacing
  text_size?: TextSize
}

/**
 * The value each var falls back to when no setting is in effect — which is
 * exactly what `text-sm leading-relaxed` (the lesson text's own classes)
 * compiles to in THIS project's scale. They are written literally into the
 * arbitrary-value class names too, because Tailwind's scanner needs a literal
 * string; `readingPresentation.test.ts` reads tailwind.config.js and fails if
 * these stop matching, since two copies of one number is the drift this repo
 * checks rather than trusts.
 */
export const DEFAULT_TEXT_SIZE = '1.00625rem'
export const DEFAULT_LINE_HEIGHT = '1.625'

/** The custom properties the lesson text's own classes read. Named here so a
 *  call site cannot misspell one silently — a typo'd var just falls back and
 *  the setting appears to do nothing. */
export const TEXT_SIZE_VAR = '--bede-text-size'
export const LINE_HEIGHT_VAR = '--bede-line-height'

/**
 * Letter spacing carries word spacing with it, deliberately, as one setting.
 *
 * Pushing letters apart without pushing words apart erodes the gap that marks
 * where one word ends — the reader gains within-word clarity and loses word
 * boundaries, which for a child still assembling words is a poor trade. They
 * move together because they have to; two separate knobs would let a parent
 * reach the bad combination by accident.
 */
const LETTER: Record<LetterSpacing, { letterSpacing: string; wordSpacing: string }> = {
  normal: { letterSpacing: '0em', wordSpacing: '0em' },
  wide: { letterSpacing: '0.06em', wordSpacing: '0.16em' },
  wider: { letterSpacing: '0.12em', wordSpacing: '0.32em' },
}

// Anchored on what the lesson text ACTUALLY renders at, not on a round
// number: `leading-relaxed` is 1.625, so a map claiming `normal` is 1.5 would
// describe a page nobody has. `normal` is the constant itself rather than a
// copy of it, so the two cannot drift. The steps above it are ~17% and ~35%,
// matching the text-size steps' own proportions.
const LINE: Record<LineSpacing, string> = {
  normal: DEFAULT_LINE_HEIGHT,
  relaxed: '1.9',
  loose: '2.2',
}

// Sized against this project's OWN scale, not stock Tailwind's. `text-sm`
// here is 1.00625rem (tailwind.config.js overrides the whole ramp), which is
// what the lesson text renders at today — so `normal` is that constant by
// reference, not a round 1rem, or "no change" would in fact be a small
// shrink. `large` is exactly `text-base`; `larger` sits between `lg` and
// `xl`.
const SIZE: Record<TextSize, string> = {
  normal: DEFAULT_TEXT_SIZE,
  large: '1.15rem',
  larger: '1.35rem',
}

/**
 * The inline style for a container the lesson text sits inside.
 *
 * WHY TWO MECHANISMS, AND WHY THE SECOND ONE IS NOT OPTIONAL
 *
 * `letterSpacing`/`wordSpacing` are plain inherited properties and that is
 * enough: nothing downstream sets them, so a value here reaches the text.
 *
 * `fontSize`/`lineHeight` are inherited too, and inheritance LOSES — the
 * lesson text carries `text-sm leading-relaxed`, which set both properties on
 * the element itself, and a property set on an element always beats one
 * inherited from an ancestor no matter how specific the ancestor's rule is.
 * Measured in real Chromium before this was fixed: <main> at 21.6px/45.36px,
 * the chat bubble that renders every word of the lesson at 16.1px/26.16px.
 * The two weaker settings were reaching the surrounding chrome and nothing a
 * child actually reads.
 *
 * So those two ALSO travel as custom properties, which the text's own classes
 * read (`text-[length:var(--bede-text-size,…)]`). A custom property set on an
 * ancestor is inherited, and the class that consumes it is on the element
 * itself, so the setting now wins where it has to. The direct properties are
 * kept alongside for anything that genuinely does inherit (break cards,
 * MeetBede), which is why both are emitted rather than one replacing the
 * other. jsdom evaluates no cascade, so only a real browser can catch this
 * class of failure — see the test file's own note.
 *
 * An unset or unrecognised value falls back to `normal` rather than throwing:
 * these arrive from a stored config a parent may have saved under an older
 * version, and a lesson must never fail to render over a presentation
 * preference. Returns an EMPTY object when everything is `normal`, so a
 * family who never touches this gets byte-for-byte today's markup.
 */
export function readingStyle(config: ReadingPresentation | null | undefined): React.CSSProperties {
  const letter = LETTER[config?.letter_spacing as LetterSpacing] ?? LETTER.normal
  const line = LINE[config?.line_spacing as LineSpacing] ?? LINE.normal
  const size = SIZE[config?.text_size as TextSize] ?? SIZE.normal

  const style: Record<string, string> = {}
  if (letter !== LETTER.normal) {
    style.letterSpacing = letter.letterSpacing
    style.wordSpacing = letter.wordSpacing
  }
  if (line !== LINE.normal) {
    style.lineHeight = line
    style[LINE_HEIGHT_VAR] = line
  }
  if (size !== SIZE.normal) {
    style.fontSize = size
    style[TEXT_SIZE_VAR] = size
  }
  return style as React.CSSProperties
}

/** Whether anything here is set away from default — for tests and for copy
 *  that should only appear when a presentation is actually in effect. */
export function hasReadingPresentation(config: ReadingPresentation | null | undefined): boolean {
  return Object.keys(readingStyle(config)).length > 0
}
