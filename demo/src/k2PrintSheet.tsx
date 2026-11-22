import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactElement } from 'react'
import type { TFunction } from 'i18next'
import { Printer } from 'lucide-react'
import type { PhonicsLesson, PhonicsTask } from './k2PhonicsTypes'
import type { MathLesson, MathPiece, MathTask } from './k2MathTypes'
import type { MapLesson, MapTask } from './mapPracticeTypes'
import { printSheet, type PrintItem } from './printDocument'
import { Picture } from './Diagram'
import MapScene, { SideView } from './MapScene'

/**
 * A K-2 round (Sound Time, Number Time, Map Practice) as a paper practice
 * sheet, through the same printer as Practice Coach's worksheets
 * (utils/printDocument.ts). The device's own print dialog prints it or saves
 * it as a PDF, on Windows, macOS, iOS, Android and Linux alike, so nothing
 * here depends on one system's PDF tool.
 *
 * The sheet shows each question the way "Your turn" shows it, so nothing on
 * paper gives an answer away, and it carries no answers: the server keeps
 * them. A question that only works by ear (a word to listen for, a sight
 * word) is left off, because paper cannot say it. Printing records nothing.
 *
 * Mirrored in the demo (demo/src/k2PrintSheet.tsx), checked by
 * demo/src/k2MathParity.test.ts.
 */

const LETTER = (i: number) => String.fromCharCode(65 + i)
const INK = '#1f2a44'

/** Pictures in a row, each with its letter (never its word, which may be the answer). */
function lettered(pictures: ReactElement[]): string {
  return renderToStaticMarkup(
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '14pt', alignItems: 'flex-end' }}>
      {pictures.map((p, i) => (
        <figure key={i} style={{ margin: 0, textAlign: 'center' }}>
          {p}
          <figcaption style={{ fontWeight: 'bold' }}>{LETTER(i)}</figcaption>
        </figure>
      ))}
    </div>,
  )
}

/** Every K-2 picture sits in one box, which K2_PRINT_CSS styles. */
const wrap = (html: string) => `<div class="k2pic">${html}</div>`

/** A hand-drawn picture at a fixed printed size. */
function picture(name: string, width: string): ReactElement {
  return <div style={{ width }}><Picture name={name} label={name} size="" /></div>
}

/** Questions that are asked only by ear: paper cannot say them. */
const BY_EAR = ['first_sound_choice', 'sight_word_choice']

export function phonicsPrintItems(t: TFunction, lesson: PhonicsLesson): PrintItem[] {
  const tasks: PhonicsTask[] = [...lesson.together, ...lesson.your_turn]
  return tasks
    .filter((task) => task.display.kind !== 'listen' && !BY_EAR.includes(task.prompt.key))
    .map((task) => {
      const { display } = task
      const item: PrintItem = { prompt: t(`k2Phonics.prompt.${task.prompt.key}`, task.prompt.args), details: [t('k2Print.circle')] }
      const shown: string[] = []
      if (display.kind === 'picture' && display.icon) shown.push(renderToStaticMarkup(picture(display.icon, '96pt')))
      if (display.kind === 'word' && display.graphemes) {
        // The word to read, large enough for a beginning reader.
        shown.push(renderToStaticMarkup(
          <p style={{ fontSize: '30pt', fontWeight: 'bold', letterSpacing: '0.12em', margin: '4pt 0' }}>{display.graphemes.map((g) => g.text).join('')}</p>,
        ))
      }
      if (task.choice_kind === 'picture') {
        shown.push(lettered(task.choices.map((c) => picture(c, '72pt'))))
        item.answerSpace = 'letter'
      } else {
        item.options = task.choices
      }
      if (shown.length) item.diagramHtml = wrap(shown.join(''))
      return item
    })
}

/**
 * Number Time's pieces drawn for paper with plain colours, since the screen
 * version is styled by the app's classes, which a printed sheet does not
 * carry. No guide numbers: counting them is the question.
 */
function Counter({ x, y, red }: { x: number; y: number; red: boolean }) {
  return red
    ? <circle cx={x} cy={y} r="15" fill="#b5483b" />
    : <g><circle cx={x} cy={y} r="14" fill="#f2d675" stroke="#9a7417" strokeWidth="3" /><circle cx={x} cy={y} r="6" fill="none" stroke="#9a7417" strokeWidth="3" /></g>
}

