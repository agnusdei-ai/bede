import { useCallback, useEffect, useState } from 'react'

import { LINE_HEIGHT_VAR, readingStyle, type LetterSpacing, type LineSpacing, type ReadingPresentation } from './readingPresentation'

/**
 * The demo's owner for the reading-presentation settings.
 *
 * The app takes these from `SessionConfig`: a parent sets them per student
 * and they follow the child to whatever tablet they sit at. The demo has no
 * parent and no student — a visitor types a name at a code screen — so here
 * they are a per-device preference the visitor sets themselves, held in
 * localStorage exactly as `useTextScale` and `useChatTheme` already are.
 *
 * Same rendering, different owner, because the demo has nobody else to be
 * the owner. That is the one deliberate divergence from the app; the values
 * themselves are asserted identical by `readingPresentation.test.ts`.
 *
 * Two keys rather than one blob, matching the convention already here
 * (`bede-chat-theme` and `bede-bubble-color` are separate): a malformed blob
 * would lose both settings, and each of these is independently useful.
 * Both are named on `site/privacy/index.html` and pinned by
 * `privacyInventory.test.ts` — that page promises an inventory with "no
 * rounding up", so a key without a row makes a public claim false.
 *
 * DELIBERATELY NOT CLEARED ON LOGOUT, unlike the chat and the drawing page.
 * Those are session content; this is an accessibility preference for the
 * DEVICE, and a reader who needs wider letter spacing to read comfortably
 * needs it on their next visit too — dropping it would be actively hostile
 * to the one visitor it exists for. That matches every sibling preference
 * here: `bede-demo-text-scale`, `bede-voice-mode` and the chat theme all
 * survive logout, and the privacy page states "indefinite, until cleared"
 * for each.
 */

const LETTER_KEY = 'bede-demo-letter-spacing'
const LINE_KEY = 'bede-demo-line-spacing'

/** Instances sync through a window event, same pattern as useChatTheme. */
const CHANGE_EVENT = 'bede-reading-presentation-change'

/**
 * Applied to <html>, not to a container inside the chat.
 *
 * The control is mounted globally (main.tsx), so a visitor can open it on the
 * code screen or the summary screen — and a first cut applied the style only
 * inside ChatScreen, which meant the two spacing rows visibly did nothing
 * there while the text-size row in the same panel worked. Caught in review.
 *
 * `useTextScale` already writes the root font size the same way, so this
 * follows the sibling that got it right rather than inventing a wrapper.
 */
function applyToDocument(presentation: ReadingPresentation) {
  if (typeof document === 'undefined') return
  const style = readingStyle(presentation) as Record<string, string>
  const root = document.documentElement
  root.style.letterSpacing = style.letterSpacing ?? ''
  root.style.wordSpacing = style.wordSpacing ?? ''
  root.style.lineHeight = style.lineHeight ?? ''
  root.style.setProperty(LINE_HEIGHT_VAR, style[LINE_HEIGHT_VAR] ?? null)
}

const LETTER_VALUES: readonly LetterSpacing[] = ['normal', 'wide', 'wider']
const LINE_VALUES: readonly LineSpacing[] = ['normal', 'relaxed', 'loose']

function read<T extends string>(key: string, allowed: readonly T[]): T {
  try {
    const raw = localStorage.getItem(key)
    return allowed.includes(raw as T) ? (raw as T) : allowed[0]
  } catch {
    // Private browsing, quota, a locked-down webview. A reading preference
    // that cannot be stored is a smaller problem than a chat that will not
    // render, so this falls back rather than throwing.
    return allowed[0]
  }
}

export function readStoredPresentation(): ReadingPresentation {
  return {
    letter_spacing: read(LETTER_KEY, LETTER_VALUES),
    line_spacing: read(LINE_KEY, LINE_VALUES),
  }
}

// Applied once, eagerly, at module load — before any component mounts —
// avoiding a visible flash of default spacing on first paint, the same
// reasoning useTextScale states for its own eager call.
if (typeof document !== 'undefined') {
  applyToDocument(readStoredPresentation())
}

export function useReadingPresentation() {
  const [presentation, setPresentation] = useState<ReadingPresentation>(readStoredPresentation)

  useEffect(() => {
    applyToDocument(presentation)
  }, [presentation])

  useEffect(() => {
    const sync = () => setPresentation(readStoredPresentation())
    window.addEventListener(CHANGE_EVENT, sync)
    return () => window.removeEventListener(CHANGE_EVENT, sync)
  }, [])

  const write = useCallback((key: string, value: string) => {
    try {
      localStorage.setItem(key, value)
    } catch {
      // Best-effort, as above — the in-memory state below still updates, so
      // the setting works for this session even when it cannot be saved.
    }
    window.dispatchEvent(new Event(CHANGE_EVENT))
    setPresentation(readStoredPresentation())
  }, [])

  const setLetterSpacing = useCallback((v: LetterSpacing) => write(LETTER_KEY, v), [write])
  const setLineSpacing = useCallback((v: LineSpacing) => write(LINE_KEY, v), [write])


  return { presentation, setLetterSpacing, setLineSpacing }
}

export const READING_PRESENTATION_KEYS = [LETTER_KEY, LINE_KEY] as const
