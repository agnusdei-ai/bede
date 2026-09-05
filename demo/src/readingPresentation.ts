/**
 * MIRRORED from homeschool-tutor/src/utils/readingPresentation.ts — same
 * reasoning as demo/src/endpointing.ts, holdGesture.ts and
 * canvasPersistence.ts. The demo is the surface a prospective family judges
 * Bede by, so a reading accommodation the product has and the demo does not
 * makes the demo look worse than the thing it is selling. A parent of a
 * dyslexic child evaluating Bede here would have found nothing.
 *
 * `readingPresentation.test.ts` imports BOTH copies and asserts every value
 * matches, so a spacing step that drifted apart would mean the demo was
 * demonstrating something a family would not actually get.
 *
 * ONE VALUE NECESSARILY DIFFERS, and it is not a drift: the demo's chat
 * bubbles carry `text-base` where the app's carry `text-sm`, so its own
 * `leading-relaxed` fallback resolves against a different font size. The line
 * heights here are unitless multipliers, so the numbers are in fact identical
 * — the difference is only in what the class fallback is written beside. The
 * parity test asserts the maps match and does not require the surrounding
 * markup to.
 *
 * WHERE THE PARENT-SET VERSION BECOMES A VISITOR-SET ONE
 *
 * The app takes these from `SessionConfig` — a parent sets them per student
 * and they follow the child to any tablet. The demo has no parent and no
 * student: a visitor types a name at a code screen. So here they are a
 * per-device preference the visitor sets themselves, held in localStorage by
 * `useReadingPresentation.ts` and offered by `TextSizeControl.tsx`, exactly as
 * `useTextScale`/`useChatTheme` already are. Same rendering, different owner,
 * because the demo has nobody else to be the owner.
 */

export type LetterSpacing = 'normal' | 'wide' | 'wider'
export type LineSpacing = 'normal' | 'relaxed' | 'loose'

export interface ReadingPresentation {
  letter_spacing?: LetterSpacing
  line_spacing?: LineSpacing
}

/**
 * What `leading-relaxed` — the lesson text's own class — compiles to, and so
 * what the var falls back to when no setting is in effect. Written literally
 * into the arbitrary-value class name too, because Tailwind's scanner needs a
 * literal string; `readingPresentation.test.ts` fails if the two stop
 * matching, since two copies of one number is the drift this repo checks
 * rather than trusts. Identical to the app's: it is a unitless multiplier, so
 * the demo's larger `text-base` bubbles resolve it correctly without change.
 */
export const DEFAULT_LINE_HEIGHT = '1.625'

/**
 * The OTHER default, for elements that carried no `leading-*` at all and so
 * took `text-sm`'s own built-in line height. Giving those the 1.625 fallback
 * above would silently change their rendering by ~14% for every family who
 * has set nothing — which is exactly the "byte-identical by default" property
 * the rest of this module is built to keep, so a second constant is cheaper
 * than a broken promise. Caught in review of #487, not by a test: every guard
 * here scanned the message bubbles and none of them looked at these three.
 */
export const DEFAULT_TIGHT_LINE_HEIGHT = '1.4375rem'

/** The custom property the lesson text's own class reads. Named here so a
 *  call site cannot misspell it silently — a typo'd var just falls back and
 *  the setting appears to do nothing. */
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



/**
 * The inline style for a container the lesson text sits inside.
 *
 * WHY TWO MECHANISMS, AND WHY THE SECOND ONE IS NOT OPTIONAL
 *
 * `letterSpacing`/`wordSpacing` are plain inherited properties and that is
 * enough: nothing downstream sets them, so a value here reaches the text.
 *
 * `lineHeight` is inherited too, and inheritance LOSES — the lesson text
 * carries `leading-relaxed`, which sets the property on the element itself,
 * and a property set on an element always beats one inherited from an
 * ancestor no matter how specific the ancestor's rule is. Measured in real
 * Chromium before this was fixed: <main> at 45.36px, the chat bubble that
 * renders every word of the lesson at 26.16px. The setting was reaching the
 * surrounding chrome and nothing a child actually reads.
 *
 * So it ALSO travels as a custom property, which the text's own class reads
 * (`leading-[var(--bede-line-height,…)]`). A custom property set on an
 * ancestor is inherited, and the class that consumes it is on the element
 * itself, so the setting now wins where it has to. The direct property is
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

  const style: Record<string, string> = {}
  if (letter !== LETTER.normal) {
    style.letterSpacing = letter.letterSpacing
    style.wordSpacing = letter.wordSpacing
  }
  if (line !== LINE.normal) {
    style.lineHeight = line
    style[LINE_HEIGHT_VAR] = line
  }
  return style as React.CSSProperties
}

/** Whether anything here is set away from default — for tests and for copy
 *  that should only appear when a presentation is actually in effect. */
export function hasReadingPresentation(config: ReadingPresentation | null | undefined): boolean {
  return Object.keys(readingStyle(config)).length > 0
}
