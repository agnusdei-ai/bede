import { useCallback, useEffect, useState } from 'react'

/**
 * Selectable chat-background theme, persisted the same way as the text-size
 * preference (see useTextScale.ts): straight to localStorage, independent of
 * the auth-scoped session store, so it survives logins/logouts on a shared
 * family tablet and each device keeps the look its reader chose.
 *
 * Every theme is nature-drawn and stays light — Bede's chat bubbles, tool
 * cards, and the white speaking surfaces sit on top of these, so the range
 * is "which corner of creation," not light-vs-dark. The gradient class
 * strings are complete literals (never assembled at runtime) so Tailwind's
 * scanner sees and generates them. Mirrored in demo/src/useChatTheme.ts.
 */

export interface ChatTheme {
  id: string
  name: string
  bgClass: string
}

export interface BubbleColor {
  id: string
  name: string
  className: string
}

// The reader's own bubble color — picked for contrast against whichever
// background theme is active. All are deep nature tones (no black) that
// keep the bubble's white text comfortably above WCAG AA contrast; the
// arbitrary-value classes are complete literals so Tailwind generates them.
export const BUBBLE_COLORS: BubbleColor[] = [
  // The default — the leaf-green the learner bubble always used.
  { id: 'sage', name: 'Sage', className: 'bg-sage-600' },
  { id: 'navy', name: 'Navy', className: 'bg-navy-500' },
  { id: 'olive', name: 'Olive', className: 'bg-[#5f6b28]' },
  { id: 'clay', name: 'Clay', className: 'bg-[#9c4a24]' },
  { id: 'plum', name: 'Plum', className: 'bg-[#6d4a7c]' },
  { id: 'walnut', name: 'Walnut', className: 'bg-[#6b4f2f]' },
]

export const CHAT_THEMES: ChatTheme[] = [
  // The default — the original nature palette chat mode shipped with.
  { id: 'meadow', name: 'Meadow', bgClass: 'bg-gradient-to-br from-parchment-100 via-sage-50 to-sage-100' },
  { id: 'parchment', name: 'Parchment', bgClass: 'bg-gradient-to-br from-parchment-100 via-parchment-50 to-gold-100' },
  { id: 'morning-sky', name: 'Morning Sky', bgClass: 'bg-gradient-to-br from-sky-100 via-blue-50 to-parchment-50' },
  { id: 'sunrise', name: 'Sunrise', bgClass: 'bg-gradient-to-br from-rose-100 via-orange-50 to-amber-100' },
  { id: 'river-stone', name: 'River Stone', bgClass: 'bg-gradient-to-br from-stone-200 via-stone-100 to-sage-100' },
  { id: 'twilight', name: 'Twilight', bgClass: 'bg-gradient-to-br from-navy-100 via-sky-50 to-parchment-100' },
]

const STORAGE_KEY = 'bede-chat-theme'
const BUBBLE_STORAGE_KEY = 'bede-bubble-color'
const DEFAULT_THEME = CHAT_THEMES[0]
const DEFAULT_BUBBLE = BUBBLE_COLORS[0]

// The picker lives in the chat header while the bubbles render deeper in
// the tree (SocraticChat's MessageBubble) — separate useChatTheme()
// instances. This same-window event keeps every instance in sync the
// moment one of them changes a preference (the browser's own 'storage'
// event only fires in OTHER tabs, so it can't do this job).
const CHANGE_EVENT = 'bede-chat-theme-change'

function readStoredTheme(): ChatTheme {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return CHAT_THEMES.find((t) => t.id === raw) ?? DEFAULT_THEME
  } catch {
    return DEFAULT_THEME
  }
}

function readStoredBubble(): BubbleColor {
  try {
    const raw = localStorage.getItem(BUBBLE_STORAGE_KEY)
    return BUBBLE_COLORS.find((b) => b.id === raw) ?? DEFAULT_BUBBLE
  } catch {
    return DEFAULT_BUBBLE
  }
}

export function useChatTheme() {
  const [theme, setThemeState] = useState<ChatTheme>(() => readStoredTheme())
  const [bubble, setBubbleState] = useState<BubbleColor>(() => readStoredBubble())

  useEffect(() => {
    const onChange = () => {
      setThemeState(readStoredTheme())
      setBubbleState(readStoredBubble())
    }
    window.addEventListener(CHANGE_EVENT, onChange)
    return () => window.removeEventListener(CHANGE_EVENT, onChange)
  }, [])

  const setThemeId = useCallback((id: string) => {
    const next = CHAT_THEMES.find((t) => t.id === id) ?? DEFAULT_THEME
    // Set locally too, not only via the event — if localStorage is
    // unavailable the event round-trip would re-read the default and the
    // tap would appear to do nothing.
    setThemeState(next)
    try {
      localStorage.setItem(STORAGE_KEY, next.id)
    } catch {
      // Best-effort — a failed save just means the preference resets next visit.
    }
    window.dispatchEvent(new Event(CHANGE_EVENT))
  }, [])

  const setBubbleId = useCallback((id: string) => {
    const next = BUBBLE_COLORS.find((b) => b.id === id) ?? DEFAULT_BUBBLE
    setBubbleState(next)
    try {
      localStorage.setItem(BUBBLE_STORAGE_KEY, next.id)
    } catch {
      // Best-effort — a failed save just means the preference resets next visit.
    }
    window.dispatchEvent(new Event(CHANGE_EVENT))
  }, [])

  return { theme, setThemeId, bubble, setBubbleId }
}
