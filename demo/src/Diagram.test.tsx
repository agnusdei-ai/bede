import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import './i18n'
import Diagram, { diagramMarkup, type DiagramSpec } from './Diagram'

afterEach(cleanup)

const every: DiagramSpec[] = [
  { kind: 'fraction_bar', parts: 4, shaded: 3 },
  { kind: 'fraction_circle', parts: 6, shaded: 2 },
  { kind: 'array', rows: 3, cols: 4 },
  { kind: 'base_ten', hundreds: 2, tens: 3, ones: 4 },
  { kind: 'clock', hour: 3, minute: 15 },
  { kind: 'rectangle', width: 5, height: 3, unit: 'cm' },
  { kind: 'right_triangle', base: 6, height: 4, unit: 'm' },
  { kind: 'number_line', start: 0, end: 10, step: 2, marks: [6], mark_labels: ['A'] },
  { kind: 'bar_graph', title: 'Pets', bars: [{ label: 'cats', value: 4 }, { label: 'dogs', value: 6 }] },
  { kind: 'coordinate_plane', size: 5, four_quadrants: false, points: [{ label: 'A', x: 3, y: 2 }] },
]

describe('drawn diagrams', () => {
  it.each(every.map((d) => [d.kind, d] as const))('draws a %s with a spoken description', (_kind, d) => {
    render(<Diagram d={d} />)
    const figure = screen.getByRole('img')
    expect(figure.getAttribute('aria-label')).toBeTruthy()
    expect(figure.querySelector('svg')).not.toBeNull()
  })

  it('shades exactly the parts the diagram says', () => {
    const { container } = render(<Diagram d={{ kind: 'fraction_bar', parts: 5, shaded: 2 }} />)
    const rects = [...container.querySelectorAll('rect')]
    expect(rects).toHaveLength(5)
    expect(rects.filter((r) => r.getAttribute('fill') !== '#ffffff')).toHaveLength(2)
  })

  it('draws one dot per array place', () => {
    const { container } = render(<Diagram d={{ kind: 'array', rows: 3, cols: 4 }} />)
    expect(container.querySelectorAll('circle')).toHaveLength(12)
  })

  it('numbers only the ends of a lettered number line, so the question stays a question', () => {
    const { container } = render(<Diagram d={{ kind: 'number_line', start: 0, end: 10, step: 2, marks: [6], mark_labels: ['A'] }} />)
    const texts = [...container.querySelectorAll('text')].map((t) => t.textContent)
    expect(texts).toEqual(['0', '10', 'A'])
  })

  it('never writes a label as markup, on screen or in print', () => {
    const evil: DiagramSpec = { kind: 'bar_graph', title: '<img src=x onerror=alert(1)>', bars: [{ label: '<script>', value: 3 }] }
    const { container } = render(<Diagram d={evil} />)
    expect(container.querySelector('script, img')).toBeNull()
    const printed = diagramMarkup(evil)
    expect(printed).not.toContain('<script>')
    expect(printed).not.toContain('<img')
    expect(printed).toContain('&lt;script&gt;')
  })

  it('draws nothing for an unknown kind or no diagram', () => {
    const { container } = render(<Diagram d={{ kind: 'svg' } as unknown as DiagramSpec} />)
    expect(container.querySelector('svg')).toBeNull()
    expect(diagramMarkup(null)).toBe('')
  })

  it('is the same component as the app copy, and covers every kind the API allows', () => {
    const strip = (s: string) => s.replace(/^ \* Mirror[^\n]*\n[^\n]*\n/m, '').replace(/^ \* Mirrored[^\n]*\n[^\n]*\n/m, '')
    const demo = readFileSync(resolve(__dirname, 'Diagram.tsx'), 'utf8')
    const app = readFileSync(resolve(__dirname, '../../homeschool-tutor/src/components/Diagram.tsx'), 'utf8')
    expect(strip(demo)).toBe(strip(app))
    const py = readFileSync(resolve(__dirname, '../../homeschool-api/models/practice.py'), 'utf8')
    const kinds = py.match(/^DIAGRAM_KINDS = \(([^)]*)\)/m)?.[1].match(/"(\w+)"/g)?.map((k) => k.slice(1, -1)) ?? []
    expect(kinds.sort()).toEqual(every.map((d) => d.kind).sort())
  })
})
