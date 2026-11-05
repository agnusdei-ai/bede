import { useEffect, useState, type ReactElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { useTranslation } from 'react-i18next'

/**
 * Draws a question's picture, in any subject, from a diagram: a closed list of kinds holding only
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
  | { kind: 'pictures'; groups: { icon: string; count: number; label?: string }[] }
  | { kind: 'scene'; icon: string; action?: string | null }
  | { kind: 'timeline'; events: { label: string; year: number }[]; show_years: boolean }
  | { kind: 'venn'; left: string; right: string; left_items: string[]; right_items: string[]; both_items: string[] }
  | { kind: 'table'; header: string[]; rows: string[][] }
  | { kind: 'cycle' | 'sequence'; steps: string[] }
  | { kind: 'ruler'; unit: 'cm' | 'in'; length: number; objects: { label: string; start: number; end: number; icon?: string | null }[] }
  | { kind: 'money'; pieces: { coin: string; count: number }[] }
  | { kind: 'thermometer'; unit: 'F' | 'C'; low: number; high: number; step: number; reading: number }
  | { kind: 'image'; wiki_title: string; caption?: string }

/** Picture symbols for the API's ICONS (models/practice.py). A name not here draws nothing. */
export const ICONS: Record<string, string> = {
  dog: '🐕', cat: '🐈', mouse: '🐁', bird: '🐦', duck: '🦆', fish: '🐟', horse: '🐎', cow: '🐄', pig: '🐖',
  sheep: '🐑', goat: '🐐', chicken: '🐓', rabbit: '🐇', frog: '🐸', bee: '🐝', butterfly: '🦋', ant: '🐜',
  spider: '🕷️', snake: '🐍', turtle: '🐢', lion: '🦁', tiger: '🐅', elephant: '🐘', bear: '🐻', monkey: '🐒',
  owl: '🦉', whale: '🐋', wolf: '🐺', fox: '🦊', deer: '🦌',
  tree: '🌳', flower: '🌼', leaf: '🍃', seedling: '🌱', sun: '☀️', moon: '🌙', star: '⭐', cloud: '☁️',
  rain: '🌧️', snow: '❄️', lightning: '⚡', rainbow: '🌈', water: '💧', fire: '🔥', mountain: '⛰️',
  volcano: '🌋', wave: '🌊', rock: '🪨',
  apple: '🍎', banana: '🍌', grapes: '🍇', carrot: '🥕', bread: '🍞', cheese: '🧀', milk: '🥛', egg: '🥚',
  cake: '🍰', cookie: '🍪',
  house: '🏠', castle: '🏰', ship: '🚢', boat: '⛵', car: '🚗', bus: '🚌', train: '🚂', plane: '✈️',
  bicycle: '🚲', book: '📕', pencil: '✏️', scroll: '📜', crown: '👑', ball: '⚽', hat: '🎩', shoe: '👟',
  key: '🔑', bell: '🔔', lightbulb: '💡', magnet: '🧲', compass: '🧭', globe: '🌍', map: '🗺️', coin: '🪙',
  boy: '👦', girl: '👧', man: '👨', woman: '👩', baby: '👶', farmer: '🧑‍🌾', king: '🤴', queen: '👸',
  hand: '✋', eye: '👁️', ear: '👂', foot: '🦶', heart: '🫀', brain: '🧠', tooth: '🦷', bone: '🦴',
  magnifier: '🔍', microscope: '🔬', thermometer: '🌡️', battery: '🔋', plant: '🪴',
  crayon: '🖍️', paperclip: '📎', scissors: '✂️', spoon: '🥄', backpack: '🎒', chair: '🪑', bed: '🛏️',
  watermelon: '🍉', bucket: '🪣', television: '📺', computer: '💻', phone: '📱', cup: '☕', bottle: '🍼',
  toothbrush: '🪥', cube: '🟦', box: '📦', basket: '🧺', truck: '🚚', ruler: '📏',
}

/** Coins and bills (models/practice.py COIN_CENTS): what each is worth and how it is drawn. */
export const COINS: Record<string, { cents: number; bill?: boolean; r?: number }> = {
  penny: { cents: 1, r: 17 }, nickel: { cents: 5, r: 19 }, dime: { cents: 10, r: 16 },
  quarter: { cents: 25, r: 22 }, half_dollar: { cents: 50, r: 25 }, dollar_coin: { cents: 100, r: 24 },
  one_bill: { cents: 100, bill: true }, five_bill: { cents: 500, bill: true },
  ten_bill: { cents: 1000, bill: true }, twenty_bill: { cents: 2000, bill: true },
}

/** What an action looks like beside the thing doing it. */
export const ACTIONS: Record<string, string> = {
  running: '💨', swimming: '🌊', flying: '☁️', sleeping: '💤', eating: '🍽️', drinking: '💧',
  singing: '🎵', walking: '👣', reading: '📖', writing: '✏️',
}

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


const EMOJI = { fontFamily: '"Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif' } as const

function Pictures({ groups }: { groups: { icon: string; count: number; label?: string }[] }) {
  const list = (groups ?? []).slice(0, 6).filter((g) => ICONS[g.icon])
  const cols = (n: number) => Math.min(4, Math.max(1, n))
  const widths = list.map((g) => cols(clamp(g.count, 1, 12)) * 38 + 16)
  const total = widths.reduce((a, b) => a + b, 0) + 10
  const tallest = Math.max(1, ...list.map((g) => Math.ceil(clamp(g.count, 1, 12) / 4)))
  let x = 6
  return (
    <svg viewBox={`0 0 ${total} ${tallest * 40 + 34}`} width={total} height={tallest * 40 + 34}>
      {list.map((g, i) => {
        const n = clamp(g.count, 1, 12)
        const left = x
        x += widths[i]
        return (
          <g key={i}>
            {Array.from({ length: n }, (_, k) => (
              <text key={k} x={left + 8 + (k % 4) * 38} y={34 + Math.floor(k / 4) * 40} fontSize={30} {...EMOJI}>{ICONS[g.icon]}</text>
            ))}
            {g.label && <text x={left + widths[i] / 2 - 8} y={tallest * 40 + 26} textAnchor="middle" {...FONT} fontWeight="bold">{g.label.slice(0, 16)}</text>}
          </g>
        )
      })}
    </svg>
  )
}

function Scene({ icon, action }: { icon: string; action?: string | null }) {
  if (!ICONS[icon]) return null
  return (
    <svg viewBox="0 0 150 100" width="150" height="100">
      <text x={20} y={78} fontSize={64} {...EMOJI}>{ICONS[icon]}</text>
      {action && ACTIONS[action] && <text x={100} y={44} fontSize={34} {...EMOJI}>{ACTIONS[action]}</text>}
    </svg>
  )
}

function Timeline({ events, show_years: years }: { events: { label: string; year: number }[]; show_years: boolean }) {
  const list = [...(events ?? [])].slice(0, 8).sort((a, b) => a.year - b.year)
  const lo = list[0]?.year ?? 0, hi = list[list.length - 1]?.year ?? 1
  const x = (v: number) => 30 + ((v - lo) / Math.max(1, hi - lo)) * 460
  const year = (v: number) => (v < 0 ? `${-v} BC` : `${v}`)
  return (
    <svg viewBox="0 0 520 130" width="520" height="130">
      <line x1={20} y1={60} x2={500} y2={60} stroke={INK} strokeWidth={3} />
      {list.map((e, i) => (
        <g key={i}>
          <circle cx={x(e.year)} cy={60} r={6} fill={FILL} stroke={INK} strokeWidth={2} />
          <text x={x(e.year)} y={i % 2 ? 96 : 38} textAnchor="middle" {...FONT}>{e.label.slice(0, 30)}</text>
          {years && <text x={x(e.year)} y={i % 2 ? 114 : 20} textAnchor="middle" {...FONT} fontSize={11}>{year(e.year)}</text>}
        </g>
      ))}
    </svg>
  )
}

function Venn({ left, right, left_items: l, right_items: r, both_items: b }: { left: string; right: string; left_items: string[]; right_items: string[]; both_items: string[] }) {
  const column = (items: string[], cx: number) => (items ?? []).slice(0, 6).map((t, i) => (
    <text key={i} x={cx} y={88 + i * 18} textAnchor="middle" {...FONT} fontSize={12}>{t.slice(0, 20)}</text>
  ))
  return (
    <svg viewBox="0 0 420 230" width="420" height="230">
      <circle cx={150} cy={125} r={100} fill={FILL} fillOpacity={0.25} stroke={INK} strokeWidth={2} />
      <circle cx={270} cy={125} r={100} fill={FILL} fillOpacity={0.25} stroke={INK} strokeWidth={2} />
      <text x={110} y={18} textAnchor="middle" {...FONT} fontWeight="bold">{left.slice(0, 20)}</text>
      <text x={310} y={18} textAnchor="middle" {...FONT} fontWeight="bold">{right.slice(0, 20)}</text>
      {column(l, 100)}{column(b, 210)}{column(r, 320)}
    </svg>
  )
}

function Table({ header, rows }: { header: string[]; rows: string[][] }) {
  const cols = (header ?? []).slice(0, 4)
  const w = 120, h = 28
  const body = (rows ?? []).slice(0, 6)
  return (
    <svg viewBox={`0 0 ${cols.length * w + 2} ${(body.length + 1) * h + 2}`} width={cols.length * w + 2} height={(body.length + 1) * h + 2}>
      {[cols, ...body].map((row, r) => cols.map((_, c) => (
        <g key={`${r}-${c}`}>
          <rect x={1 + c * w} y={1 + r * h} width={w} height={h} fill={r === 0 ? '#e8ece2' : PAPER} stroke={INK} strokeWidth={1} />
          <text x={1 + c * w + w / 2} y={1 + r * h + 19} textAnchor="middle" {...FONT} fontWeight={r === 0 ? 'bold' : 'normal'}>{(row[c] ?? '').slice(0, 20)}</text>
        </g>
      )))}
    </svg>
  )
}

function Steps({ kind, steps }: { kind: 'cycle' | 'sequence'; steps: string[] }) {
  const list = (steps ?? []).slice(0, 8)
  const box = (t: string, x: number, y: number, key: number) => (
    <g key={key}>
      <rect x={x - 62} y={y - 16} width={124} height={32} rx={8} fill={t === '?' ? PAPER : '#e8ece2'} stroke={INK} strokeWidth={1.5} strokeDasharray={t === '?' ? '4 3' : undefined} />
      <text x={x} y={y + 5} textAnchor="middle" {...FONT}>{t.slice(0, 20)}</text>
    </g>
  )
  if (kind === 'sequence') {
    return (
      <svg viewBox={`0 0 ${list.length * 150} 50`} width={list.length * 150} height={50}>
        {list.map((t, i) => (
          <g key={i}>
            {box(t, 70 + i * 150, 25, i)}
            {i < list.length - 1 && <path d={`M${134 + i * 150},25 l12,0 m-5,-5 l5,5 l-5,5`} stroke={INK} strokeWidth={2} fill="none" />}
          </g>
        ))}
      </svg>
    )
  }
  const cx = 200, cy = 150, r = 105
  const at = (i: number) => {
    const a = (i / list.length) * 2 * Math.PI - Math.PI / 2
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)]
  }
  return (
    <svg viewBox="0 0 400 300" width="400" height="300">
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="#b9c1ad" strokeWidth={2} strokeDasharray="6 4" />
      {list.map((_, i) => {
        const a = ((i + 0.5) / list.length) * 2 * Math.PI - Math.PI / 2
        const [ax, ay] = [cx + r * Math.cos(a), cy + r * Math.sin(a)]
        const deg = (a * 180) / Math.PI + 90
        return <path key={`a${i}`} d="M-5,-5 L5,0 L-5,5" transform={`translate(${ax},${ay}) rotate(${deg - 90})`} stroke={INK} strokeWidth={2} fill="none" />
      })}
      {list.map((t, i) => { const [x, y] = at(i); return box(t, x, y, i) })}
    </svg>
  )
}

