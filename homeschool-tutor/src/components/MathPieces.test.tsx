/**
 * The pieces of a K-2 math round (docs/K2_PRACTICE.md §5.3): counters, a
 * ten-frame and a number bond, drawn from numbers alone, and the ten-frame a
 * child fills by dragging OR by tapping. These tests pin the drawing of each
 * new kind, that the kinds here equal the server's closed list, that every
 * drag has a tap-only alternative, and the target-size class contract (jsdom
 * lays nothing out).
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { useState } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import type { MathPiece } from '../services/api'
import {
  BUILD_FRAME_GRID, FRAME_CONTAINER, MathPicture, PICTURE_FRAME_GRID, PIECE_KINDS, TenFrameBuilder,
} from './MathPieces'

beforeEach(async () => { await i18n.changeLanguage('en') })
afterEach(() => { cleanup(); vi.restoreAllMocks() })

function Builder({ frames = 1, start = 0, ghost, takeAway, onCount }: {
  frames?: number; start?: number; ghost?: number; takeAway?: boolean; onCount?: (n: number) => void
}) {
  const [count, setCount] = useState(start)
  return (
    <>
      <TenFrameBuilder frames={frames} start={start} count={count} ghost={ghost} takeAway={takeAway}
        onChange={(n) => { setCount(n); onCount?.(n) }} />
      <output data-testid="count">{count}</output>
    </>
  )
}
const count = () => Number(screen.getByTestId('count').textContent)

describe('MathPicture', () => {
  it('draws counters in rows, red solid and yellow as a ring, numbered only with the guide', () => {
    const d: MathPiece = { kind: 'counters', groups: [{ color: 'red', count: 4 }, { color: 'yellow', count: 6 }] }
    const { container, rerender } = render(<MathPicture d={d} />)
    expect(container.querySelectorAll('[data-counter="red"]')).toHaveLength(4)
    expect(container.querySelectorAll('[data-counter="yellow"]')).toHaveLength(6)
    // Not color alone: a yellow counter carries an inner ring, a red one does not.
    expect(container.querySelector('[data-counter="yellow"]')!.querySelectorAll('circle')).toHaveLength(2)
    expect(container.querySelector('[data-counter="red"]')!.querySelectorAll('circle')).toHaveLength(1)
    // Without the guide (Your turn) the row's name does not count it.
    expect(screen.getByRole('img', { name: 'A row of red counters' })).toBeTruthy()
    expect(container.querySelectorAll('text')).toHaveLength(0)
    rerender(<MathPicture d={d} guide />)
    expect(screen.getByRole('img', { name: '4 red counters' })).toBeTruthy()
    expect(Array.from(container.querySelectorAll('text')).map((t) => t.textContent).slice(0, 4)).toEqual(['1', '2', '3', '4'])
  })

  it('draws a ten-frame filled in order, with the taken-away ones crossed out', () => {
    const { container } = render(<MathPicture d={{ kind: 'ten_frame', frames: 2, red: 8, yellow: 5, crossed: 3 }} guide />)
    expect(container.querySelectorAll('[data-counter]')).toHaveLength(13)
    expect(container.querySelectorAll('[data-counter="red"]')).toHaveLength(8)
    expect(container.querySelectorAll('[data-crossed]')).toHaveLength(3)
    expect(container.querySelectorAll('.grid')).toHaveLength(2)
    expect(screen.getByRole('img', { name: 'A ten-frame with 13 counters, 3 crossed out' })).toBeTruthy()
  })

  it('in Your turn, no picture names a quantity a screen reader could answer with', async () => {
    // The echo rule applied to accessible names: without the guide, a label
    // never states how many there are, since that is what is being asked.
    const pieces: MathPiece[] = [
      { kind: 'counters', groups: [{ color: 'red', count: 7 }] },
      { kind: 'counters', groups: [{ color: 'red', count: 4 }, { color: 'yellow', count: 6 }] },
      { kind: 'ten_frame', frames: 1, red: 6, yellow: 1 },
      { kind: 'ten_frame', frames: 2, red: 13, crossed: 4 },
      { kind: 'equal_groups', groups: 3, each: 4 },
      { kind: 'equal_groups', groups: 4, loose: 12 },
    ]
    for (const locale of ['en', 'es']) {
      await i18n.changeLanguage(locale)
      for (const d of pieces) {
        const { container, unmount } = render(<MathPicture d={d} />)
        const names = Array.from(container.querySelectorAll('[aria-label]')).map((el) => el.getAttribute('aria-label') ?? '')
        expect(names.length, JSON.stringify(d)).toBeGreaterThan(0)
        for (const name of names) expect(name, `${locale}: ${name}`).not.toMatch(/\d/)
        unmount()
      }
    }
  })

  it('draws a number bond with the blank as a question mark', () => {
    render(<MathPicture d={{ kind: 'number_bond', whole: 7, parts: [3, null] }} />)
    const bond = screen.getByTestId('math-number-bond')
    expect(Array.from(bond.querySelectorAll('text')).map((t) => t.textContent)).toEqual(['7', '3', '?'])
    expect(bond.getAttribute('aria-label')).toBe('A number bond: 7 is 3 and ?')
  })

  it('draws plates of counters, with the running count (skip counting) only as the guide', () => {
    const { container, rerender } = render(<MathPicture d={{ kind: 'equal_groups', groups: 3, each: 4 }} guide />)
    expect(container.querySelectorAll('[data-plate]')).toHaveLength(3)
    expect(container.querySelectorAll('[data-plate] [data-counter="red"]')).toHaveLength(12)
    expect(Array.from(container.querySelectorAll('[data-running]')).map((n) => n.textContent)).toEqual(['4', '8', '12'])
    expect(screen.getByRole('img', { name: '3 plates with 4 counters on each' })).toBeTruthy()
    rerender(<MathPicture d={{ kind: 'equal_groups', groups: 3, each: 4 }} />)
    expect(container.querySelectorAll('[data-running]')).toHaveLength(0)
    expect(screen.getByRole('img', { name: 'Plates of counters' })).toBeTruthy()
  })

  it('draws counters to share above empty plates, with the fair share shown faintly only as the guide', () => {
    const { container, rerender } = render(<MathPicture d={{ kind: 'equal_groups', groups: 4, loose: 12 }} />)
    expect(container.querySelectorAll('[data-testid="math-loose"] [data-counter]')).toHaveLength(12)
    expect(container.querySelectorAll('[data-plate] [data-counter]')).toHaveLength(0)
    rerender(<MathPicture d={{ kind: 'equal_groups', groups: 4, loose: 12 }} guide />)
    expect(container.querySelectorAll('[data-plate] [data-counter]')).toHaveLength(12)
    expect(screen.getByRole('img', { name: '12 counters to share onto 4 plates' })).toBeTruthy()
  })

  it('never shows a times or divide sign on a plate picture', () => {
    for (const d of [{ kind: 'equal_groups', groups: 5, each: 10 }, { kind: 'equal_groups', groups: 3, loose: 15 }] as MathPiece[]) {
      for (const guide of [true, false]) {
        const { container, unmount } = render(<MathPicture d={d} guide={guide} />)
        expect(container.textContent ?? '').not.toMatch(/[×÷*/]/)
        unmount()
      }
    }
  })

  it('draws nothing for a kind outside the closed vocabulary', () => {
    const { container } = render(<MathPicture d={{ kind: 'svg' } as unknown as MathPiece} />)
    expect(container.innerHTML).toBe('')
  })

  it('draws exactly the kinds the server may send', () => {
    const py = readFileSync(join(__dirname, '../../../homeschool-api/models/practice.py'), 'utf8')
    const kinds = py.match(/^PIECE_DIAGRAM_KINDS = \(([^)]*)\)/m)?.[1].match(/"(\w+)"/g)?.map((k) => k.slice(1, -1)) ?? []
    expect([...PIECE_KINDS].sort()).toEqual(kinds.sort())
    expect(kinds).toHaveLength(4)
  })
})

