import type { ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { useTranslation } from 'react-i18next'

/**
 * Draws a maths picture from a diagram: a closed list of kinds holding only
 * numbers and short labels (models/practice.py). Nothing a model wrote is
 * ever inserted as markup; every shape is built here and every label is a
 * React text node, so it is escaped. The backend works the answer out from
 * the same numbers (services/practice/diagrams.py), so the picture and the
 * answer key cannot disagree.
 *
 * Mirrored in demo/src/Diagram.tsx; demo/src/Diagram.test.tsx keeps the two
 * the same.
 */

export type DiagramSpec =
  | { kind: 'fraction_bar' | 'fraction_circle'; parts: number; shaded: number }
  | { kind: 'array'; rows: number; cols: number }
  | { kind: 'base_ten'; hundreds: number; tens: number; ones: number }
  | { kind: 'clock'; hour: number; minute: number }
  | { kind: 'rectangle'; width: number; height: number; unit?: string }
  | { kind: 'right_triangle'; base: number; height: number; unit?: string }
  | { kind: 'number_line'; start: number; end: number; step: number; marks: number[]; mark_labels: string[] }
  | { kind: 'bar_graph'; title?: string; bars: { label: string; value: number }[] }
  | { kind: 'coordinate_plane'; size: number; four_quadrants: boolean; points: { label: string; x: number; y: number }[] }

const INK = '#1f2a44'
const FILL = '#8fa37a'
const PAPER = '#ffffff'
const FONT = { fontFamily: 'system-ui, sans-serif', fontSize: 13, fill: INK } as const

const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, Math.round(Number(n) || 0)))

function FractionBar({ parts, shaded }: { parts: number; shaded: number }) {
  const p = clamp(parts, 1, 24)
  const s = clamp(shaded, 0, p)
  const w = 300 / p
  return (
    <svg viewBox="0 0 320 60" width="320" height="60">
      {Array.from({ length: p }, (_, i) => (
        <rect key={i} x={10 + i * w} y={10} width={w} height={40} fill={i < s ? FILL : PAPER} stroke={INK} strokeWidth={2} />
      ))}
    </svg>
  )
}

function FractionCircle({ parts, shaded }: { parts: number; shaded: number }) {
  const p = clamp(parts, 1, 24)
  const s = clamp(shaded, 0, p)
  const r = 60, cx = 70, cy = 70
  const at = (i: number) => {
    const a = (i / p) * 2 * Math.PI - Math.PI / 2
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)]
  }
  return (
    <svg viewBox="0 0 140 140" width="140" height="140">
      {p === 1
        ? <circle cx={cx} cy={cy} r={r} fill={s ? FILL : PAPER} stroke={INK} strokeWidth={2} />
        : Array.from({ length: p }, (_, i) => {
          const [x1, y1] = at(i)
          const [x2, y2] = at(i + 1)
          const large = 1 / p > 0.5 ? 1 : 0
          return <path key={i} d={`M${cx},${cy} L${x1},${y1} A${r},${r} 0 ${large} 1 ${x2},${y2} Z`}
            fill={i < s ? FILL : PAPER} stroke={INK} strokeWidth={2} />
        })}
    </svg>
  )
}

function DotArray({ rows, cols }: { rows: number; cols: number }) {
  const r = clamp(rows, 1, 12), c = clamp(cols, 1, 12)
  return (
    <svg viewBox={`0 0 ${c * 24 + 8} ${r * 24 + 8}`} width={c * 24 + 8} height={r * 24 + 8}>
      {Array.from({ length: r * c }, (_, i) => (
        <circle key={i} cx={16 + (i % c) * 24} cy={16 + Math.floor(i / c) * 24} r={7} fill={INK} />
      ))}
    </svg>
  )
}

