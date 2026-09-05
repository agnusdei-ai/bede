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

const LINE: Record<LineSpacing, string> = {
  normal: '1.5',
  relaxed: '1.8',
  loose: '2.1',
}

const SIZE: Record<TextSize, string> = {
  normal: '1rem',
  large: '1.15rem',
  larger: '1.35rem',
}

/**
 * The inline style for a container the lesson text sits inside. Every value
 * is inherited, so one element carries the whole setting rather than every
 * text node needing to know about it.
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

  const style: React.CSSProperties = {}
  if (letter !== LETTER.normal) {
    style.letterSpacing = letter.letterSpacing
    style.wordSpacing = letter.wordSpacing
  }
  if (line !== LINE.normal) style.lineHeight = line
  if (size !== SIZE.normal) style.fontSize = size
  return style
}

/** Whether anything here is set away from default — for tests and for copy
 *  that should only appear when a presentation is actually in effect. */
export function hasReadingPresentation(config: ReadingPresentation | null | undefined): boolean {
  return Object.keys(readingStyle(config)).length > 0
}