const BAR_COLOURS = ['#c98b5a', '#7d9bb8', '#b6a04a', '#9a7fb0']

function Ruler({ unit, length, objects }: { unit: 'cm' | 'in'; length: number; objects: { label: string; start: number; end: number; icon?: string | null }[] }) {
  const n = clamp(length, 2, 30)
  const list = (objects ?? []).slice(0, 4)
  const per = Math.max(18, Math.min(40, 540 / n))
  const x = (v: number) => 20 + Math.max(0, Math.min(n, Number(v) || 0)) * per
  const top = 14 + list.length * 34
  const ticks: ReactElement[] = []
  const sub = unit === 'in' ? 2 : 1
  for (let k = 0; k <= n * sub; k++) {
    const whole = k % sub === 0
    ticks.push(<line key={k} x1={x(k / sub)} y1={top} x2={x(k / sub)} y2={top + (whole ? 16 : 9)} stroke={INK} strokeWidth={whole ? 1.5 : 1} />)
    if (whole) ticks.push(<text key={`n${k}`} x={x(k / sub)} y={top + 30} textAnchor="middle" {...FONT} fontSize={11}>{k / sub}</text>)
  }
  return (
    <svg viewBox={`0 0 ${n * per + 50} ${top + 44}`} width={n * per + 50} height={top + 44}>
      {list.map((o, i) => (
        <g key={i}>
          <rect x={x(o.start)} y={10 + i * 34} width={Math.max(4, x(o.end) - x(o.start))} height={24} rx={6} fill={BAR_COLOURS[i % 4]} stroke={INK} strokeWidth={1.5} />
          <text x={x(o.start) + 6} y={27 + i * 34} {...FONT} fill="#ffffff" fontWeight="bold">
            {o.icon && ICONS[o.icon] ? `${ICONS[o.icon]} ` : ''}{o.label.slice(0, 16)}
          </text>
          <line x1={x(o.start)} y1={34 + i * 34} x2={x(o.start)} y2={top} stroke={INK} strokeWidth={0.75} strokeDasharray="2 3" />
          <line x1={x(o.end)} y1={34 + i * 34} x2={x(o.end)} y2={top} stroke={INK} strokeWidth={0.75} strokeDasharray="2 3" />
        </g>
      ))}
      <rect x={14} y={top} width={n * per + 12} height={36} fill="#f4e7b8" stroke={INK} strokeWidth={1.5} />
      {ticks}
      <text x={n * per + 22} y={top + 30} {...FONT} fontSize={11}>{unit}</text>
    </svg>
  )
}