function BaseTen({ hundreds, tens, ones }: { hundreds: number; tens: number; ones: number }) {
  const h = clamp(hundreds, 0, 9), t = clamp(tens, 0, 9), o = clamp(ones, 0, 9)
  const unit = 6
  const shapes: ReactElement[] = []
  let x = 6
  for (let i = 0; i < h; i++) {
    for (let k = 0; k < 100; k++) {
      shapes.push(<rect key={`h${i}-${k}`} x={x + (k % 10) * unit} y={6 + Math.floor(k / 10) * unit} width={unit} height={unit} fill={FILL} stroke={INK} strokeWidth={0.5} />)
    }
    x += unit * 10 + 10
  }
  for (let i = 0; i < t; i++) {
    for (let k = 0; k < 10; k++) {
      shapes.push(<rect key={`t${i}-${k}`} x={x} y={6 + k * unit} width={unit} height={unit} fill={FILL} stroke={INK} strokeWidth={0.5} />)
    }
    x += unit + 6
  }
  x += 4
  for (let i = 0; i < o; i++) {
    shapes.push(<rect key={`o${i}`} x={x + (i % 3) * (unit + 4)} y={6 + Math.floor(i / 3) * (unit + 4)} width={unit} height={unit} fill={FILL} stroke={INK} strokeWidth={0.5} />)
  }
  const width = x + 3 * (unit + 4) + 6
  return <svg viewBox={`0 0 ${width} ${unit * 10 + 12}`} width={width} height={unit * 10 + 12}>{shapes}</svg>
}

function Clock({ hour, minute }: { hour: number; minute: number }) {
  const h = clamp(hour, 1, 12), m = clamp(minute, 0, 59)
  const cx = 70, cy = 70
  const hand = (turns: number, len: number) => {
    const a = turns * 2 * Math.PI - Math.PI / 2
    return { x2: cx + len * Math.cos(a), y2: cy + len * Math.sin(a) }
  }
  return (
    <svg viewBox="0 0 140 140" width="140" height="140">
      <circle cx={cx} cy={cy} r={62} fill={PAPER} stroke={INK} strokeWidth={3} />
      {Array.from({ length: 12 }, (_, i) => {
        const a = ((i + 1) / 12) * 2 * Math.PI - Math.PI / 2
        return <text key={i} x={cx + 50 * Math.cos(a)} y={cy + 50 * Math.sin(a) + 5} textAnchor="middle" {...FONT}>{i + 1}</text>
      })}
      <line x1={cx} y1={cy} {...hand(((h % 12) + m / 60) / 12, 30)} stroke={INK} strokeWidth={5} strokeLinecap="round" />
      <line x1={cx} y1={cy} {...hand(m / 60, 46)} stroke={INK} strokeWidth={3} strokeLinecap="round" />
      <circle cx={cx} cy={cy} r={4} fill={INK} />
    </svg>
  )
}

function Rect({ width, height, unit }: { width: number; height: number; unit?: string }) {
  const w = clamp(width, 1, 100), h = clamp(height, 1, 100)
  const scale = 180 / Math.max(w, h)
  const pw = Math.max(30, w * scale), ph = Math.max(30, h * scale)
  const u = unit ? ` ${unit}` : ''
  return (
    <svg viewBox={`0 0 ${pw + 80} ${ph + 50}`} width={pw + 80} height={ph + 50}>
      <rect x={20} y={10} width={pw} height={ph} fill={PAPER} stroke={INK} strokeWidth={2} />
      <text x={20 + pw / 2} y={ph + 32} textAnchor="middle" {...FONT}>{w}{u}</text>
      <text x={pw + 28} y={10 + ph / 2 + 5} {...FONT}>{h}{u}</text>
    </svg>
  )
}

function RightTriangle({ base, height, unit }: { base: number; height: number; unit?: string }) {
  const b = clamp(base, 1, 100), h = clamp(height, 1, 100)
  const scale = 180 / Math.max(b, h)
  const pb = Math.max(30, b * scale), ph = Math.max(30, h * scale)
  const u = unit ? ` ${unit}` : ''
  return (
    <svg viewBox={`0 0 ${pb + 80} ${ph + 50}`} width={pb + 80} height={ph + 50}>
      <polygon points={`20,${10 + ph} ${20 + pb},${10 + ph} 20,10`} fill={PAPER} stroke={INK} strokeWidth={2} />
      <rect x={20} y={ph - 2} width={12} height={12} fill="none" stroke={INK} strokeWidth={1} />
      <text x={20 + pb / 2} y={ph + 32} textAnchor="middle" {...FONT}>{b}{u}</text>
      <text x={0} y={10 + ph / 2} {...FONT}>{h}{u}</text>
    </svg>
  )
}