export function MathPrintPicture({ d }: { d: MathPiece }) {
  if (d.kind === 'counters') {
    const widest = Math.max(1, ...d.groups.map((g) => g.count))
    return (
      <svg viewBox={`0 0 ${widest * 38 + 4} ${d.groups.length * 40 + 4}`} width={widest * 26} height={d.groups.length * 28}>
        {d.groups.map((g, r) => Array.from({ length: g.count }, (_, i) => (
          <Counter key={`${r}-${i}`} x={21 + i * 38} y={22 + r * 40} red={g.color === 'red'} />
        )))}
      </svg>
    )
  }
  if (d.kind === 'ten_frame') {
    const frames = d.frames ?? 1
    const red = d.red ?? 0
    const filled = red + (d.yellow ?? 0)
    const crossedFrom = filled - (d.crossed ?? 0)
    return (
      <svg viewBox={`0 0 ${5 * 44 + 8} ${frames * 100 + (frames - 1) * 12}`} width={5 * 30 + 6} height={frames * 68 + (frames - 1) * 8}>
        {Array.from({ length: frames * 10 }, (_, i) => {
          const f = Math.floor(i / 10)
          const k = i % 10
          const x = 4 + (k % 5) * 44
          const y = f * 112 + 4 + Math.floor(k / 5) * 44
          return (
            <g key={i}>
              <rect x={x} y={y} width="44" height="44" fill="#fff" stroke={INK} strokeWidth="2" />
              {i < filled && <Counter x={x + 22} y={y + 22} red={i < red} />}
              {i < filled && i >= crossedFrom && <path d={`M${x + 8} ${y + 8} L${x + 36} ${y + 36} M${x + 36} ${y + 8} L${x + 8} ${y + 36}`} stroke={INK} strokeWidth="4" />}
            </g>
          )
        })}
      </svg>
    )
  }
  const shown = (v: number | null) => (v === null ? '?' : String(v))
  const circle = (cx: number, cy: number, v: number | null) => (
    <g>
      <circle cx={cx} cy={cy} r="26" fill="#fff" stroke={INK} strokeWidth="3" strokeDasharray={v === null ? '6 4' : undefined} />
      <text x={cx} y={cy + 9} textAnchor="middle" fontSize="26" fontWeight="700" fill={INK}>{shown(v)}</text>
    </g>
  )
  return (
    <svg viewBox="0 0 200 150" width="150" height="112">
      <line x1="100" y1="40" x2="45" y2="110" stroke={INK} strokeWidth="3" />
      <line x1="100" y1="40" x2="155" y2="110" stroke={INK} strokeWidth="3" />
      {circle(100, 32, d.whole)}{circle(45, 115, d.parts[0] ?? null)}{circle(155, 115, d.parts[1] ?? null)}
    </svg>
  )
}

export function mathPrintItems(t: TFunction, lesson: MathLesson): PrintItem[] {
  const tasks: MathTask[] = [...lesson.together, ...lesson.your_turn]
  return tasks.map((task) => {
    const item: PrintItem = {
      prompt: t(`k2Math.prompt.${task.prompt.key}`, task.prompt.args),
      diagramHtml: wrap(renderToStaticMarkup(<MathPrintPicture d={task.display.diagram} />)),
      details: [t('k2Print.circle')],
    }
    if (task.choice_kind === 'color') item.options = task.choices.map((c) => t(`k2Math.choice.${c}`))
    else if (task.choice_kind === 'number') item.options = task.choices
    else item.details = [t('k2Print.drawCounters')]
    return item
  })
}

export function mapPrintItems(t: TFunction, lesson: MapLesson, prompt: (task: MapTask) => string, choice: (c: string) => string): PrintItem[] {
  const tasks: MapTask[] = [...lesson.together, ...lesson.your_turn]
  return tasks.map((task) => {
    const item: PrintItem = { prompt: prompt(task) }
    const side = task.side_view ? renderToStaticMarkup(<SideView symbols={task.side_view} />) : ''
    if (task.answer_kind === 'scene_choice' && task.options) {
      item.diagramHtml = wrap(side + lettered(task.options.map((o, i) => <MapScene key={i} scene={o} small />)))
      item.answerSpace = 'letter'
      item.details = [t('k2Print.circle')]
    } else {
      item.diagramHtml = wrap(side + renderToStaticMarkup(<MapScene scene={task.scene} marked={task.marked} />))
      if (task.answer_kind === 'choice' && task.choices) {
        item.options = task.choices.map(choice)
        item.details = [t('k2Print.circle')]
      }
      if (task.answer_kind === 'tap') {
        item.details = [t('k2Print.markSquare')]
        item.answerSpace = 'picture'
      }
    }
    return item
  })
}

/**
 * The few screen classes MapScene's compass, key and side view lean on,
 * restated for paper.
 */
export const K2_PRINT_CSS = `
.k2pic { margin: 0.3em 0; break-inside: avoid; page-break-inside: avoid; }
.k2pic .relative { position: relative; display: inline-block; margin-right: 44pt; }
.k2pic .absolute { position: absolute; top: -6pt; right: -44pt; background: #fff; border-radius: 50%; border: 1px solid #b9ad8f; }
.k2pic svg.w-14 { width: 34pt; height: 34pt; }
.k2pic svg.w-36 { width: 110pt; height: auto; }
.k2pic svg.max-w-md { max-width: 260pt; height: auto; }
.k2pic ul { list-style: none; display: flex; flex-wrap: wrap; gap: 3pt 12pt; padding: 0; margin: 4pt 0; font-size: 10pt; }
.k2pic li { display: flex; align-items: center; gap: 4pt; }
.k2pic [role="img"] { display: flex; align-items: flex-end; gap: 14pt; }
`

/** Prints the sheet, or saves it as a PDF from the same dialog. */
export function printPractice(t: TFunction, title: string, items: PrintItem[]): Promise<boolean> {
  return printSheet({
    title: t('k2Print.title', { title }),
    items,
    copies: ['student'],
    labels: { name: t('printSheet.name'), date: t('printSheet.date'), keyTitle: title },
    css: K2_PRINT_CSS,
  })
}

export function PrintPracticeButton({ t, onPrint, className }: { t: TFunction; onPrint: () => void; className: string }) {
  return (
    <button type="button" onClick={onPrint} className={className}>
      <Printer aria-hidden="true" className="mr-2 inline h-5 w-5" />{t('k2Print.button')}
    </button>
  )
}
