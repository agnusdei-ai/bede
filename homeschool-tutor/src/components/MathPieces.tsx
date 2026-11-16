import { useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { useTranslation } from 'react-i18next'
import type { CounterColor, CountersPiece, MathPiece, NumberBondPiece, TenFramePiece } from '../services/api'

/**
 * The pieces of a K-2 practical-math round (docs/K2_PRACTICE.md §5.3):
 * counters, a ten-frame and a number bond, drawn from numbers alone.
 *
 * The server's closed vocabulary (homeschool-api/models/practice.py's
 * PieceDiagram) carries only numbers and two counter colors, so there is
 * nothing a model or a request could write that reaches this page as text or
 * markup. These are kept apart from Diagram.tsx on purpose: that component is
 * what a quiz reader's pictures draw through, and the public demo mirrors it
 * byte for byte; these pieces are built only by the K-2 round itself.
 *
 * A red counter is solid and a yellow one is a ring, so the two never differ
 * by color alone. Every size is in rem, so a counter grows with the text-size
 * control and nothing forces sideways scrolling at 200% text. Movement is only
 * ever under motion-safe.
 */

/** One counter, drawn in SVG. `n` is the guide number written on it. */
export function Counter({ color, n, faint = false }: { color: CounterColor; n?: number; faint?: boolean }) {
  const red = color === 'red'
  return (
    <svg viewBox="0 0 40 40" aria-hidden="true" data-counter={color}
      className={`h-9 w-9 shrink-0 ${faint ? 'opacity-30' : ''}`}>
      {red ? (
        <circle cx="20" cy="20" r="17" className="fill-madder-500" />
      ) : (
        <>
          <circle cx="20" cy="20" r="17" className="fill-gold-300 stroke-gold-700" strokeWidth="3" />
          <circle cx="20" cy="20" r="8" className="fill-none stroke-gold-700" strokeWidth="3" />
        </>
      )}
      {n !== undefined && (
        <text x="20" y="25" textAnchor="middle" fontSize="15" fontWeight="700"
          className={red ? 'fill-white' : 'fill-navy-800'}>{n}</text>
      )}
    </svg>
  )
}

function CountersPicture({ d, guide }: { d: CountersPiece; guide: boolean }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-2" data-testid="math-counters">
      {d.groups.map((g, gi) => (
        <div key={gi} role="img" aria-label={t(`k2Math.rowOf.${g.color}`, { count: g.count })}
          className="flex flex-wrap gap-1">
          {Array.from({ length: g.count }, (_, i) => (
            <Counter key={i} color={g.color} n={guide ? i + 1 : undefined} />
          ))}
        </div>
      ))}
    </div>
  )
}

/** The cells of one or two ten-frames, filled in order: red first, then
 * yellow; the last `crossed` filled cells drawn with a cross. */
function frameCells(d: TenFramePiece): { color: CounterColor | null; crossed: boolean }[] {
  const frames = d.frames ?? 1
  const red = d.red ?? 0
  const yellow = d.yellow ?? 0
  const filled = red + yellow
  const crossedFrom = filled - (d.crossed ?? 0)
  return Array.from({ length: frames * 10 }, (_, i) => ({
    color: i < red ? 'red' : i < filled ? 'yellow' : null,
    crossed: i < filled && i >= crossedFrom,
  }))
}

