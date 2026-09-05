import { useCallback, useEffect, useState } from 'react'

import type {
  LetterSpacing,
  LineSpacing,
  ReadingPresentation,
} from '../utils/readingPresentation'

/**
 * Puts the reading settings within the READER's reach, without taking them
 * away from the parent.
 *
 * ## Why this exists
 *
 * `letter_spacing` and `line_spacing` were parent-set and per-student, which
 * is the right OWNER — `docs/ACCESSIBILITY_RESEARCH.md` §4.1 makes letter
 * spacing the best-supported thing in this whole area, and an accommodation
 * belongs to the person who decided the child needs it. But it left the
 * consequence inverted: text size, whose evidence is contested and whose
 * direction REVERSES with age (§4.4), was one tap away on every screen, while
 * the setting that actually works could only be changed by leaving the
 * lesson, opening Parent Setup, editing a `<select>` and saving the pod.
 *
 * A child mid-passage cannot do that, and a parent sitting beside them will
 * not. An accommodation that is out of reach at the moment it is needed is
 * not much of an accommodation.
 *
 * ## The rule
 *
 * The parent's per-student value is the STARTING POINT, and the child may
 * move it on the device in front of them. Two properties make that safe:
 *
 *   1. **The child's change is per-device**, like `useChatTheme`'s colours and
 *      `useTextScale`'s size. It never writes back to `StudentConfig`, so a
 *      child cannot silently undo what a parent decided for every device.
 *   2. **A parent who changes their mind wins.** Each stored override records
 *      the parent value it was made AGAINST. When the parent's current value
 *      differs from that, the override is stale and is ignored — a parent
 *      retyping the setting is read as a deliberate redirect, not an
 *      oversight, exactly as `_build_static_prompt`'s rule 9 already treats a
 *      parent's own `current_unit` against a stored bookmark.
 *
 * So the child can always reach it, and the parent always has the last word.
 *
 * ## Deliberately not gated on `appearance_locked`
 *
 * That flag hides the theme/bubble picker in a child session, so a child
 * cannot spend the lesson choosing colours. This is not that. Colours are a
 * preference; spacing is the accommodation, and locking a child out of the
 * one setting that measurably helps them read — in the name of stopping them
 * fiddling — would be the wrong trade in a product whose constitution puts
 * "the full dignity, privacy, safety and developmental needs of every child"
 * above tidiness. If a parent wants a particular value enforced, they set it,
 * and any change they make overrides the child's per rule 2 above.
 *
 * ## Storage
 *
 * One key per student per device. A blob rather than the demo's two flat keys
 * because the override and the seed it was made against are one indivisible
 * fact — storing them apart would let them drift into a state that means
 * nothing. The demo's stated objection to blobs (a malformed one loses both
 * settings) is answered by validating each field independently and by the
 * fallback direction: anything unreadable falls back to the PARENT's value,
 * which is the more authoritative of the two anyway.
 */

const KEY_PREFIX = 'bede-reading:'

/** Instances sync through a window event, same pattern as useChatTheme. */
const CHANGE_EVENT = 'bede-reading-presentation-change'

const LETTER_VALUES: readonly LetterSpacing[] = ['normal', 'wide', 'wider']
const LINE_VALUES: readonly LineSpacing[] = ['normal', 'relaxed', 'loose']

interface StoredOverride {
  /** The child's chosen value. */
  letter?: LetterSpacing
  /** The parent value `letter` was chosen against. */
  letterSeed?: LetterSpacing
  line?: LineSpacing
  lineSeed?: LineSpacing
}

function storageKey(studentName: string): string {
  return `${KEY_PREFIX}${studentName}`
}

function valid<T extends string>(raw: unknown, allowed: readonly T[]): T | undefined {
  return typeof raw === 'string' && allowed.includes(raw as T) ? (raw as T) : undefined
}

function readOverride(studentName: string | null | undefined): StoredOverride {
  if (!studentName) return {}
  try {
    const raw = localStorage.getItem(storageKey(studentName))
    if (!raw) return {}
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return {}
    const o = parsed as Record<string, unknown>
    // Field by field, so one bad value cannot cost the other setting.
    return {
      letter: valid(o.letter, LETTER_VALUES),
      letterSeed: valid(o.letterSeed, LETTER_VALUES),
      line: valid(o.line, LINE_VALUES),
      lineSeed: valid(o.lineSeed, LINE_VALUES),
    }
  } catch {
    // Private browsing, quota, a locked-down webview, or hand-edited JSON.
    // Falling back to the parent's value is the safe direction.
    return {}
  }
}

/** What the parent set for this student, defaults filled in. */
function parentValues(config: ReadingPresentation | null | undefined): Required<ReadingPresentation> {
  return {
    letter_spacing: valid(config?.letter_spacing, LETTER_VALUES) ?? 'normal',
    line_spacing: valid(config?.line_spacing, LINE_VALUES) ?? 'normal',
  }
}

/**
 * The value actually in force: the child's override while it was made against
 * what the parent currently says, otherwise the parent's own value.
 *
 * Exported for the tests, which is the only way to pin the precedence rule
 * without driving a component.
 */
export function resolvePresentation(
  config: ReadingPresentation | null | undefined,
  stored: StoredOverride,
): Required<ReadingPresentation> {
  const parent = parentValues(config)
  return {
    letter_spacing:
      stored.letter && stored.letterSeed === parent.letter_spacing
        ? stored.letter
        : parent.letter_spacing,
    line_spacing:
      stored.line && stored.lineSeed === parent.line_spacing ? stored.line : parent.line_spacing,
  }
}

export function useReadingPresentation(
  config: ReadingPresentation | null | undefined,
  studentName: string | null | undefined,
) {
  const [stored, setStored] = useState<StoredOverride>(() => readOverride(studentName))

  useEffect(() => {
    setStored(readOverride(studentName))
  }, [studentName])

  useEffect(() => {
    const sync = () => setStored(readOverride(studentName))
    window.addEventListener(CHANGE_EVENT, sync)
    return () => window.removeEventListener(CHANGE_EVENT, sync)
  }, [studentName])

  const presentation = resolvePresentation(config, stored)

  const write = useCallback(
    (patch: StoredOverride) => {
      if (!studentName) return
      const next = { ...readOverride(studentName), ...patch }
      try {
        localStorage.setItem(storageKey(studentName), JSON.stringify(next))
      } catch {
        // Best-effort. The in-memory state below still updates, so the
        // setting works for this session even when it cannot be saved.
      }
      setStored(next)
      window.dispatchEvent(new Event(CHANGE_EVENT))
    },
    [studentName],
  )

  // The seed is the PARENT's current value, never the effective one. Seeding
  // against the effective value would mean a child's second change re-seeded
  // against their own first, and the parent's later edit would then never
  // take — the override would outlive the decision it was made under.
  const parent = parentValues(config)
  const setLetterSpacing = useCallback(
    (v: LetterSpacing) => write({ letter: v, letterSeed: parent.letter_spacing }),
    [write, parent.letter_spacing],
  )
  const setLineSpacing = useCallback(
    (v: LineSpacing) => write({ line: v, lineSeed: parent.line_spacing }),
    [write, parent.line_spacing],
  )

  return { presentation, setLetterSpacing, setLineSpacing }
}

export const READING_PRESENTATION_KEY_PREFIX = KEY_PREFIX