function NumberLine({ start, end, step, marks, mark_labels: labels }: { start: number; end: number; step: number; marks: number[]; mark_labels: string[] }) {
  const s = Math.round(start), e = Math.round(end), st = Math.max(1, Math.round(step))
  const ticks: number[] = []
  for (let v = s; v <= e && ticks.length <= 40; v += st) ticks.push(v)
  const x = (v: number) => 20 + ((v - s) / Math.max(1, e - s)) * 340
  // With lettered points, only the ends are numbered, so the question is a real one.
  const lettered = (labels ?? []).length > 0
  return (
    <svg viewBox="0 0 380 80" width="380" height="80">
      <line x1={10} y1={40} x2={370} y2={40} stroke={INK} strokeWidth={2} />
      {ticks.map((v, i) => (
        <g key={v}>
          <line x1={x(v)} y1={32} x2={x(v)} y2={48} stroke={INK} strokeWidth={2} />
          {(!lettered || i === 0 || i === ticks.length - 1) && <text x={x(v)} y={68} textAnchor="middle" {...FONT}>{v}</text>}
        </g>
      ))}
      {(marks ?? []).slice(0, 4).map((v, i) => (
        <g key={`m${i}`}>
          <circle cx={x(v)} cy={40} r={6} fill={FILL} stroke={INK} strokeWidth={2} />
          {lettered && <text x={x(v)} y={22} textAnchor="middle" {...FONT} fontWeight="bold">{(labels[i] ?? '').slice(0, 3)}</text>}
        </g>
      ))}
    </svg>
  )
}

function BarGraph({ title, bars }: { title?: string; bars: { label: string; value: number }[] }) {
  const list = (bars ?? []).slice(0, 8)
  const top = Math.max(1, ...list.map((b) => b.value))
  const step = top <= 10 ? 1 : top <= 20 ? 2 : top <= 50 ? 5 : top <= 100 ? 10 : Math.ceil(top / 10)
  const ceiling = Math.ceil(top / step) * step
  const y = (v: number) => 170 - (v / ceiling) * 140
  const lines: number[] = []
  for (let v = 0; v <= ceiling; v += step) lines.push(v)
  return (
    <svg viewBox={`0 0 ${60 + list.length * 60} 210`} width={60 + list.length * 60} height={210}>
      {title && <text x={40} y={16} {...FONT} fontWeight="bold">{title.slice(0, 40)}</text>}
      {lines.map((v) => (
        <g key={v}>
          <line x1={40} y1={y(v)} x2={40 + list.length * 60} y2={y(v)} stroke="#d0d4dc" strokeWidth={1} />
          <text x={34} y={y(v) + 4} textAnchor="end" {...FONT}>{v}</text>
        </g>
      ))}
      {list.map((b, i) => (
        <g key={i}>
          <rect x={50 + i * 60} y={y(b.value)} width={40} height={170 - y(b.value)} fill={FILL} stroke={INK} strokeWidth={1.5} />
          <text x={70 + i * 60} y={190} textAnchor="middle" {...FONT}>{b.label.slice(0, 12)}</text>
        </g>
      ))}
      <line x1={40} y1={170} x2={40 + list.length * 60} y2={170} stroke={INK} strokeWidth={2} />
    </svg>
  )
}

