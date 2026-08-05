import { useRef, useEffect, useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { X, Undo2, Redo2, FilePlus2, Check, Pencil, Eraser, Printer, Download } from 'lucide-react'
import type { Subject } from './api'
import { clearPage, loadPage, pruneOtherPages, savePage } from './canvasPersistence'

interface Point {
  x: number
  y: number
  pressure: number
}

interface Stroke {
  points: Point[]
  width: number
  color: string
  // Eraser strokes are resolved to the CURRENT paper color at draw time —
  // storing the background hex directly would leave stale-colored patches
  // behind whenever the child recolors the paper mid-drawing.
  isEraser?: boolean
}

interface HandwritingCanvasProps {
  onSubmit: (imageDataUrl: string) => void
  onCancel: () => void
  // Picks the printed/drawn paper style below — mathematics gets graph
  // paper (for showing work, plotting, keeping columns aligned); Art &
  // Music gets staff paper (five-line musical staves for copying a hymn
  // line, notating a melody, or first composition exercises); Science gets
  // the nature-journal split page (open sketch space above, ruled
  // observation lines below — the classic Charlotte Mason nature-notebook
  // layout); everything else (written narration, copywork, etc., per
  // invite_handwriting's own scope) gets composition paper, the classic
  // ruled handwriting-practice sheet. Optional/undefined falls back to
  // composition paper.
  subject?: Subject
  // Scales the composition/journal ruling to the child's writing size —
  // K-2 gets wide primary ruling with a dashed midline (still forming
  // letters), 3-5 the standard elementary ruling, 6-8 a tighter
  // college-style rule with no midline. Unknown/absent falls back to the
  // 3-5 ruling, which is what this canvas always drew before.
  gradeStage?: string
  // The demo session code this page belongs to. Given it, the page
  // (strokes, paper style, paper color) is kept in this tab's
  // sessionStorage so going back to the chat and returning finds the work
  // still there; see canvasPersistence.ts for the budget, what happens at
  // it, and why none of it reaches the server. Omitted, this component
  // behaves exactly as it always did: the page exists only while mounted.
  persistKey?: string
}

// True-to-scale printing and saving: the canvas's internal drawing
// resolution is pinned to US Letter at 96 CSS px/inch, regardless of the
// on-screen viewport's size or shape. Before this existed, the backing
// store was sized to canvas.offsetWidth/Height - whatever CSS pixels the
// flex layout happened to give it - so a visitor on a narrow phone got a
// correspondingly low-resolution save/print, and the SAME drawing produced
// a different-resolution PNG depending on how big their browser window
// happened to be. Pinning the backing resolution here, letterboxing the
// on-screen display to the same 8.5:11 aspect ratio (see the paperBox
// sizing effect below), and forcing @page to portrait Letter with no
// stretch in the print stylesheet makes on-screen drawing, the saved PNG,
// and the printed page all the same shape at the same scale, matching the
// app's own canvas (`homeschool-tutor/src/components/HandwritingCanvas.tsx`).
const PRINT_DPI = 96
const PAGE_WIDTH_IN = 8.5
const PAGE_HEIGHT_IN = 11
const PAGE_ASPECT = PAGE_WIDTH_IN / PAGE_HEIGHT_IN
const CANVAS_WIDTH = PAGE_WIDTH_IN * PRINT_DPI // 816
const CANVAS_HEIGHT = PAGE_HEIGHT_IN * PRINT_DPI // 1056

const PARCHMENT_BG = '#faf8f0'

// Paper colors — construction-paper pastels a child would pull from the
// craft drawer, plus Slate: the classical schoolroom chalkboard (rulings
// lighten automatically on dark paper; pick a light ink to write on it).
const PAPER_COLORS = [
  { id: 'parchment', value: PARCHMENT_BG },
  { id: 'white', value: '#ffffff' },
  { id: 'sunshine', value: '#fdf3cf' },
  { id: 'rose', value: '#fbe4e4' },
  { id: 'sage', value: '#e4efe4' },
  { id: 'sky', value: '#e0ecf9' },
  { id: 'slate', value: '#2e3a44' },
] as const

// Perceived-luminance check so rulings stay visible on dark paper.
function isDarkPaper(hex: string): boolean {
  const n = parseInt(hex.slice(1), 16)
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255
  return 0.299 * r + 0.587 * g + 0.114 * b < 128
}
const GRAPH_LINE_COLOR = '#c9d6e8'
const COMPOSITION_RULE_COLOR = '#a9c3dc'
const COMPOSITION_MIDLINE_COLOR = '#c7d8ea'

// Every spacing/margin constant below is measured in the same fixed page
// pixels as CANVAS_WIDTH/HEIGHT above (96 per inch) — unchanged numbers
// from before the fixed page space existed, now interpreted against a
// page that is always the same physical size rather than however much of
// the browser window happened to be available.
const GRAPH_SPACING = 24
// Dot-grid paper: same pitch as the graph grid so work translates between
// the two, but only the intersections are marked — dots guide without
// boxing the child in, which suits geometry constructions, multiplication
// arrays, symmetry work, and freehand-but-tidy diagrams.
const DOT_SPACING = 24
const DOT_RADIUS = 1.5
// Composition ruling scaled to the writer, not one-size-fits-all. The
// dashed guide midline sits halfway between one baseline and the next,
// matching the classic elementary layout (top space, dashed midline,
// solid baseline) — K-2 writes big and needs the midline; 6-8 gets a
// tighter college-style rule with no midline. The '3-5' row is the exact
// ruling this canvas always drew before grade scaling existed.
const RULING_BY_STAGE: Record<string, { lineHeight: number; midline: boolean }> = {
  'K-2': { lineHeight: 58, midline: true },
  '3-5': { lineHeight: 42, midline: true },
  '6-8': { lineHeight: 32, midline: false },
}
const DEFAULT_RULING = RULING_BY_STAGE['3-5']
// Nature-journal split page: the top portion is open sketch space (the
// specimen drawing), the bottom is ruled for the written observation —
// one page holds both halves of a Charlotte Mason notebook entry. A short
// date line sits top-right, as on a real nature-notebook page.
const JOURNAL_SPLIT_RATIO = 0.58
const JOURNAL_DATE_LINE_Y = 34
const JOURNAL_DATE_LINE_WIDTH = 150
// Musical staff paper: five lines per staff. The line gap is generous
// (beginner manuscript paper, not engraver-tight) so a child can place
// note heads between lines with a stylus or pencil after printing.
const STAFF_LINE_GAP = 12
// Top of one staff to the top of the next — leaves clear space between
// staves for lyrics, solfège syllables, or ledger lines.
const STAFF_GROUP_SPACING = 96
const STAFF_TOP_MARGIN = 48

type PaperStyle = 'composition' | 'graph' | 'dots' | 'staff' | 'journal' | 'blank'

// The subject picks the DEFAULT paper only — the child is free to switch to
// any paper from the toolbar picker regardless of topic (a math session may
// want a blank sketch; an art session may want ruled lines for a caption).
function paperStyleFor(subject?: Subject): PaperStyle {
  if (subject === 'mathematics') return 'graph'
  if (subject === 'art_music') return 'staff'
  if (subject === 'science') return 'journal'
  return 'composition'
}

const PAPER_ORDER: PaperStyle[] = ['composition', 'graph', 'dots', 'staff', 'journal', 'blank']

// Fills the page background and its ruling — called any time the canvas is
// (re)initialized, resized, cleared, or redrawn from the stroke history, so
// the paper style never needs separate "erase to blank" handling from
// "erase to ruled/gridded" handling.
// One writing line (optional dashed midline + solid baseline) — shared by
// composition paper and the journal page's ruled lower portion so the two
// always agree on what a "line" looks like at a given grade stage.
function drawRuledLines(
  ctx: CanvasRenderingContext2D,
  width: number,
  fromY: number,
  toY: number,
  ruling: { lineHeight: number; midline: boolean },
  ruleColor: string,
  midColor: string,
) {
  for (let y = fromY + ruling.lineHeight; y < toY; y += ruling.lineHeight) {
    if (ruling.midline) {
      const midY = y - ruling.lineHeight / 2
      ctx.strokeStyle = midColor
      ctx.lineWidth = 1
      ctx.setLineDash([6, 6])
      ctx.beginPath()
      ctx.moveTo(0, midY + 0.5)
      ctx.lineTo(width, midY + 0.5)
      ctx.stroke()
    }

    ctx.strokeStyle = ruleColor
    ctx.lineWidth = 1
    ctx.setLineDash([])
    ctx.beginPath()
    ctx.moveTo(0, y + 0.5)
    ctx.lineTo(width, y + 0.5)
    ctx.stroke()
  }
}

function drawPaper(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  style: PaperStyle,
  bg: string,
  ruling: { lineHeight: number; midline: boolean },
) {
  ctx.fillStyle = bg
  ctx.fillRect(0, 0, width, height)

  if (style === 'blank') return

  const dark = isDarkPaper(bg)
  const ruleColor = dark ? 'rgba(255,255,255,0.35)' : COMPOSITION_RULE_COLOR
  const midColor = dark ? 'rgba(255,255,255,0.22)' : COMPOSITION_MIDLINE_COLOR
  const gridColor = dark ? 'rgba(255,255,255,0.25)' : GRAPH_LINE_COLOR

  if (style === 'graph') {
    ctx.strokeStyle = gridColor
    ctx.lineWidth = 1
    ctx.setLineDash([])
    for (let x = GRAPH_SPACING; x < width; x += GRAPH_SPACING) {
      ctx.beginPath()
      ctx.moveTo(x + 0.5, 0)
      ctx.lineTo(x + 0.5, height)
      ctx.stroke()
    }
    for (let y = GRAPH_SPACING; y < height; y += GRAPH_SPACING) {
      ctx.beginPath()
      ctx.moveTo(0, y + 0.5)
      ctx.lineTo(width, y + 0.5)
      ctx.stroke()
    }
    return
  }

  if (style === 'dots') {
    // A dot at every grid intersection, none on the edges — the ink-dot
    // color leans on the ruling color so dots survive dark paper too.
    ctx.fillStyle = dark ? 'rgba(255,255,255,0.4)' : ruleColor
    for (let x = DOT_SPACING; x < width; x += DOT_SPACING) {
      for (let y = DOT_SPACING; y < height; y += DOT_SPACING) {
        ctx.beginPath()
        ctx.arc(x, y, DOT_RADIUS, 0, Math.PI * 2)
        ctx.fill()
      }
    }
    return
  }

  if (style === 'staff') {
    ctx.strokeStyle = ruleColor
    ctx.lineWidth = 1
    ctx.setLineDash([])
    // Whole staves only — a staff that would run off the bottom edge is
    // omitted rather than drawn partially (four lines is not a staff).
    for (let top = STAFF_TOP_MARGIN; top + 4 * STAFF_LINE_GAP <= height; top += STAFF_GROUP_SPACING) {
      for (let line = 0; line < 5; line++) {
        const y = top + line * STAFF_LINE_GAP
        ctx.beginPath()
        ctx.moveTo(0, y + 0.5)
        ctx.lineTo(width, y + 0.5)
        ctx.stroke()
      }
    }
    return
  }

  if (style === 'journal') {
    // Short date line, top-right — filled in by hand like a real notebook.
    ctx.strokeStyle = ruleColor
    ctx.lineWidth = 1
    ctx.setLineDash([])
    ctx.beginPath()
    ctx.moveTo(width - 24 - JOURNAL_DATE_LINE_WIDTH, JOURNAL_DATE_LINE_Y + 0.5)
    ctx.lineTo(width - 24, JOURNAL_DATE_LINE_Y + 0.5)
    ctx.stroke()

    // Divider between the sketch space above and the writing lines below.
    const splitY = Math.round(height * JOURNAL_SPLIT_RATIO)
    ctx.beginPath()
    ctx.moveTo(0, splitY + 0.5)
    ctx.lineTo(width, splitY + 0.5)
    ctx.stroke()

    drawRuledLines(ctx, width, splitY, height, ruling, ruleColor, midColor)
    return
  }

  drawRuledLines(ctx, width, 0, height, ruling, ruleColor, midColor)
}

// The only exportable surface in this app — a deliberate, narrow exception
// to having no export/download functionality anywhere else. This is
// entirely client-side: it prints the already-rendered canvas bitmap via
// the browser's own print dialog, with no new backend endpoint and
// nothing sent anywhere.
const PRINT_AREA_ID = 'handwriting-print-area'

// A compact MS-Paint/Preview-style swatch row rather than a full color wheel —
// enough range for a nature-notebook sketch or a math diagram without
// overwhelming a touch toolbar. First entry is the historical default ink
// color this canvas always used, kept as the default selection.
const PALETTE = [
  { id: 'ink', value: '#1b3a6b' },
  { id: 'black', value: '#1a1a1a' },
  { id: 'red', value: '#c0392b' },
  { id: 'orange', value: '#d9791b' },
  { id: 'gold', value: '#c9971e' },
  { id: 'green', value: '#2f7d4f' },
  { id: 'sky', value: '#2f7fc0' },
  { id: 'purple', value: '#7a4fa3' },
  { id: 'brown', value: '#7a5230' },
] as const

type SizePreset = 'thin' | 'medium' | 'thick'
const SIZE_PRESETS: Record<SizePreset, { min: number; max: number; base: number; dot: number }> = {
  thin: { min: 1, max: 3, base: 1.5, dot: 5 },
  medium: { min: 2, max: 6, base: 3, dot: 9 },
  thick: { min: 4, max: 12, base: 6, dot: 14 },
}

type Tool = 'pen' | 'eraser'

// How long the page sits still before it is written to sessionStorage. The
// moment that actually matters is the visitor leaving for the chat, which
// flushes on unmount regardless; this only stops a long drawing being
// re-serialized on every single stroke.
const PERSIST_DEBOUNCE_MS = 600

// Why this page is not being kept. Set when a write is refused, cleared
// only by starting a fresh page - it describes a state that stays true
// however much the visitor taps, so it is not dismissible.
type CanvasRefusal = 'page-full' | 'storage-unavailable' | null

// What the bar above the paper is showing. The "start fresh?" question is
// tracked SEPARATELY from the refusal above, and merely covers it while it
// is open: folding both into one value let "Never mind" clear a refusal
// the visitor still needed to see, leaving them silently unsaved with an
// empty bar. Found in review of the demo port; fixed in both copies.
type CanvasNotice = CanvasRefusal | 'confirm-new-page'

// How long a save may be deferred by continuous drawing before it happens
// anyway. Without a ceiling, every stroke restarts the debounce, so a
// child drawing without pausing writes NOTHING - and a page that is never
// written is also a page whose budget is never checked, so the "this is
// getting full" warning would arrive only once it was too late.
const PERSIST_MAX_WAIT_MS = 3_000

const HEX_COLOR = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i

// canvasPersistence.parsePage already rejects anything structurally wrong;
// these are the narrower question of whether the VALUES are ones this
// component still recognizes, since an unknown paper style or a non-color
// string would otherwise reach the draw loop and render nothing at all.
function safePaperStyle(value: string | undefined, fallback: PaperStyle): PaperStyle {
  return PAPER_ORDER.includes(value as PaperStyle) ? (value as PaperStyle) : fallback
}
function safeColor(value: string | undefined, fallback: string): string {
  return value && HEX_COLOR.test(value) ? value : fallback
}

function downloadFilename(now: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  const stamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`
  return `bede-drawing-${stamp}.png`
}

export default function HandwritingCanvas({ onSubmit, onCancel, subject, gradeStage, persistKey }: HandwritingCanvasProps) {
  const { t } = useTranslation()
  // Read once, on mount. Pruning here means a tab that has been through
  // more than one demo code never holds more than the one page the budget
  // is stated for.
  const [restored] = useState(() => {
    if (!persistKey) return null
    pruneOtherPages(persistKey)
    return loadPage(persistKey)
  })
  const [paperStyle, setPaperStyle] = useState<PaperStyle>(() =>
    safePaperStyle(restored?.paperStyle, paperStyleFor(subject)),
  )
  const ruling = RULING_BY_STAGE[gradeStage ?? ''] ?? DEFAULT_RULING
  const [paperColor, setPaperColor] = useState<string>(() => safeColor(restored?.paperColor, PARCHMENT_BG))
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  // The neutral backdrop the paper sits in on screen — measured to letterbox
  // the paper (see the effect below) so the paper itself always keeps the
  // real page's 8.5:11 aspect ratio, whatever shape the browser window is.
  const wrapperRef = useRef<HTMLDivElement>(null)
  const [paperBox, setPaperBox] = useState<{ width: number; height: number }>({
    width: CANVAS_WIDTH,
    height: CANVAS_HEIGHT,
  })
  const isDrawingRef = useRef(false)
  const currentStrokeRef = useRef<Point[]>([])
  const strokesRef = useRef<Stroke[]>(
    (restored?.strokes ?? []).map((stroke) => ({
      points: stroke.points,
      width: stroke.width,
      color: safeColor(stroke.color, PALETTE[0].value),
      isEraser: stroke.isEraser,
    })),
  )
  const dprRef = useRef(window.devicePixelRatio || 1)

  // Force re-render when strokes change so undo button updates
  const [strokeCount, setStrokeCount] = useState(strokesRef.current.length)
  // Undone strokes, waiting for Redo. A NEW stroke invalidates the stack
  // (classic paint-app behavior) — you can't redo on top of a divergence.
  const redoStackRef = useRef<Stroke[]>([])
  const [redoCount, setRedoCount] = useState(0)

  // Paint controls — MS Paint/Preview-style: pick a tool, a size, a color.
  // Kept as plain state (not refs) so the toolbar re-renders immediately;
  // the pointer handlers below are plain functions re-created each render,
  // so they always see the latest selection with no extra plumbing.
  const [tool, setTool] = useState<Tool>('pen')
  const [sizePreset, setSizePreset] = useState<SizePreset>('medium')
  const [color, setColor] = useState<string>(PALETTE[0].value)

  // ── Keeping the page across a trip back to the chat ──────────────────────
  // See canvasPersistence.ts. `keeping` is the honest answer to "will this
  // page still be here when I come back": it goes false the first time a
  // write is refused and stays false until a fresh page is started, so the
  // notice the visitor is shown and what is actually stored never disagree.
  const [refusal, setRefusal] = useState<CanvasRefusal>(null)
  const [confirmingNewPage, setConfirmingNewPage] = useState(false)
  const [nearlyFull, setNearlyFull] = useState(false)
  // The question, while it is open, covers the refusal underneath it; the
  // refusal comes back if they answer "Never mind".
  const notice: CanvasNotice = confirmingNewPage ? 'confirm-new-page' : refusal
  const keepingRef = useRef(true)
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // When the oldest un-saved change happened, for PERSIST_MAX_WAIT_MS.
  const pendingSinceRef = useRef<number | null>(null)
  // Whether anything has actually been written for this page yet. Keeps an
  // empty page from being written after a fresh start: "New page clears the
  // stored drawing" has to stay literally true, and it is a promise made
  // publicly in the demo's case (site/privacy/index.html).
  const wroteRef = useRef(false)

  // `final` marks the unmount flush: the component is going away, so there
  // is no longer any way to tell the visitor a refusal happened - which is
  // exactly why a refusal there must not also delete the page they safely
  // stored minutes ago (see canvasPersistence's SaveOptions).
  const writePage = useCallback((options: { final?: boolean } = {}) => {
    if (!persistKey || !keepingRef.current) return
    // Nothing drawn and nothing written yet: leave storage untouched, so
    // "New page clears the stored drawing" - a promise this one makes
    // publicly, in site/privacy/index.html - stays literally true instead
    // of being followed by an empty page written on the way out.
    if (!strokesRef.current.length && !wroteRef.current) return
    // isEraser is optional on the in-memory stroke and required in storage:
    // "absent" and "false" mean the same thing to this canvas, and picking
    // one of them at the boundary keeps the stored shape unambiguous.
    const strokes = strokesRef.current.map((stroke) => ({ ...stroke, isEraser: !!stroke.isEraser }))
    const result = savePage(
      persistKey,
      { strokes, paperStyle, paperColor },
      { dropStoredOnRefusal: !options.final },
    )
    if (result.ok) {
      wroteRef.current = true
      setNearlyFull(result.nearlyFull)
      return
    }
    if (options.final) {
      // Nobody left to tell. Deliberately does NOT set keepingRef false:
      // this instance is over, and the next mount starts clean.
      return
    }
    // Stop trying: every further attempt fails the same way, and the visitor
    // has been told once. Only starting a fresh page clears this.
    keepingRef.current = false
    setNearlyFull(false)
    setRefusal(result.reason === 'over-budget' ? 'page-full' : 'storage-unavailable')
  }, [persistKey, paperStyle, paperColor])

  // Held in a ref so the unmount flush below calls the CURRENT writePage
  // without re-registering (and therefore re-running) its cleanup whenever
  // the paper style or color changes.
  const writePageRef = useRef(writePage)
  useEffect(() => { writePageRef.current = writePage })

  const schedulePersist = useCallback(() => {
    if (!persistKey) return
    const now = Date.now()
    if (pendingSinceRef.current === null) pendingSinceRef.current = now
    // Drawing without pausing must not defer the write forever - see
    // PERSIST_MAX_WAIT_MS.
    if (now - pendingSinceRef.current >= PERSIST_MAX_WAIT_MS) {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
      saveTimerRef.current = null
      pendingSinceRef.current = null
      writePageRef.current()
      return
    }
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(() => {
      saveTimerRef.current = null
      pendingSinceRef.current = null
      writePageRef.current()
    }, PERSIST_DEBOUNCE_MS)
  }, [persistKey])

  // The moment the whole feature exists for: the visitor pressed Cancel or
  // Done and this component is going away. Flush synchronously rather than
  // waiting out the debounce, which would never fire.
  useEffect(() => {
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
      writePageRef.current({ final: true })
    }
  }, [])

  // Paper style and color are part of the page too - a visitor who set up
  // slate graph paper should find slate graph paper, not just their strokes.
  useEffect(() => {
    schedulePersist()
  }, [paperStyle, paperColor, schedulePersist])

  // Fits the largest 8.5:11 box into the available backdrop — the same
  // letterbox math a photo viewer uses — so the on-screen drawing area is
  // always shaped like the real sheet of paper that comes out of a save or
  // a print, whatever shape the browser window itself is.
  useEffect(() => {
    const wrapper = wrapperRef.current
    if (!wrapper) return
    const fit = () => {
      const availW = wrapper.clientWidth
      const availH = wrapper.clientHeight
      let width = availW
      let height = width / PAGE_ASPECT
      if (height > availH) {
        height = availH
        width = height * PAGE_ASPECT
      }
      setPaperBox({ width, height })
    }
    fit()
    const observer = new ResizeObserver(fit)
    observer.observe(wrapper)
    return () => observer.disconnect()
  }, [])

  const initCanvas = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const dpr = window.devicePixelRatio || 1
    dprRef.current = dpr
    // The backing store is always the fixed physical page resolution, not
    // the on-screen display size — see CANVAS_WIDTH/HEIGHT's comment above.
    canvas.width = CANVAS_WIDTH * dpr
    canvas.height = CANVAS_HEIGHT * dpr
    const ctx = canvas.getContext('2d')!
    ctx.scale(dpr, dpr)
    drawPaper(ctx, CANVAS_WIDTH, CANVAS_HEIGHT, paperStyle, paperColor, ruling)
  }, [paperStyle, paperColor, ruling])

  // Redraw all strokes from scratch onto the canvas
  const redrawAll = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    const dpr = dprRef.current

    // Clear to paper (background + ruling/grid)
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.scale(dpr, dpr)
    drawPaper(ctx, canvas.width / dpr, canvas.height / dpr, paperStyle, paperColor, ruling)

    // Replay all strokes — an "eraser" stroke is just one whose color is the
    // background color, so replaying strokes in order naturally covers
    // whatever ink was under it with no separate erase code path.
    for (const stroke of strokesRef.current) {
      const strokeColor = stroke.isEraser ? paperColor : stroke.color
      if (stroke.points.length < 2) {
        // Single dot
        const pt = stroke.points[0]
        if (!pt) continue
        ctx.beginPath()
        ctx.arc(pt.x, pt.y, stroke.width / 2, 0, Math.PI * 2)
        ctx.fillStyle = strokeColor
        ctx.fill()
        continue
      }
      ctx.beginPath()
      ctx.strokeStyle = strokeColor
      ctx.lineWidth = stroke.width
      ctx.lineCap = 'round'
      ctx.lineJoin = 'round'
      ctx.moveTo(stroke.points[0].x, stroke.points[0].y)
      for (let i = 1; i < stroke.points.length; i++) {
        ctx.lineTo(stroke.points[i].x, stroke.points[i].y)
      }
      ctx.stroke()
    }
  }, [paperStyle, paperColor, ruling])

  useEffect(() => {
    initCanvas()
    // Switching paper mid-drawing repaints the ruling underneath and replays
    // every stroke on top — nothing the child drew is lost. (initCanvas
    // paints the fresh paper; the replay restores their work.)
    redrawAll()
  }, [initCanvas, redrawAll])

  // Get canvas-relative coordinates from pointer event — works identically
  // for a Surface Pen, Apple Pencil, a finger, or a mouse, since the
  // Pointer Events API (not separate mouse/touch handlers) unifies all of
  // them, pressure included where the hardware reports it.
  // The displayed box (rect) can be smaller than the fixed CANVAS_WIDTH/HEIGHT
  // drawing space (it's letterboxed to fit the screen — see paperBox above),
  // so pointer position is rescaled into that drawing space rather than used
  // as raw display pixels. This is also what makes the coordinate space
  // independent of window size: the same physical spot on the page always
  // maps to the same stored (x, y), whatever size the browser happens to be.
  const getPos = (e: React.PointerEvent<HTMLCanvasElement>): Point => {
    const canvas = canvasRef.current!
    const rect = canvas.getBoundingClientRect()
    return {
      x: (e.clientX - rect.left) * (CANVAS_WIDTH / rect.width),
      y: (e.clientY - rect.top) * (CANVAS_HEIGHT / rect.height),
      pressure: e.pressure,
    }
  }

  const getStrokeWidth = (pressure: number) => {
    const { min, max, base } = SIZE_PRESETS[sizePreset]
    return Math.max(min, Math.min(max, pressure * max || base))
  }

  // Eraser paints flat parchment, same trick redrawAll's own comment
  // describes for ink — on ruled/gridded paper this also erases whatever
  // ruling was under the stroke (a flat patch with no lines in it), same
  // as scribbling over a real ruled sheet with white-out. Redrawing the
  // ruling underneath the erased patch would need a separate ink layer
  // composited over the paper background; not worth the added complexity
  // for a homeschool sketch/practice tool.
  const activeColor = () => (tool === 'eraser' ? paperColor : color)

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    e.preventDefault()
    // Capture pointer so we receive move events even outside canvas bounds
    canvasRef.current?.setPointerCapture(e.pointerId)
    isDrawingRef.current = true
    const pt = getPos(e)
    currentStrokeRef.current = [pt]

    // Draw a dot immediately so single taps show ink
    const canvas = canvasRef.current!
    const ctx = canvas.getContext('2d')!
    const w = getStrokeWidth(pt.pressure)
    ctx.beginPath()
    ctx.arc(pt.x, pt.y, w / 2, 0, Math.PI * 2)
    ctx.fillStyle = activeColor()
    ctx.fill()
  }

  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    e.preventDefault()
    if (!isDrawingRef.current) return

    const pt = getPos(e)
    const prev = currentStrokeRef.current.at(-1)!
    currentStrokeRef.current.push(pt)

    const canvas = canvasRef.current!
    const ctx = canvas.getContext('2d')!
    const w = getStrokeWidth(pt.pressure)

    ctx.beginPath()
    ctx.strokeStyle = activeColor()
    ctx.lineWidth = w
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    ctx.moveTo(prev.x, prev.y)
    ctx.lineTo(pt.x, pt.y)
    ctx.stroke()
  }

  const onPointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    e.preventDefault()
    if (!isDrawingRef.current) return
    isDrawingRef.current = false

    const points = currentStrokeRef.current
    if (points.length > 0) {
      const avgPressure = points.reduce((s, p) => s + p.pressure, 0) / points.length
      strokesRef.current.push({
        points,
        width: getStrokeWidth(avgPressure),
        color: activeColor(),
        isEraser: tool === 'eraser',
      })
      setStrokeCount(strokesRef.current.length)
      redoStackRef.current = []
      setRedoCount(0)
      schedulePersist()
    }
    currentStrokeRef.current = []
  }

  const onPointerLeave = (e: React.PointerEvent<HTMLCanvasElement>) => {
    // Only end stroke if pointer is truly gone (not just leaving for a moment)
    if (isDrawingRef.current) {
      onPointerUp(e)
    }
  }

  const handleUndo = () => {
    const undone = strokesRef.current.pop()
    if (!undone) return
    redoStackRef.current.push(undone)
    setRedoCount(redoStackRef.current.length)
    setStrokeCount(strokesRef.current.length)
    redrawAll()
    schedulePersist()
  }

  const handleRedo = () => {
    // `redone`, not `restored`: that name now belongs to the page this
    // canvas came back to at mount.
    const redone = redoStackRef.current.pop()
    if (!redone) return
    strokesRef.current.push(redone)
    setRedoCount(redoStackRef.current.length)
    setStrokeCount(strokesRef.current.length)
    redrawAll()
    schedulePersist()
  }

  // A clean sheet, on purpose. This is the visitor's own control over how
  // long a page lasts: it is kept for as long as they want it and goes when
  // they say so, rather than on a timer or a rule they cannot see. The
  // stored copy goes with it - a page they chose to put away must not
  // reappear the next time they open the canvas.
  const startNewPage = () => {
    strokesRef.current = []
    setStrokeCount(0)
    redoStackRef.current = []
    setRedoCount(0)
    keepingRef.current = true
    wroteRef.current = false
    setNearlyFull(false)
    setRefusal(null)
    setConfirmingNewPage(false)
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current)
      saveTimerRef.current = null
    }
    pendingSinceRef.current = null
    if (persistKey) clearPage(persistKey)
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    const dpr = dprRef.current
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.scale(dpr, dpr)
    drawPaper(ctx, canvas.width / dpr, canvas.height / dpr, paperStyle, paperColor, ruling)
  }

  // Ask first when there is work on the page. Before the page persisted at
  // all, clearing only threw away what was on screen in front of the
  // visitor; now it throws away something that would otherwise have
  // survived the rest of the session, which is worth one question.
  const handleNewPage = () => {
    if (strokeCount === 0) {
      startNewPage()
      return
    }
    setConfirmingNewPage(true)
  }

  // Client-side only, exactly like handlePrint below: the already-rendered
  // bitmap goes straight to the visitor's own device through the browser's
  // own download, with no endpoint, no request, and nothing leaving the
  // tab. This is what makes "your page is too big to keep" a fair thing to
  // say - they are told while the drawing is still in front of them.
  const handleSaveToDevice = () => {
    const canvas = canvasRef.current
    if (!canvas) return
    const filename = downloadFilename(new Date())
    const trigger = (href: string, revoke?: () => void) => {
      const link = document.createElement('a')
      link.href = href
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      revoke?.()
    }
    if (typeof canvas.toBlob === 'function') {
      canvas.toBlob((blob) => {
        if (!blob) return
        const url = URL.createObjectURL(blob)
        trigger(url, () => setTimeout(() => URL.revokeObjectURL(url), 0))
      }, 'image/png')
      return
    }
    trigger(canvas.toDataURL('image/png'))
  }

  const handleDone = () => {
    const canvas = canvasRef.current
    if (!canvas) return
    onSubmit(canvas.toDataURL('image/png'))
  }

  // The only exportable/printable surface in this app (see PRINT_AREA_ID's
  // own comment above) — purely client-side, the browser's native print
  // dialog against the already-rendered canvas bitmap wrapped in
  // #handwriting-print-area below. Works on blank paper too (no strokes
  // required), so a visitor can print composition or graph paper on its
  // own, not only paper they've already drawn on.
  const handlePrint = () => {
    window.print()
  }

  // The backing store is now a fixed physical resolution (CANVAS_WIDTH x
  // CANVAS_HEIGHT), not tied to the on-screen display size, so an ordinary
  // window resize just reflows the letterboxed paperBox CSS size — the
  // browser scales the same raster to fit, same as an <img>, with no redraw
  // needed. Only a devicePixelRatio change (e.g. dragging the window to a
  // monitor with different pixel density) needs the backing store rebuilt
  // at the new dpr, so re-init and replay strokes just for that case.
  useEffect(() => {
    const handleResize = () => {
      const dpr = window.devicePixelRatio || 1
      if (dpr === dprRef.current) return
      initCanvas()
      redrawAll()
    }

    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [initCanvas, redrawAll])

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-parchment-50">
      {/* Toolbar */}
      <div className="flex items-center justify-between gap-2 px-4 py-2 bg-white shadow-sm border-b border-parchment-200 flex-shrink-0 overflow-x-auto">
        {/* Cancel */}
        <button
          onClick={onCancel}
          className="flex items-center gap-1.5 text-gray-500 hover:text-gray-700 px-3 py-2 rounded-lg transition-colors flex-shrink-0"
        >
          <X size={18} />
          <span className="text-sm font-medium">{t('canvas.cancel')}</span>
        </button>

        {/* Right actions */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={handleUndo}
            disabled={strokeCount === 0}
            title={t('canvas.undoTitle')}
            className="flex items-center gap-1 px-3 py-2 rounded-lg text-gray-600 hover:bg-gray-100 disabled:opacity-30 transition-colors text-sm"
          >
            <Undo2 size={16} />
            <span className="hidden sm:inline">{t('canvas.undo')}</span>
          </button>
          <button
            onClick={handleRedo}
            disabled={redoCount === 0}
            title={t('canvas.redo')}
            className="flex items-center gap-1 px-3 py-2 rounded-lg text-gray-600 hover:bg-gray-100 disabled:opacity-30 transition-colors text-sm"
          >
            <Redo2 size={16} />
            <span className="hidden sm:inline">{t('canvas.redo')}</span>
          </button>
          <button
            onClick={handleNewPage}
            title={t('canvas.newPageTitle')}
            className="flex items-center gap-1 px-3 py-2 rounded-lg text-gray-600 hover:bg-gray-100 transition-colors text-sm"
          >
            <FilePlus2 size={16} />
            <span className="hidden sm:inline">{t('canvas.newPage')}</span>
          </button>
          <button
            onClick={handleSaveToDevice}
            title={t('canvas.saveTitle')}
            className="flex items-center gap-1 px-3 py-2 rounded-lg text-gray-600 hover:bg-gray-100 transition-colors text-sm"
          >
            <Download size={16} />
            <span className="hidden sm:inline">{t('canvas.save')}</span>
          </button>
          <button
            onClick={handlePrint}
            title={t('canvas.printTitle')}
            className="flex items-center gap-1 px-3 py-2 rounded-lg text-gray-600 hover:bg-gray-100 transition-colors text-sm"
          >
            <Printer size={16} />
            <span className="hidden sm:inline">{t('canvas.print')}</span>
          </button>
          <button
            onClick={handleDone}
            title={t('canvas.doneTitle')}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-navy-500 text-white hover:bg-navy-600 transition-colors font-medium text-sm min-h-[44px]"
          >
            <Check size={16} />
            <span>{t('canvas.done')}</span>
          </button>
        </div>
      </div>

      {/* Paper picker — the child's choice, regardless of subject. Its own
          row, not squeezed between Cancel and the action buttons: on a
          phone-width screen (not just the "portrait tablet" the old inline
          layout was sized for), Cancel plus five action buttons alone
          already consume nearly the full width, which used to leave this
          picker no visible room at all — zero paper-type labels showing and
          the Done button clipped off the right edge of the screen, a real
          reported bug. A full-width row has enough space for all six styles
          on most phones; overflow-x-auto is the fallback for the narrowest. */}
      <div className="flex items-center gap-1 px-4 py-1.5 bg-white border-b border-parchment-200 flex-shrink-0 overflow-x-auto">
        <div className="flex items-center gap-1 bg-parchment-100 rounded-lg p-1">
          {PAPER_ORDER.map((style) => (
            <button
              key={style}
              onClick={() => setPaperStyle(style)}
              aria-pressed={paperStyle === style}
              title={t('canvas.paperTitle', { name: t(`canvas.paperStyle.${style}`) })}
              className={`px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors flex-shrink-0 ${
                paperStyle === style ? 'bg-white shadow-sm text-navy-700' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {t(`canvas.paperStyle.${style}`)}
            </button>
          ))}
        </div>
      </div>

      {/* Paint controls — tool, size, color. A second row keeps the primary
          Cancel/Undo/Clear/Done actions above uncluttered on a narrow
          tablet screen (Surface Pro / iPad portrait width included). */}
      <div className="flex items-center gap-3 px-4 py-2 bg-white border-b border-parchment-200 flex-shrink-0 overflow-x-auto">
        {/* Pen / eraser */}
        <div className="flex items-center gap-1 bg-parchment-100 rounded-lg p-1 flex-shrink-0">
          <button
            onClick={() => setTool('pen')}
            title={t('canvas.tool.pen')}
            aria-pressed={tool === 'pen'}
            className={`p-2 rounded-md transition-colors ${tool === 'pen' ? 'bg-white shadow-sm text-navy-700' : 'text-gray-500 hover:text-gray-700'}`}
          >
            <Pencil size={16} />
          </button>
          <button
            onClick={() => setTool('eraser')}
            title={t('canvas.tool.eraser')}
            aria-pressed={tool === 'eraser'}
            className={`p-2 rounded-md transition-colors ${tool === 'eraser' ? 'bg-white shadow-sm text-navy-700' : 'text-gray-500 hover:text-gray-700'}`}
          >
            <Eraser size={16} />
          </button>
        </div>

        {/* Brush size */}
        <div className="flex items-center gap-1 bg-parchment-100 rounded-lg p-1 flex-shrink-0">
          {(Object.keys(SIZE_PRESETS) as SizePreset[]).map((preset) => (
            <button
              key={preset}
              onClick={() => setSizePreset(preset)}
              title={t(`canvas.brush.${preset}`)}
              aria-pressed={sizePreset === preset}
              className={`w-8 h-8 rounded-md flex items-center justify-center transition-colors ${sizePreset === preset ? 'bg-white shadow-sm' : 'hover:bg-white/60'}`}
            >
              <span
                className="rounded-full bg-navy-700"
                style={{ width: SIZE_PRESETS[preset].dot, height: SIZE_PRESETS[preset].dot }}
              />
            </button>
          ))}
        </div>

        {/* Color palette */}
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {PALETTE.map((swatch) => (
            <button
              key={swatch.value}
              onClick={() => { setColor(swatch.value); setTool('pen') }}
              title={t(`canvas.ink.${swatch.id}`)}
              aria-pressed={tool === 'pen' && color === swatch.value}
              className={`w-7 h-7 rounded-full border-2 transition-transform flex-shrink-0 ${
                tool === 'pen' && color === swatch.value ? 'border-navy-500 scale-110' : 'border-white shadow-sm'
              }`}
              style={{ backgroundColor: swatch.value }}
            />
          ))}
          {/* Native color picker — the "more colors" escape hatch, same idea
              as MS Paint's "Edit Colors..." dialog. Native <input type="color">
              gives a system color picker on every platform this app targets
              (including Surface Pro/iPad browsers) with no extra dependency. */}
          <label
            title={t('canvas.moreColors')}
            className="w-7 h-7 rounded-full border-2 border-white shadow-sm flex-shrink-0 cursor-pointer overflow-hidden relative"
            style={{ background: 'conic-gradient(red, yellow, lime, cyan, blue, magenta, red)' }}
          >
            <input
              type="color"
              value={color}
              onChange={(e) => { setColor(e.target.value); setTool('pen') }}
              className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
            />
          </label>
        </div>

        {/* Paper color — construction paper + slate chalkboard. Square
            swatches so they read as PAPER, distinct from the round ink dots. */}
        <div className="flex items-center gap-1.5 flex-shrink-0 pl-3 border-l border-parchment-200">
          <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">{t('canvas.paperHeading')}</span>
          {PAPER_COLORS.map((swatch) => (
            <button
              key={swatch.value}
              onClick={() => setPaperColor(swatch.value)}
              title={t('canvas.paperTitle', { name: t(`canvas.paperColor.${swatch.id}`) })}
              aria-pressed={paperColor === swatch.value}
              className={`w-7 h-7 rounded-md border-2 transition-transform flex-shrink-0 ${
                paperColor === swatch.value ? 'border-navy-500 scale-110' : 'border-white shadow-sm'
              }`}
              style={{ backgroundColor: swatch.value }}
            />
          ))}
        </div>
      </div>

      {/* The one place this canvas ever speaks to the visitor in words: what
          is about to happen to their page. Deliberately a bar above the
          paper rather than a dialog over it - nothing here blocks drawing,
          and the drawing stays fully in view (and fully saveable) while
          they decide. The two "not being kept" notices carry no dismiss:
          the state they describe is still true after any amount of tapping,
          and only starting a fresh page ends it.

          Plain flex siblings, not an overlay on the paper: an earlier
          version of this port drew them as an overlay because the canvas
          used to size its backing store to whatever box it was given, so a
          bar appearing on its own would shrink that box out from under an
          already-fixed-resolution bitmap and land new strokes above the
          stylus. Now that the backing store is the fixed CANVAS_WIDTH x
          CANVAS_HEIGHT page above and getPos rescales through the
          canvas's own bounding rect, a notice changing how much vertical
          space is left for the paper just reflows the letterboxed display
          size (see the paperBox effect above) - pointer mapping is
          unaffected, so the overlay workaround is no longer needed and
          would only be dead weight to carry forward. */}
      {notice && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2 bg-amber-50 border-b border-amber-200 flex-shrink-0">
          <p className="text-sm text-amber-900 flex-1 min-w-[12rem]">
            {notice === 'page-full' && t('canvas.pageFull')}
            {notice === 'storage-unavailable' && t('canvas.storageUnavailable')}
            {notice === 'confirm-new-page' && t('canvas.confirmNewPage')}
          </p>
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              onClick={handleSaveToDevice}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-white border border-amber-300 text-amber-900 hover:bg-amber-100 transition-colors text-sm font-medium min-h-[44px]"
            >
              <Download size={16} />
              <span>{notice === 'confirm-new-page' ? t('canvas.saveFirst') : t('canvas.saveToDevice')}</span>
            </button>
            <button
              onClick={startNewPage}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-navy-500 text-white hover:bg-navy-600 transition-colors text-sm font-medium min-h-[44px]"
            >
              <FilePlus2 size={16} />
              <span>{t('canvas.startFresh')}</span>
            </button>
            {notice === 'confirm-new-page' && (
              <button
                onClick={() => setConfirmingNewPage(false)}
                className="px-3 py-2 rounded-lg text-amber-900 hover:bg-amber-100 transition-colors text-sm min-h-[44px]"
              >
                {t('canvas.neverMind')}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Quiet heads-up well before anything is at risk - a line of text, no
          buttons, nothing to answer. */}
      {!notice && nearlyFull && (
        <div className="px-4 py-1.5 bg-amber-50 border-b border-amber-200 flex-shrink-0">
          <p className="text-xs text-amber-800">{t('canvas.nearlyFull')}</p>
        </div>
      )}

      {/* Backdrop — letterboxes the paper (see the paperBox-fitting effect
          above) so it always keeps a real letter page's 8.5:11 shape,
          whatever shape the browser window itself is. */}
      <div ref={wrapperRef} className="flex-1 relative flex items-center justify-center overflow-hidden bg-parchment-200/40">
        {/* The paper itself — id'd so the print stylesheet below can isolate
            just this (background + ruling + strokes), not the toolbar or
            backdrop, when handlePrint() triggers window.print(). Sized to
            paperBox on screen (a scaled-down view of the fixed physical
            drawing resolution — see CANVAS_WIDTH/HEIGHT) but always an
            exact 8.5in x 11in at print time (below) and always the same
            physical pixel count when saved, so what's drawn on screen is
            what prints and what saves, true to scale regardless of window
            size — closing the gap where a phone visitor's saved keepsake
            used to come out as a small, blurry image. */}
        <div
          ref={containerRef}
          id={PRINT_AREA_ID}
          className="relative bg-white shadow-md"
          style={{ width: paperBox.width, height: paperBox.height }}
        >
          <canvas
            ref={canvasRef}
            className="absolute inset-0 w-full h-full"
            style={{
              touchAction: 'none',
              cursor: 'crosshair',
              // Chrome/Edge/Firefox all default print rendering to omit
              // background colors/light strokes to save ink — this asks them
              // not to, though the user's own "background graphics" print
              // option (off by default in most browsers) still wins if set.
              printColorAdjust: 'exact',
              WebkitPrintColorAdjust: 'exact',
            } as React.CSSProperties}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerLeave={onPointerLeave}
          />
        </div>
      </div>

      {/* Scoped to this component's own overlay — isolates the paper
          (#handwriting-print-area) as the only thing that prints, hiding
          the toolbar and backdrop behind it. Forces portrait Letter with
          zero page margin and sizes the paper to the physical page exactly
          (no percentage-based stretch-to-fill) so it always prints at the
          same true scale and orientation as a real ruled sheet, regardless
          of the on-screen window's shape. */}
      <style>{`
        @media print {
          @page { size: letter portrait; margin: 0; }
          body * { visibility: hidden !important; }
          #${PRINT_AREA_ID}, #${PRINT_AREA_ID} * { visibility: visible !important; }
          #${PRINT_AREA_ID} {
            /* !important: React's inline style={} (setting paperBox's
               on-screen letterboxed px size) otherwise wins the cascade
               over this stylesheet and the page would print at whatever
               size it happened to be on screen instead of true 8.5x11in. */
            position: fixed !important;
            inset: 0 !important;
            width: ${PAGE_WIDTH_IN}in !important;
            height: ${PAGE_HEIGHT_IN}in !important;
            box-shadow: none !important;
          }
        }
      `}</style>
    </div>
  )
}
