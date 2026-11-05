import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import './i18n'
import Diagram, { ACTIONS, COINS, ICONS, WIKI_SUMMARY, diagramMarkup, lookupImage, type DiagramSpec } from './Diagram'

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
  { kind: 'pictures', groups: [{ icon: 'apple', count: 3, label: 'A' }, { icon: 'bee', count: 1, label: 'B' }] },
  { kind: 'scene', icon: 'duck', action: 'swimming' },
  { kind: 'timeline', events: [{ label: 'Rome founded', year: -753 }, { label: 'Magna Carta', year: 1215 }], show_years: true },
  { kind: 'venn', left: 'Frogs', right: 'Fish', left_items: ['legs'], right_items: ['fins'], both_items: ['live in water'] },
  { kind: 'table', header: ['Planet', 'Moons'], rows: [['Earth', '1'], ['Mars', '2']] },
  { kind: 'cycle', steps: ['evaporation', 'condensation', '?', 'collection'] },
  { kind: 'sequence', steps: ['seed', 'sprout', 'plant'] },
  { kind: 'ruler', unit: 'cm', length: 15, objects: [{ label: 'crayon', start: 0, end: 9, icon: 'crayon' }, { label: 'linking cube', start: 9, end: 11 }] },
  { kind: 'money', pieces: [{ coin: 'quarter', count: 2 }, { coin: 'one_bill', count: 1 }] },
  { kind: 'thermometer', unit: 'F', low: 0, high: 100, step: 10, reading: 60 },
]
// The one kind that is not drawn here: a real picture fetched from Wikimedia Commons.
const image: DiagramSpec = { kind: 'image', wiki_title: 'Battle of Hastings', caption: 'The Battle of Hastings' }

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

  it('draws pictures of things for any subject, and nothing for a name it does not know', () => {
    const { container } = render(<Diagram d={{ kind: 'pictures', groups: [{ icon: 'apple', count: 3 }] }} />)
    expect([...container.querySelectorAll('text')].filter((t) => t.textContent === ICONS.apple)).toHaveLength(3)
    cleanup()
    const scene = render(<Diagram d={{ kind: 'scene', icon: 'duck', action: 'swimming' }} />)
    expect(scene.getByRole('img', { name: 'A picture of a duck swimming' })).toBeTruthy()
    cleanup()
    const unknown = render(<Diagram d={{ kind: 'scene', icon: 'unicorn' }} />)
    expect(unknown.container.querySelector('svg')).toBeNull()
  })

  it('shows a blank step as a blank, and puts timeline events in order', () => {
    const { container } = render(<Diagram d={{ kind: 'cycle', steps: ['rain', '?', 'clouds'] }} />)
    expect([...container.querySelectorAll('rect')].some((r) => r.getAttribute('stroke-dasharray'))).toBe(true)
    cleanup()
    const line = render(<Diagram d={{ kind: 'timeline', events: [{ label: 'later', year: 1900 }, { label: 'earlier', year: -50 }], show_years: true }} />)
    const texts = [...line.container.querySelectorAll('text')].map((t) => t.textContent)
    expect(texts.indexOf('earlier')).toBeLessThan(texts.indexOf('later'))
    expect(texts).toContain('50 BC')
  })

  it('lays each thing along the ruler from its start to its end', () => {
    const { container } = render(<Diagram d={{ kind: 'ruler', unit: 'cm', length: 10, objects: [{ label: 'crayon', start: 2, end: 7 }] }} />)
    const bar = container.querySelector('rect[rx="6"]')!
    const numbers = [...container.querySelectorAll('text')].filter((t) => /^\d+$/.test(t.textContent ?? ''))
    const at = (n: string) => Number(numbers.find((t) => t.textContent === n)!.getAttribute('x'))
    expect(Number(bar.getAttribute('x'))).toBeCloseTo(at('2'))
    expect(Number(bar.getAttribute('x')) + Number(bar.getAttribute('width'))).toBeCloseTo(at('7'))
  })

  it('draws one coin or bill per piece, showing what each is worth', () => {
    const { container } = render(<Diagram d={{ kind: 'money', pieces: [{ coin: 'quarter', count: 2 }, { coin: 'dime', count: 1 }] }} />)
    expect([...container.querySelectorAll('text')].map((t) => t.textContent)).toEqual(['25¢', '25¢', '10¢'])
  })

  describe('real pictures from Wikimedia Commons', () => {
    const summary = (body: object) => vi.fn(async () => new Response(JSON.stringify(body), { status: 200 }))

    it('shows a freely licensed Commons picture with its credit, and prints it once shown', async () => {
      const fetchMock = summary({ type: 'standard', title: 'Battle of Hastings', thumbnail: { source: 'https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Bayeux.jpg/320px-Bayeux.jpg' } })
      vi.stubGlobal('fetch', fetchMock)
      render(<Diagram d={image} />)
      const img = await screen.findByAltText('The Battle of Hastings')
      expect(img.getAttribute('src')).toContain('/wikipedia/commons/')
      expect(screen.getByText(/Wikimedia Commons, from the Wikipedia article “Battle of Hastings”/)).toBeTruthy()
      expect(fetchMock).toHaveBeenCalledWith(`${WIKI_SUMMARY}Battle_of_Hastings`)
      expect(diagramMarkup(image)).toContain('<img src="https://upload.wikimedia.org/wikipedia/commons/')
      vi.unstubAllGlobals()
    })

    it.each([
      ['a non-free English Wikipedia upload', { type: 'standard', thumbnail: { source: 'https://upload.wikimedia.org/wikipedia/en/a/ab/Poster.jpg' } }],
      ['a disambiguation page', { type: 'disambiguation', thumbnail: { source: 'https://upload.wikimedia.org/wikipedia/commons/x.jpg' } }],
      ['an article with no picture', { type: 'standard' }],
      ['a picture from anywhere else', { type: 'standard', thumbnail: { source: 'https://evil.example/x.jpg' } }],
    ])('shows the words instead of %s', async (_what, body) => {
      vi.stubGlobal('fetch', summary(body))
      const title = `Test ${Math.random()}`
      expect(await lookupImage(title)).toBeNull()
      render(<Diagram d={{ kind: 'image', wiki_title: title, caption: 'A caption' }} />)
      expect(screen.getByText('A caption')).toBeTruthy()
      expect(document.querySelector('img')).toBeNull()
      vi.unstubAllGlobals()
    })

    it('shows the words when Wikipedia cannot be reached, and prints the words before a lookup', async () => {
      vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Load failed') }))
      expect(await lookupImage('Unreachable Place')).toBeNull()
      expect(diagramMarkup({ kind: 'image', wiki_title: 'Never Looked Up', caption: 'A <b>caption</b>' })).toBe('<div class="diagram"><p><em>A &lt;b&gt;caption&lt;/b&gt;</em></p></div>')
      vi.unstubAllGlobals()
    })

    it('asks the same Wikipedia origin picture study already asks', () => {
      const card = readFileSync(resolve(__dirname, 'VisualAidCard.tsx'), 'utf8')
      expect(card).toContain(new URL(WIKI_SUMMARY).origin)
    })
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
    expect(kinds.sort()).toEqual([...every, image].map((d) => d.kind).sort())
    const list = (name: string) => py.match(new RegExp(`^${name} = \\(([^)]*)\\)`, 'm'))?.[1].match(/"(\w+)"/g)?.map((k) => k.slice(1, -1)) ?? []
    expect(list('ICONS').sort()).toEqual(Object.keys(ICONS).sort())
    expect(list('ACTIONS').sort()).toEqual(Object.keys(ACTIONS).sort())
    const cents = Object.fromEntries([...(py.match(/^COIN_CENTS = \{([^}]*)\}/m)?.[1] ?? '').matchAll(/"(\w+)": (\d+)/g)].map((m) => [m[1], Number(m[2])]))
    expect(Object.fromEntries(Object.entries(COINS).map(([k, v]) => [k, v.cents]))).toEqual(cents)
  })
})
