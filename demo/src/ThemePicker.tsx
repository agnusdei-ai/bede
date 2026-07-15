import { useEffect, useRef, useState } from 'react'
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
export default function ThemePicker({ theme, onSelect, bubble, onSelectBubble }: {
  theme: ChatTheme
  onSelect: (id: string) => void
  bubble: BubbleColor
  onSelectBubble: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

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
        onClick={() => setOpen((v) => !v)}
        title="Background theme"
        aria-label={`Background theme: ${theme.name}. Tap to change.`}
        aria-expanded={open}
        className="p-2 text-gray-400 hover:text-navy-600 rounded-lg hover:bg-navy-50 transition-colors"
      >
        <Palette size={15} />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 bg-white rounded-xl border border-parchment-200 shadow-lg p-2 w-52">
          <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide px-1 pb-1">Background</div>
          {CHAT_THEMES.map((t) => (
            <button
              key={t.id}
              onClick={() => { onSelect(t.id); setOpen(false) }}
              aria-pressed={t.id === theme.id}
              className={`w-full flex items-center gap-2 px-1.5 py-1.5 rounded-lg text-left transition-colors ${
                t.id === theme.id ? 'bg-navy-50' : 'hover:bg-parchment-100'
              }`}
            >
              <span className={`w-7 h-7 rounded-md border border-black/10 shrink-0 ${t.bgClass}`} />
              <span className="flex-1 text-xs font-medium text-navy-700">{t.name}</span>
              {t.id === theme.id && <Check size={13} className="text-navy-500 shrink-0" />}
            </button>
          ))}

          {/* The reader's own bubble color — round swatches (like the ink
              palette on the drawing canvas) so they read as color chips,
              distinct from the rectangular background-gradient tiles above. */}
          <div className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide px-1 pt-2 pb-1 border-t border-parchment-200 mt-1">
            Your bubble
          </div>
          <div className="flex items-center gap-1.5 px-1.5 pb-1">
            {BUBBLE_COLORS.map((b) => (
              <button
                key={b.id}
                onClick={() => onSelectBubble(b.id)}
                title={b.name}
                aria-pressed={b.id === bubble.id}
                aria-label={`Bubble color: ${b.name}`}
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