describe('TenFrameBuilder', () => {
  it('puts a counter in with a tap on an empty box, and takes one out with a tap on a full one', () => {
    render(<Builder />)
    fireEvent.click(screen.getByRole('button', { name: 'Put a counter in box 1' }))
    fireEvent.click(screen.getByRole('button', { name: 'Put a counter in box 5' }))
    expect(count()).toBe(2)
    fireEvent.click(screen.getByRole('button', { name: 'Take the counter out of box 2' }))
    expect(count()).toBe(1)
  })

  it('reaches every count from 0 to the frames’ size with taps alone, never a drag', () => {
    const counts = vi.fn()
    render(<Builder frames={2} onCount={counts} />)
    for (let i = 0; i < 25; i += 1) fireEvent.click(screen.getByRole('button', { name: 'Put in a counter' }))
    expect(count()).toBe(20)
    for (let i = 0; i < 25; i += 1) fireEvent.click(screen.getByRole('button', { name: 'Take one out' }))
    expect(count()).toBe(0)
    expect(new Set(counts.mock.calls.map((c) => c[0]))).toEqual(new Set(Array.from({ length: 21 }, (_, i) => i)))
  })

  it('drags a counter from the tray onto the frame, and one off the frame', () => {
    render(<Builder start={3} />)
    const frame = screen.getByTestId('math-build-frame')
    const tray = screen.getByTestId('math-tray')
    const outside = document.body
    const at = (x: number, y: number) => ({ clientX: x, clientY: y, pointerId: 1, pointerType: 'touch' })
    document.elementFromPoint = vi.fn(() => frame.querySelector('button')) as typeof document.elementFromPoint
    fireEvent.pointerDown(tray, at(10, 300))
    fireEvent.pointerMove(tray, at(60, 120))
    fireEvent.pointerUp(tray, at(60, 120))
    // The click a touch drag can be followed by does not move a second counter.
    fireEvent.click(tray)
    expect(count()).toBe(4)
    const full = screen.getByRole('button', { name: 'Take the counter out of box 4' })
    document.elementFromPoint = vi.fn(() => outside) as typeof document.elementFromPoint
    fireEvent.pointerDown(full, at(60, 120))
    fireEvent.pointerMove(full, at(60, 400))
    fireEvent.pointerUp(full, at(60, 400))
    expect(count()).toBe(3)
    // A drag that lands back on the frame moves nothing.
    document.elementFromPoint = vi.fn(() => frame) as typeof document.elementFromPoint
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Take the counter out of box 3' }), at(60, 120))
    fireEvent.pointerUp(frame, at(100, 120))
    expect(count()).toBe(3)
    // A plain tap still works after a drag.
    fireEvent.pointerDown(tray, at(10, 300))
    fireEvent.pointerUp(tray, at(10, 300))
    fireEvent.click(tray)
    expect(count()).toBe(4)
  })

  it('shows the target faintly in Together and keeps the first counters red', () => {
    const { container } = render(<Builder start={2} ghost={6} />)
    expect(container.querySelectorAll('[data-ghost]')).toHaveLength(4)
    expect(container.querySelectorAll('[data-full] [data-counter="red"]')).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: 'Put in a counter' }))
    expect(container.querySelectorAll('[data-full] [data-counter="yellow"]')).toHaveLength(1)
  })

  it('does nothing while disabled', () => {
    const onChange = vi.fn()
    render(<TenFrameBuilder frames={1} start={0} count={2} onChange={onChange} disabled />)
    fireEvent.click(screen.getByRole('button', { name: 'Put a counter in box 3' }))
    fireEvent.click(screen.getByRole('button', { name: 'Put in a counter' }))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('outlines the counters to take away in Together, since those boxes start full', () => {
    const { container } = render(<Builder start={9} ghost={5} takeAway />)
    const marked = Array.from(container.querySelectorAll('[data-remove]'))
    expect(marked.map((el) => el.getAttribute('aria-label'))).toEqual(
      ['Take this counter away, box 6', 'Take this counter away, box 7', 'Take this counter away, box 8', 'Take this counter away, box 9'])
    for (const el of marked) expect(el.className).toMatch(/border-dashed/)
    expect(container.querySelectorAll('[data-ghost]')).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Take one out' }))
    expect(container.querySelectorAll('[data-remove]')).toHaveLength(3)
    cleanup()
    // Your turn has no guide at all; building up keeps its empty-box outline.
    const quiet = render(<Builder start={9} takeAway />)
    expect(quiet.container.querySelectorAll('[data-remove], [data-ghost]')).toHaveLength(0)
  })

  it('turns a frame on its side (two across, five down) when five boxes do not fit, by a rem container query', () => {
    // jsdom evaluates no CSS, so this pins the contract; the layout itself
    // was measured in Chromium (see docs/K2_PRACTICE.md §5.3).
    render(<><Builder frames={2} /><MathPicture d={{ kind: 'ten_frame', frames: 2, red: 12 }} /></>)
    const rem = (grid: string) => Number(grid.match(/@container\(max-width:([\d.]+)rem\)/)?.[1])
    for (const [grid, box, gap] of [[BUILD_FRAME_GRID, 3.5, 0.5], [PICTURE_FRAME_GRID, 2.75, 0.25]] as const) {
      for (const cls of ['grid-cols-2', 'grid-rows-5', 'grid-flow-col']) {
        expect(grid).toContain(`[@container(max-width:${rem(grid)}rem)]:${cls}`)
      }
      expect(grid).toMatch(/\bgrid-cols-5\b/)
      // Never a viewport breakpoint: those do not follow the app's text size.
      expect(grid).not.toMatch(/\b(sm|md|lg|xl):/)
      // The switch happens before five boxes, their gaps, the padding and the
      // 4px border (at most 0.25rem at any supported size) stop fitting.
      expect(rem(grid)).toBeGreaterThanOrEqual(5 * box + 4 * gap + 0.5 + 0.25)
    }
    const builderGrids = document.querySelectorAll('[data-testid="math-build-frame"] > div')
    const pictureGrids = document.querySelectorAll('[data-testid="math-ten-frame"] > div')
    expect(builderGrids).toHaveLength(2)
    for (const g of builderGrids) expect(g.className).toContain(BUILD_FRAME_GRID)
    for (const g of pictureGrids) expect(g.className).toContain(PICTURE_FRAME_GRID)
    // Each frame's wrapper is the query container and spans the space it has.
    for (const id of ['math-build-frame', 'math-ten-frame']) {
      expect(screen.getByTestId(id).parentElement!.className).toContain(FRAME_CONTAINER)
    }
    expect(FRAME_CONTAINER).toContain('[container-type:inline-size]')
    expect(FRAME_CONTAINER).toContain('w-full')
  })

  it('meets the target sizes by class contract, wraps, and keeps targets 8px apart', () => {
    render(<Builder frames={2} />)
    for (const button of screen.getAllByRole('button')) {
      expect(button.className, button.outerHTML).toMatch(/min-h-14/)
      expect(button.className, button.outerHTML).toMatch(/min-w-14/)
    }
    for (const grid of document.querySelectorAll('[data-testid="math-build-frame"] .grid')) {
      expect(grid.className).toMatch(/\bgap-2\b/)
    }
    const source = readFileSync(join(__dirname, 'MathPieces.tsx'), 'utf8')
    expect(source).not.toMatch(/\b(w|min-w|max-w|h|min-h)-\[\d+px\]/)
    expect(source).not.toMatch(/style=\{\{[^}]*(width|height)\s*:\s*\d/)
    expect(source).not.toMatch(/framer-motion|react-spring|gsap|lottie/)
    // Pieces you can drag never let the page scroll instead.
    expect(screen.getByTestId('math-tray').className).toContain('touch-none')
  })
})
