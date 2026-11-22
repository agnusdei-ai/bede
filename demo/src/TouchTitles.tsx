import { useEffect, useLayoutEffect, useRef, useState } from 'react'

/**
 * A control's tooltip, shown on a TOUCH screen too.
 *
 * Most icon buttons explain themselves with `title`, which a browser shows
 * only on hover, and a phone or tablet never hovers: the one thing saying
 * what an icon does was unreachable on the devices Bede mostly runs on. This
 * listens once, for the whole page: when a control is tapped (touch or pen,
 * never a mouse, which already gets the browser's own tooltip), its `title`
 * is shown just below it for TOUCH_TITLE_MS. The tap still does what it
 * does; the label only names what just happened, so the controls are
 * learned by using them (the same rule as IconButton, which has its own
 * label and sets no `title`, so the two never show at once).
 *
 * Clamped into the viewport, flipped above when there is no room below, and
 * dismissed on scroll or resize, since its position was measured at the tap.
 * Decorative for assistive technology (`aria-hidden`): every such control
 * already carries an accessible name of its own.
 *
 * Mirror of homeschool-tutor/src/components/TouchTitles.tsx; demo/src/TouchTitles.test.ts keeps the two the same.
 */
export const TOUCH_TITLE_MS = 1600
const GAP = 6
const EDGE = 8

export default function TouchTitles() {
  const [tip, setTip] = useState<{ text: string; top: number; bottom: number; center: number } | null>(null)
  const [place, setPlace] = useState<{ left: number; top: number } | null>(null)
  const ref = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    let touch = false
    let timer: ReturnType<typeof setTimeout> | null = null
    const hide = () => { if (timer) clearTimeout(timer); timer = null; setTip(null) }
    const down = (event: PointerEvent) => { touch = event.pointerType === 'touch' || event.pointerType === 'pen' }
    const click = (event: MouseEvent) => {
      if (!touch) return
      const target = event.target instanceof Element ? event.target : null
      const control = target?.closest<HTMLElement>('button[title], a[title], [role="button"][title], label[title]')
      const text = control?.getAttribute('title')?.trim()
      if (!control || !text) return
      const r = control.getBoundingClientRect()
      if (timer) clearTimeout(timer)
      setTip({ text, top: r.top, bottom: r.bottom, center: r.left + r.width / 2 })
      timer = setTimeout(hide, TOUCH_TITLE_MS)
    }
    document.addEventListener('pointerdown', down, true)
    document.addEventListener('click', click, true)
    window.addEventListener('scroll', hide, true)
    window.addEventListener('resize', hide)
    return () => {
      if (timer) clearTimeout(timer)
      document.removeEventListener('pointerdown', down, true)
      document.removeEventListener('click', click, true)
      window.removeEventListener('scroll', hide, true)
      window.removeEventListener('resize', hide)
    }
  }, [])

  useLayoutEffect(() => {
    if (!tip || !ref.current) { setPlace(null); return }
    const { width, height } = ref.current.getBoundingClientRect()
    const vw = window.innerWidth
    const vh = window.innerHeight
    const left = Math.min(Math.max(EDGE, tip.center - width / 2), Math.max(EDGE, vw - width - EDGE))
    const below = tip.bottom + GAP
    const top = below + height + EDGE <= vh ? below : Math.max(EDGE, tip.top - GAP - height)
    setPlace({ left, top })
  }, [tip])

  if (!tip) return null
  return (
    <span
      ref={ref} aria-hidden="true" data-testid="touch-title"
      style={{ position: 'fixed', left: place?.left ?? -9999, top: place?.top ?? -9999, maxWidth: `calc(100vw - ${2 * EDGE}px)` }}
      className="pointer-events-none z-[60] rounded-md bg-navy-800 px-2 py-1 text-xs font-medium text-white shadow-lg"
    >
      {tip.text}
    </span>
  )
}