function TenFramePicture({ d, guide }: { d: TenFramePiece; guide: boolean }) {
  const { t } = useTranslation()
  const cells = frameCells(d)
  const total = (d.red ?? 0) + (d.yellow ?? 0)
  return (
    <div className="flex flex-col gap-2" role="img" data-testid="math-ten-frame"
      aria-label={t('k2Math.frameLabel', { count: total, crossed: d.crossed ?? 0 })}>
      {Array.from({ length: d.frames ?? 1 }, (_, f) => (
        <div key={f} className="grid grid-cols-5 gap-1 rounded-lg border-4 border-navy-700 bg-white p-1">
          {cells.slice(f * 10, f * 10 + 10).map((cell, i) => (
            <div key={i} className="relative flex min-h-11 min-w-11 items-center justify-center border border-navy-300">
              {cell.color && <Counter color={cell.color} n={guide ? f * 10 + i + 1 : undefined} />}
              {cell.crossed && (
                <svg viewBox="0 0 40 40" aria-hidden="true" className="absolute inset-0 m-auto h-9 w-9" data-crossed="">
                  <line x1="6" y1="6" x2="34" y2="34" className="stroke-navy-800" strokeWidth="4" />
                  <line x1="34" y1="6" x2="6" y2="34" className="stroke-navy-800" strokeWidth="4" />
                </svg>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function NumberBondPicture({ d }: { d: NumberBondPiece }) {
  const { t } = useTranslation()
  const shown = (v: number | null) => (v === null ? '?' : String(v))
  const [a, b] = d.parts
  const circle = (cx: number, cy: number, value: number | null, key: string) => (
    <g key={key}>
      <circle cx={cx} cy={cy} r="26" className={value === null ? 'fill-parchment-50 stroke-navy-700' : 'fill-white stroke-navy-700'}
        strokeWidth="3" strokeDasharray={value === null ? '6 4' : undefined} />
      <text x={cx} y={cy + 9} textAnchor="middle" fontSize="26" fontWeight="700" className="fill-navy-800">
        {shown(value)}
      </text>
    </g>
  )
  return (
    <svg viewBox="0 0 200 150" role="img" data-testid="math-number-bond" className="w-full max-w-[16rem]"
      aria-label={t('k2Math.bondLabel', { whole: shown(d.whole), a: shown(a), b: shown(b) })}>
      <line x1="100" y1="40" x2="45" y2="110" className="stroke-navy-700" strokeWidth="3" />
      <line x1="100" y1="40" x2="155" y2="110" className="stroke-navy-700" strokeWidth="3" />
      {circle(100, 32, d.whole, 'whole')}
      {circle(45, 115, a, 'a')}
      {circle(155, 115, b, 'b')}
    </svg>
  )
}

/** Draws any piece. Anything outside the closed vocabulary draws nothing. */
export function MathPicture({ d, guide = false }: { d: MathPiece | null | undefined; guide?: boolean }) {
  if (!d) return null
  if (d.kind === 'counters') return <CountersPicture d={d} guide={guide} />
  if (d.kind === 'ten_frame') return <TenFramePicture d={d} guide={guide} />
  if (d.kind === 'number_bond') return <NumberBondPicture d={d} />
  return null
}

/** The kinds this file draws: kept equal to the server's list by test. */
export const PIECE_KINDS = ['counters', 'ten_frame', 'number_bond'] as const

/**
 * A ten-frame the child fills or empties. Three ways to move a counter, so
 * dragging is never the only way (docs/K2_PRACTICE.md §5.3):
 *
 * - drag a counter from the tray onto the frame, or a counter off the frame;
 * - tap an empty box to put a counter in, or a full one to take one out;
 * - the two large buttons below, "Put in a counter" and "Take one out".
 *
 * Counters always fill the frame in order, the way a ten-frame is used, so
 * the answer is simply how many are on it.
 */
export function TenFrameBuilder({
  frames, start, count, onChange, ghost, disabled = false,
}: {
  frames: number
  /** Counters already there when the question opened, drawn red. */
  start: number
  count: number
  onChange: (count: number) => void
  /** Together: how many the frame should hold, faintly shown. */
  ghost?: number
  disabled?: boolean
}) {
  const { t } = useTranslation()
  const capacity = frames * 10
  const frameRef = useRef<HTMLDivElement>(null)
  const drag = useRef<{ from: 'tray' | 'frame'; x: number; y: number } | null>(null)
  // A drag that ends where it began can still be followed by a click on the
  // same element (touch has implicit pointer capture); that click must not
  // move a second counter. Cleared at the start of every press.
  const dragged = useRef(false)
  const [floating, setFloating] = useState<{ x: number; y: number } | null>(null)

  const set = (n: number) => { if (!disabled) onChange(Math.max(0, Math.min(capacity, n))) }
  const tap = (n: number) => () => {
    if (dragged.current) { dragged.current = false; return }
    set(n)
  }

  const begin = (from: 'tray' | 'frame') => (e: ReactPointerEvent) => {
    if (disabled) return
    drag.current = { from, x: e.clientX, y: e.clientY }
  }
  const move = (e: ReactPointerEvent) => {
    if (!drag.current) return
    if (Math.abs(e.clientX - drag.current.x) + Math.abs(e.clientY - drag.current.y) > 8) {
      setFloating({ x: e.clientX, y: e.clientY })
    }
  }
  const end = (e: ReactPointerEvent) => {
    const started = drag.current
    drag.current = null
    setFloating(null)
    if (!started || disabled) return
    const moved = Math.abs(e.clientX - started.x) + Math.abs(e.clientY - started.y) > 8
    if (!moved) return // a tap: the box's own click handles it
    dragged.current = true
    const target = document.elementFromPoint?.(e.clientX, e.clientY) ?? null
    const onFrame = !!target && !!frameRef.current?.contains(target)
    if (started.from === 'tray' && onFrame) set(count + 1)
    if (started.from === 'frame' && !onFrame) set(count - 1)
  }

  return (
    <div className="flex flex-col items-center gap-3" onPointerMove={move} onPointerUp={end}
      onPointerDownCapture={() => { dragged.current = false }}
      onPointerCancel={() => { drag.current = null; setFloating(null) }} data-testid="math-builder">
      <div ref={frameRef} className="flex flex-col gap-2" data-testid="math-build-frame"
        role="group" aria-label={t('k2Math.frameLabel', { count, crossed: 0 })}>
        {Array.from({ length: frames }, (_, f) => (
          <div key={f} className="grid grid-cols-5 gap-2 rounded-lg border-4 border-navy-700 bg-white p-1">
            {Array.from({ length: 10 }, (_, i) => {
              const n = f * 10 + i
              const full = n < count
              const color: CounterColor = n < start ? 'red' : 'yellow'
              return (
                <button
                  key={n} type="button" disabled={disabled}
                  onClick={tap(full ? count - 1 : count + 1)}
                  onPointerDown={full ? begin('frame') : undefined}
                  aria-label={full ? t('k2Math.takeFromBox', { n: n + 1 }) : t('k2Math.putInBox', { n: n + 1 })}
                  data-full={full ? '' : undefined}
                  data-ghost={!full && ghost !== undefined && n < ghost ? '' : undefined}
                  className={`min-h-14 min-w-14 flex items-center justify-center rounded-md touch-none ${
                    !full && ghost !== undefined && n < ghost
                      ? 'border-2 border-dashed border-sage-500 bg-sage-50' : 'border border-navy-300'
                  }`}
                >
                  {full && <Counter color={color} />}
                </button>
              )
            })}
          </div>
        ))}
      </div>
      <div className="flex flex-wrap items-center justify-center gap-2">
        <button
          type="button" disabled={disabled || count >= capacity}
          onPointerDown={begin('tray')}
          onClick={tap(count + 1)}
          aria-label={t('k2Math.trayCounter')}
          data-testid="math-tray"
          className="min-h-14 min-w-14 flex items-center justify-center rounded-full border-2 border-dashed border-sage-400 bg-white touch-none"
        >
          <Counter color={count < start ? 'red' : 'yellow'} />
        </button>
        <button type="button" disabled={disabled || count >= capacity} onClick={() => set(count + 1)}
          className="min-h-14 min-w-14 rounded-xl border-2 border-sage-300 bg-white px-3 text-base font-medium text-navy-700">
          {t('k2Math.addOne')}
        </button>
        <button type="button" disabled={disabled || count <= 0} onClick={() => set(count - 1)}
          className="min-h-14 min-w-14 rounded-xl border-2 border-sage-300 bg-white px-3 text-base font-medium text-navy-700">
          {t('k2Math.takeOne')}
        </button>
      </div>
      <p className="text-sm text-gray-600 text-center">{t('k2Math.dragHint')}</p>
      {floating && (
        <div aria-hidden="true" className="pointer-events-none fixed z-50 -translate-x-1/2 -translate-y-1/2"
          style={{ left: floating.x, top: floating.y }}>
          <Counter color="yellow" />
        </div>
      )}
    </div>
  )
}