function Plane({ size, four_quadrants: four, points }: { size: number; four_quadrants: boolean; points: { label: string; x: number; y: number }[] }) {
  const n = clamp(size, 2, 10)
  const lo = four ? -n : 0
  const cell = (four ? 120 : 220) / n
  const span = (n - lo) * cell
  const px = (v: number) => 24 + (v - lo) * cell
  const py = (v: number) => 12 + (n - v) * cell
  const grid: ReactElement[] = []
  for (let v = lo; v <= n; v++) {
    grid.push(<line key={`v${v}`} x1={px(v)} y1={py(n)} x2={px(v)} y2={py(lo)} stroke={v === 0 ? INK : '#d0d4dc'} strokeWidth={v === 0 ? 2 : 1} />)
    grid.push(<line key={`h${v}`} x1={px(lo)} y1={py(v)} x2={px(n)} y2={py(v)} stroke={v === 0 ? INK : '#d0d4dc'} strokeWidth={v === 0 ? 2 : 1} />)
    grid.push(<text key={`xl${v}`} x={px(v)} y={py(four ? 0 : lo) + 16} textAnchor="middle" {...FONT} fontSize={10}>{v}</text>)
    if (v !== 0) grid.push(<text key={`yl${v}`} x={px(four ? 0 : lo) - 6} y={py(v) + 4} textAnchor="end" {...FONT} fontSize={10}>{v}</text>)
  }
  return (
    <svg viewBox={`0 0 ${span + 48} ${span + 40}`} width={span + 48} height={span + 40}>
      {grid}
      {(points ?? []).slice(0, 6).map((p, i) => (
        <g key={i}>
          <circle cx={px(clamp(p.x, lo, n))} cy={py(clamp(p.y, lo, n))} r={5} fill={FILL} stroke={INK} strokeWidth={2} />
          <text x={px(clamp(p.x, lo, n)) + 8} y={py(clamp(p.y, lo, n)) - 6} {...FONT} fontWeight="bold">{p.label.slice(0, 3)}</text>
        </g>
      ))}
    </svg>
  )
}

/** What the picture shows, in words, for a screen reader. */
export function describe(d: DiagramSpec, t: (key: string, values?: Record<string, unknown>) => string): string {
  switch (d.kind) {
    case 'fraction_bar': return t('diagram.fractionBar', { parts: d.parts, shaded: d.shaded })
    case 'fraction_circle': return t('diagram.fractionCircle', { parts: d.parts, shaded: d.shaded })
    case 'array': return t('diagram.array', { rows: d.rows, cols: d.cols })
    case 'base_ten': return t('diagram.baseTen', { hundreds: d.hundreds, tens: d.tens, ones: d.ones })
    case 'clock': return t('diagram.clock', { hour: d.hour, minute: d.minute })
    case 'rectangle': return t('diagram.rectangle', { width: d.width, height: d.height, unit: d.unit ?? '' })
    case 'right_triangle': return t('diagram.rightTriangle', { base: d.base, height: d.height, unit: d.unit ?? '' })
    case 'number_line': return t('diagram.numberLine', { start: d.start, end: d.end, step: d.step, points: (d.mark_labels ?? []).join(', ') || d.marks.join(', ') })
    case 'bar_graph': return t('diagram.barGraph', { bars: d.bars.map((b) => `${b.label} ${b.value}`).join(', ') })
    case 'coordinate_plane': return t('diagram.plane', { points: d.points.map((p) => p.label).join(', ') })
  }
}

export function DiagramSvg({ d }: { d: DiagramSpec }) {
  switch (d.kind) {
    case 'fraction_bar': return <FractionBar parts={d.parts} shaded={d.shaded} />
    case 'fraction_circle': return <FractionCircle parts={d.parts} shaded={d.shaded} />
    case 'array': return <DotArray rows={d.rows} cols={d.cols} />
    case 'base_ten': return <BaseTen hundreds={d.hundreds} tens={d.tens} ones={d.ones} />
    case 'clock': return <Clock hour={d.hour} minute={d.minute} />
    case 'rectangle': return <Rect width={d.width} height={d.height} unit={d.unit} />
    case 'right_triangle': return <RightTriangle base={d.base} height={d.height} unit={d.unit} />
    case 'number_line': return <NumberLine {...d} />
    case 'bar_graph': return <BarGraph title={d.title} bars={d.bars} />
    case 'coordinate_plane': return <Plane {...d} />
    default: return null
  }
}

export default function Diagram({ d }: { d?: DiagramSpec | null }) {
  const { t } = useTranslation()
  if (!d) return null
  return (
    <figure role="img" aria-label={describe(d, t)} className="my-2 max-w-full overflow-x-auto">
      <DiagramSvg d={d} />
    </figure>
  )
}

/** The same picture as SVG markup, for a printed worksheet. React builds and
 *  escapes it, so no model text is ever written into the page as markup. */
export function diagramMarkup(d?: DiagramSpec | null): string {
  return d ? `<div class="diagram">${renderToStaticMarkup(<DiagramSvg d={d} />)}</div>` : ''
}