function Money({ pieces }: { pieces: { coin: string; count: number }[] }) {
  const items: { coin: string }[] = []
  for (const p of (pieces ?? []).slice(0, 6)) {
    if (!COINS[p.coin]) continue
    for (let k = 0; k < clamp(p.count, 1, 10); k++) items.push({ coin: p.coin })
  }
  let x = 8
  const drawn = items.map((it, i) => {
    const c = COINS[it.coin]
    const label = c.cents >= 100 ? `$${c.cents / 100}` : `${c.cents}¢`
    if (c.bill) {
      const g = <g key={i}><rect x={x} y={14} width={88} height={44} rx={4} fill="#cfe3c4" stroke="#3d6b35" strokeWidth={2} />
        <text x={x + 44} y={42} textAnchor="middle" {...FONT} fontSize={16} fontWeight="bold" fill="#2f5229">{label}</text></g>
      x += 96
      return g
    }
    const r = c.r ?? 20
    const g = <g key={i}><circle cx={x + r} cy={36} r={r} fill={it.coin === 'penny' ? '#d9a066' : '#d7d9dd'} stroke={INK} strokeWidth={1.5} />
      <text x={x + r} y={40} textAnchor="middle" {...FONT} fontSize={11} fontWeight="bold">{label}</text></g>
    x += r * 2 + 8
    return g
  })
  return <svg viewBox={`0 0 ${Math.max(60, x)} 72`} width={Math.max(60, x)} height={72}>{drawn}</svg>
}

