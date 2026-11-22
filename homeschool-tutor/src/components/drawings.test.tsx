import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { DRAWINGS, DRAWING_PALETTE } from './drawings'
import Diagram, { ICONS, Picture } from './Diagram'

const PATH = /^[MmLlHhVvCcSsQqTtAaZz0-9.,\s-]+$/

describe("Bede's hand-drawn pictures", () => {
  it('has a drawing for every picture name the API accepts, and nothing else', () => {
    const py = readFileSync(resolve(import.meta.dirname, '../../../homeschool-api/models/practice.py'), 'utf8')
    const icons = py.match(/^ICONS = \(([^)]*)\)/m)?.[1].match(/"(\w+)"/g)?.map((k) => k.slice(1, -1)) ?? []
    expect(icons.length).toBeGreaterThan(100)
    expect(Object.keys(DRAWINGS).sort()).toEqual([...icons].sort())
    expect(Object.keys(DRAWINGS).sort()).toEqual(Object.keys(ICONS).sort())
  })

  it('holds only path data and palette colours, so no text or markup can reach a picture', () => {
    for (const [name, d] of Object.entries(DRAWINGS)) {
      for (const p of [d.ink, d.bold, d.thin, d.fine, d.hatch, d.cross, ...d.wash.map(([w]) => w)]) {
        if (p !== undefined) expect(p, name).toMatch(PATH)
      }
      for (const [, colour] of d.wash) expect(DRAWING_PALETTE, `${name} ${colour}`).toHaveProperty(colour)
      for (const dot of d.dots ?? []) expect(dot.every((n) => Number.isFinite(n)), name).toBe(true)
    }
  })

  it('draws a picture, not the word, and writes no text inside it', () => {
    const { container } = render(<Picture name="fox" label="fox" size="h-24 w-24" />)
    const svg = container.querySelector('svg[role="img"]')
    expect(svg).not.toBeNull()
    expect(svg?.getAttribute('aria-label')).toBe('fox')
    expect(container.textContent).toBe('')
    expect(svg?.querySelector('text')).toBeNull()
  })

  it('draws the small rendering inside a pictures diagram, with no filters or hatching', () => {
    const { container } = render(<Diagram d={{ kind: 'pictures', groups: [{ icon: 'apple', count: 3 }] }} />)
    const pictures = container.querySelectorAll('svg svg')
    expect(pictures).toHaveLength(3)
    for (const p of pictures) {
      expect(p.querySelector('[filter], defs')).toBeNull()
      expect(p.querySelector('path')).not.toBeNull()
    }
  })

  it('carries its own filters at full size, so a printed copy draws the same', () => {
    const { container } = render(<Diagram d={{ kind: 'scene', icon: 'horse', action: 'running' }} />)
    const inner = container.querySelector('svg svg')
    expect(inner?.querySelector('filter#bede-ink')).not.toBeNull()
    expect(inner?.querySelector('pattern#bede-hatch')).not.toBeNull()
  })
})
