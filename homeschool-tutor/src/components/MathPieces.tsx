import { useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { useTranslation } from 'react-i18next'
import type { CounterColor, CountersPiece, EqualGroupsPiece, MathPiece, NumberBondPiece, TenFramePiece } from '../services/k2MathTypes'

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

/**
 * A ten-frame is five boxes across and two down. When five boxes do not fit
 * the space the round has (a phone, larger text), the frame turns on its side:
 * two boxes across and five down, filled down the first column and then the
 * second, so it is still two fives. Columns are never squeezed below their
 * boxes, which is what made boxes overlap and taps land on the wrong one.
 *
 * The switch is a CSS container query in rem on the frame's own wrapper
 * (FRAME_CONTAINER), not a viewport breakpoint: rem follows the app's own
 * text-size control, a viewport width does not. The thresholds are the width
 * five boxes need: 5 x 3.5rem boxes + 4 x 0.5rem gaps + 0.5rem padding + the
 * 4px border for a frame the child fills (BUILD_FRAME_GRID), and 5 x 2.75rem
 * + 4 x 0.25rem + 0.5rem + the border for a picture (PICTURE_FRAME_GRID).
 */
export const FRAME_CONTAINER = 'w-full [container-type:inline-size]'
export const BUILD_FRAME_GRID = 'grid grid-cols-5 gap-2 [@container(max-width:20.75rem)]:grid-cols-2 '
  + '[@container(max-width:20.75rem)]:grid-rows-5 [@container(max-width:20.75rem)]:grid-flow-col'
export const PICTURE_FRAME_GRID = 'grid grid-cols-5 gap-1 [@container(max-width:16rem)]:grid-cols-2 '
  + '[@container(max-width:16rem)]:grid-rows-5 [@container(max-width:16rem)]:grid-flow-col'

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
        // Without the guide (Your turn) the label never says how many: the
        // count is the question, and a screen reader must not answer it.
        <div key={gi} role="img"
          aria-label={guide ? t(`k2Math.rowOf.${g.color}`, { count: g.count }) : t(`k2Math.rowQuiet.${g.color}`)}
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
  // Without the guide (Your turn) the label never states a total: for "how
  // many in all" it is the answer.
  const label = guide ? t('k2Math.frameLabel', { count: total, crossed: d.crossed ?? 0 }) : t('k2Math.frameQuiet')
  return (
    <div className={FRAME_CONTAINER}>
    <div className="mx-auto flex w-fit flex-col gap-2" role="img" data-testid="math-ten-frame" aria-label={label}>
      {Array.from({ length: d.frames ?? 1 }, (_, f) => (
        <div key={f} className={`${PICTURE_FRAME_GRID} rounded-lg border-4 border-navy-700 bg-white p-1`}>
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

/**
 * Plates of counters, grade 2's bridge to multiplication and division. With
 * the guide (Watch, Together) each plate shows the running total under it,
 * which is counting by the plate's size (4, 8, 12...), and a sharing picture
 * shows the fair share faintly on each plate. Your turn shows neither, and
 * its label never states the answer. No times or divide sign anywhere.
 */
function EqualGroupsPicture({ d, guide }: { d: EqualGroupsPiece; guide: boolean }) {
  const { t } = useTranslation()
  const each = d.each ?? 0
  const loose = d.loose ?? 0
  const share = loose > 0 ? loose / d.groups : 0
  // Without the guide (Your turn) the label states no number at all, the
  // same rule as every other piece's quiet label.
  const label = !guide ? t(loose > 0 ? 'k2Math.shareQuiet' : 'k2Math.groupsQuiet')
    : loose > 0 ? t('k2Math.shareLabel', { total: loose, groups: d.groups })
      : t('k2Math.groupsLabel', { groups: d.groups, each })
  return (
    <div className="flex flex-col items-center gap-3" role="img" aria-label={label} data-testid="math-equal-groups">
      {loose > 0 && (
        <div className="flex max-w-[20rem] flex-wrap justify-center gap-1" data-testid="math-loose">
          {Array.from({ length: loose }, (_, i) => <Counter key={i} color="yellow" />)}
        </div>
      )}
      <div className="flex flex-wrap justify-center gap-3">
        {Array.from({ length: d.groups }, (_, g) => (
          <div key={g} className="flex flex-col items-center gap-1">
            <div data-plate="" className="flex min-h-[4.5rem] w-[6.5rem] flex-wrap content-center items-center justify-center gap-0.5 rounded-full border-4 border-navy-300 bg-white p-2">
              {Array.from({ length: each }, (_, i) => <Counter key={i} color="red" />)}
              {guide && Array.from({ length: share }, (_, i) => <Counter key={`s${i}`} color="yellow" faint />)}
            </div>
            {guide && each > 0 && (
              <span data-running="" className="text-lg font-semibold text-navy-700 tabular-nums">{(g + 1) * each}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

/** Draws any piece. Anything outside the closed vocabulary draws nothing. */
export function MathPicture({ d, guide = false }: { d: MathPiece | null | undefined; guide?: boolean }) {
  if (!d) return null
  if (d.kind === 'counters') return <CountersPicture d={d} guide={guide} />
  if (d.kind === 'ten_frame') return <TenFramePicture d={d} guide={guide} />
  if (d.kind === 'number_bond') return <NumberBondPicture d={d} />
  if (d.kind === 'equal_groups') return <EqualGroupsPicture d={d} guide={guide} />
  return null
}

/** The kinds this file draws: kept equal to the server's list by test. */
export const PIECE_KINDS = ['counters', 'ten_frame', 'number_bond', 'equal_groups'] as const

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
  frames, start, count, onChange, ghost, takeAway = false, disabled = false,
}: {
  frames: number
  /** Counters already there when the question opened, drawn red. */
  start: number
  count: number
  onChange: (count: number) => void
  /** Together: how many the frame should hold, faintly shown. When counters
   * are being taken away, the ones to take are outlined instead, since the
   * boxes below the target start full. */
  ghost?: number
  takeAway?: boolean
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
    <div className="flex w-full flex-col items-center gap-3" onPointerMove={move} onPointerUp={end}
      onPointerDownCapture={() => { dragged.current = false }}
      onPointerCancel={() => { drag.current = null; setFloating(null) }} data-testid="math-builder">
      <div className={FRAME_CONTAINER}>
      <div ref={frameRef} className="mx-auto flex w-fit flex-col gap-2" data-testid="math-build-frame"
        role="group" aria-label={t('k2Math.buildLabel', { count })}>
        {Array.from({ length: frames }, (_, f) => (
          <div key={f} className={`${BUILD_FRAME_GRID} rounded-lg border-4 border-navy-700 bg-white p-1`}>
            {Array.from({ length: 10 }, (_, i) => {
              const n = f * 10 + i
              const full = n < count
              const color: CounterColor = n < start ? 'red' : 'yellow'
              const guideEmpty = !full && !takeAway && ghost !== undefined && n < ghost
              const guideRemove = full && takeAway && ghost !== undefined && n >= ghost
              return (
                <button
                  key={n} type="button" disabled={disabled}
                  onClick={tap(full ? count - 1 : count + 1)}
                  onPointerDown={full ? begin('frame') : undefined}
                  aria-label={guideRemove ? t('k2Math.takeAwayBox', { n: n + 1 })
                    : full ? t('k2Math.takeFromBox', { n: n + 1 }) : t('k2Math.putInBox', { n: n + 1 })}
                  data-full={full ? '' : undefined}
                  data-ghost={guideEmpty ? '' : undefined}
                  data-remove={guideRemove ? '' : undefined}
                  className={`min-h-14 min-w-14 flex items-center justify-center rounded-md touch-none ${
                    guideEmpty ? 'border-2 border-dashed border-sage-500 bg-sage-50'
                      : guideRemove ? 'border-4 border-dashed border-madder-500 bg-madder-50'
                        : 'border border-navy-300'
                  }`}
                >
                  {full && <Counter color={color} />}
                </button>
              )
            })}
          </div>
        ))}
      </div>
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
