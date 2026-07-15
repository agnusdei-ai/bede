import { useEffect, useRef, useState } from 'react'
import { Palette, Check } from 'lucide-react'
import { CHAT_THEMES, type ChatTheme } from '../hooks/useChatTheme'

/**
 * Compact background-theme picker for the chat header: a palette icon that
 * opens a small dropdown of gradient swatches (each swatch IS the theme's
 * real gradient, so what you tap is what you get). Selection is applied
 * and persisted by the parent via useChatTheme. Mirrored in
 * demo/src/ThemePicker.tsx.
 */
export default function ThemePicker({ theme, onSelect }: { theme: ChatTheme; onSelect: (id: string) => void }) {
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
        <div className="absolute right-0 top-full mt-1 z-50 bg-white rounded-xl border border-parchment-200 shadow-lg p-2 w-44">
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
        </div>
      )}
    </div>
  )
}
