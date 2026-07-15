import { useCallback, useState } from 'react'

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
 * scanner sees and generates them. Mirror of homeschool-tutor/src/hooks/useChatTheme.ts.
 */

export interface ChatTheme {
  id: string
  name: string
  bgClass: string
}

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
const DEFAULT_THEME = CHAT_THEMES[0]

function readStoredTheme(): ChatTheme {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return CHAT_THEMES.find((t) => t.id === raw) ?? DEFAULT_THEME
  } catch {
    return DEFAULT_THEME
  }
}

export function useChatTheme() {
  const [theme, setThemeState] = useState<ChatTheme>(() => readStoredTheme())

  const setThemeId = useCallback((id: string) => {
    const next = CHAT_THEMES.find((t) => t.id === id) ?? DEFAULT_THEME
    setThemeState(next)
    try {
      localStorage.setItem(STORAGE_KEY, next.id)
    } catch {
      // Best-effort — a failed save just means the preference resets next visit.
    }
  }, [])

  return { theme, setThemeId }
}
