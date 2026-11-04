import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Palette, Check } from 'lucide-react'
import { BUBBLE_COLORS, CHAT_THEMES, type BubbleColor, type ChatTheme } from './useChatTheme'

/**
 * Compact background-theme picker for the chat header: a palette icon that
 * opens a small dropdown of gradient swatches (each swatch IS the theme's
 * real gradient, so what you tap is what you get), plus a row of round
 * swatches for the reader's own bubble color. Selection is applied and
 * persisted by the parent via useChatTheme. Mirror of
 * homeschool-tutor/src/components/ThemePicker.tsx.
 */
// The menu is 13rem wide (w-52). It opens under the palette button and is
// kept inside the screen: the header's buttons moved the palette left when
// Practice Coach was added, and a menu aligned to the button's right edge
// then opened about 50px past the left edge of a phone.
export const MENU_WIDTH = 208
export const MENU_GUTTER = 8

export function placeThemeMenu(
  button: { left: number; right: number; bottom: number },
  viewportWidth: number,
  viewportHeight: number,
): { top: number; left: number; maxHeight: number } {
  const width = Math.min(MENU_WIDTH, viewportWidth - 2 * MENU_GUTTER)
  const preferred = button.right - width
  const left = Math.max(MENU_GUTTER, Math.min(preferred, viewportWidth - width - MENU_GUTTER))
  const top = button.bottom + 4
  return { top, left, maxHeight: Math.max(120, viewportHeight - top - MENU_GUTTER) }
}

export default function ThemePicker({ theme, onSelect, bubble, onSelectBubble }: {
  theme: ChatTheme
  onSelect: (id: string) => void
  bubble: BubbleColor
  onSelectBubble: (id: string) => void
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const [place, setPlace] = useState<{ top: number; left: number; maxHeight: number } | null>(null)

  // Position against the viewport, not the header, so the menu can never
  // open off the screen whatever sits beside the button.
  useLayoutEffect(() => {
    if (!open || !buttonRef.current) { setPlace(null); return }
    const r = buttonRef.current.getBoundingClientRect()
    setPlace(placeThemeMenu(r, window.innerWidth, window.innerHeight))
  }, [open])

  // A fixed menu would drift from its button on scroll or rotation, so it
  // closes instead.
  useEffect(() => {
    if (!open) return
    const close = () => setOpen(false)
    // Scrolling the menu's own list (a short screen) must not close it.
    const onScroll = (e: Event) => {
      if (menuRef.current && e.target instanceof Node && menuRef.current.contains(e.target)) return
      setOpen(false)
    }
    window.addEventListener('resize', close)
    window.addEventListener('scroll', onScroll, true)
    return () => {
      window.removeEventListener('resize', close)
      window.removeEventListener('scroll', onScroll, true)
    }
  }, [open])

  // Close on any tap/click outside — standard dropdown behavior, and on a
  // tablet there's no Esc key to reach for.
  useEffect(() => {
    if (!open) return
    const onPointerDown = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open])

  return (
    <div ref={rootRef} className="relative shrink-0">
      <button
        ref={buttonRef}
        onClick={() => setOpen((v) => !v)}
        title={t('themePicker.backgroundTheme')}
        aria-label={t('themePicker.backgroundThemeAria', { name: theme.name })}
        aria-expanded={open}
        className="p-2 text-gray-400 hover:text-navy-600 rounded-lg hover:bg-navy-50 transition-colors"
      >
        <Palette size={15} />
      </button>

      {open && place && (
        <div
          ref={menuRef}
          data-testid="theme-menu"
          className="fixed z-50 bg-white rounded-xl border border-parchment-200 shadow-lg p-2 overflow-y-auto"
          style={{ top: place.top, left: place.left, width: Math.min(MENU_WIDTH, window.innerWidth - 2 * MENU_GUTTER), maxHeight: place.maxHeight }}
        >
          <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide px-1 pb-1">{t('themePicker.background')}</div>
          {CHAT_THEMES.map((ct) => (
            <button
              key={ct.id}
              onClick={() => { onSelect(ct.id); setOpen(false) }}
              aria-pressed={ct.id === theme.id}
              className={`w-full flex items-center gap-2 px-1.5 py-1.5 rounded-lg text-left transition-colors ${
                ct.id === theme.id ? 'bg-navy-50' : 'hover:bg-parchment-100'
              }`}
            >
              <span className={`w-7 h-7 rounded-md border border-black/10 shrink-0 ${ct.bgClass}`} />
              <span className="flex-1 text-xs font-medium text-navy-700">{ct.name}</span>
              {ct.id === theme.id && <Check size={13} className="text-navy-500 shrink-0" />}
            </button>
          ))}

          {/* The reader's own bubble color — round swatches (like the ink
              palette on the drawing canvas) so they read as color chips,
              distinct from the rectangular background-gradient tiles above. */}
          <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide px-1 pt-2 pb-1 border-t border-parchment-200 mt-1">
            {t('themePicker.yourBubble')}
          </div>
          <div className="flex items-center gap-1.5 px-1.5 pb-1">
            {BUBBLE_COLORS.map((b) => (
              <button
                key={b.id}
                onClick={() => onSelectBubble(b.id)}
                title={b.name}
                aria-pressed={b.id === bubble.id}
                aria-label={t('themePicker.bubbleColorAria', { name: b.name })}
                className={`w-6 h-6 rounded-full border-2 transition-transform shrink-0 ${b.className} ${
                  b.id === bubble.id ? 'border-navy-500 scale-110' : 'border-white shadow-sm'
                }`}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