function Thermometer({ unit, low, high, step, reading }: { unit: 'F' | 'C'; low: number; high: number; step: number; reading: number }) {
  const lo = Math.round(low), hi = Math.max(lo + 1, Math.round(high)), st = Math.max(1, Math.round(step))
  const y = (v: number) => 210 - ((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * 180
  const marks: ReactElement[] = []
  for (let v = lo; v <= hi && marks.length < 60; v += st) {
    marks.push(<g key={v}><line x1={62} y1={y(v)} x2={74} y2={y(v)} stroke={INK} strokeWidth={1.5} />
      <text x={80} y={y(v) + 4} {...FONT} fontSize={11}>{v}°{unit}</text></g>)
  }
  return (
    <svg viewBox="0 0 140 250" width="140" height="250">
      <rect x={42} y={20} width={20} height={200} rx={10} fill={PAPER} stroke={INK} strokeWidth={2} />
      <rect x={47} y={y(reading)} width={10} height={220 - y(reading)} fill="#c0392b" />
      <circle cx={52} cy={228} r={16} fill="#c0392b" stroke={INK} strokeWidth={2} />
      {marks}
    </svg>
  )
}

// ── A real thing, from Wikimedia Commons ─────────────────────────────────────
// The same lookup picture study makes (VisualAidCard.tsx): the browser asks
// Wikipedia for one article's summary and loads its lead picture. Only a file
// on Wikimedia Commons is shown, because Commons holds freely licensed files
// and English Wikipedia's own uploads can be non-free. Anything else, a
// missing article, a disambiguation page or no picture, shows the words.
export const WIKI_SUMMARY = 'https://en.wikipedia.org/api/rest_v1/page/summary/'
const COMMONS = /^https:\/\/upload\.wikimedia\.org\/wikipedia\/commons\//

type Found = { src: string; title: string } | null
const found = new Map<string, Found>()

export async function lookupImage(title: string): Promise<Found> {
  if (found.has(title)) return found.get(title) ?? null
  let result: Found = null
  try {
    const res = await fetch(`${WIKI_SUMMARY}${encodeURIComponent(title.replace(/ /g, '_'))}`)
    if (res.ok) {
      const data = await res.json()
      const src = data?.thumbnail?.source || data?.originalimage?.source
      if (data?.type !== 'disambiguation' && typeof src === 'string' && COMMONS.test(src)) {
        result = { src, title: String(data?.title || title) }
      }
    }
  } catch {
    result = null
  }
  found.set(title, result)
  return result
}

function Credit({ title }: { title: string }) {
  const { t } = useTranslation()
  return <span className="block text-xs text-gray-500">{t('diagram.imageCredit', { title })}</span>
}

function WikiImage({ wiki_title: title, caption }: { wiki_title: string; caption?: string }) {
  const [image, setImage] = useState<Found | undefined>(found.get(title))
  useEffect(() => {
    let live = true
    if (!found.has(title)) void lookupImage(title).then((r) => { if (live) setImage(r) })
    return () => { live = false }
  }, [title])
  const words = caption || title
  if (!image) return <span className="italic text-gray-500">{words}</span>
  return (
    <span className="block">
      <img src={image.src} alt={words} className="max-h-64 max-w-full rounded" referrerPolicy="no-referrer" />
      <Credit title={image.title} />
    </span>
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
    case 'pictures': return t('diagram.pictures', { things: d.groups.map((g) => `${g.label ? `${g.label}: ` : ''}${g.count} ${t(`diagram.icon.${g.icon}`, { defaultValue: g.icon })}`).join(', ') })
    case 'scene': return t('diagram.scene', { thing: t(`diagram.icon.${d.icon}`, { defaultValue: d.icon }), action: d.action ? t(`diagram.action.${d.action}`, { defaultValue: d.action }) : '' })
    case 'timeline': return t('diagram.timeline', { events: d.events.map((e) => d.show_years ? `${e.label} (${e.year})` : e.label).join(', ') })
    case 'venn': return t('diagram.venn', { left: d.left, right: d.right })
    case 'table': return t('diagram.table', { header: d.header.join(', '), rows: d.rows.length })
    case 'cycle': return t('diagram.cycle', { steps: d.steps.join(', ') })
    case 'sequence': return t('diagram.sequence', { steps: d.steps.join(', ') })
    case 'ruler': return t('diagram.ruler', { unit: d.unit, things: d.objects.map((o) => t('diagram.rulerThing', { label: o.label, start: o.start, end: o.end })).join('; ') })
    case 'money': return t('diagram.money', { pieces: d.pieces.map((p) => `${p.count} × ${t(`diagram.coin.${p.coin}`, { defaultValue: p.coin })}`).join(', ') })
    case 'thermometer': return t('diagram.thermometer', { low: d.low, high: d.high, unit: d.unit })
    case 'image': return d.caption || d.wiki_title
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
    case 'pictures': return <Pictures groups={d.groups} />
    case 'scene': return <Scene icon={d.icon} action={d.action} />
    case 'timeline': return <Timeline events={d.events} show_years={d.show_years} />
    case 'venn': return <Venn {...d} />
    case 'table': return <Table header={d.header} rows={d.rows} />
    case 'cycle': case 'sequence': return <Steps kind={d.kind} steps={d.steps} />
    case 'ruler': return <Ruler unit={d.unit} length={d.length} objects={d.objects} />
    case 'money': return <Money pieces={d.pieces} />
    case 'thermometer': return <Thermometer {...d} />
    case 'image': return <WikiImage wiki_title={d.wiki_title} caption={d.caption} />
    default: return null
  }
}

/** A picture Bede cannot draw, said plainly: the words without a "picture:" label. */
export function pictureWords(text: string): string {
  return text.replace(/^\s*(picture|image|drawing|photo)\s*(of)?\s*:\s*/i, '')
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
export function diagramMarkup(d?: DiagramSpec | null, t?: (key: string, values?: Record<string, unknown>) => string): string {
  if (!d) return ''
  if (d.kind === 'image') {
    // Printing cannot wait for a lookup: the picture is printed when the
    // screen has already shown it, and the words otherwise.
    const image = found.get(d.wiki_title)
    const words = d.caption || d.wiki_title
    return `<div class="diagram">${renderToStaticMarkup(image
      ? <figure><img src={image.src} alt={words} style={{ maxHeight: '16rem', maxWidth: '100%' }} /><figcaption>{`${words}. ${t ? t('diagram.imageCredit', { title: image.title }) : `Picture: Wikimedia Commons, from the Wikipedia article “${image.title}”`}`}</figcaption></figure>
      : <p><em>{words}</em></p>)}</div>`
  }
  return `<div class="diagram">${renderToStaticMarkup(<DiagramSvg d={d} />)}</div>`
}
