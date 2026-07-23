import { useRef, useEffect, useCallback, useState } from 'react'
import { X, Undo2, Redo2, Trash2, Check, Pencil, Eraser, Printer } from 'lucide-react'
import type { Subject } from '../types'

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
}

// True-to-scale printing: the canvas's internal drawing resolution is
// pinned to US Letter at 96 CSS px/inch — the same convention every ruling
// constant below is measured in — regardless of the on-screen viewport's
// size or shape. Before this existed, ruling was drawn relative to
// canvas.offsetWidth/Height, i.e. whatever CSS pixels the toolbar's flex-1
// container happened to occupy (often landscape-shaped on a laptop
// browser window). Printing that stretched it non-uniformly to fill
// whatever page size/orientation the browser picked, so neither the
// ruling spacing nor the page orientation matched a real sheet of ruled
// letter paper. Pinning the backing resolution here, letterboxing the
// on-screen display to the same 8.5:11 aspect ratio (see the paperBox
// sizing effect below), and forcing @page to portrait Letter with no
// stretch in the print stylesheet makes on-screen drawing and the printed
// page the same shape at the same scale.
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
  { name: 'Parchment', value: PARCHMENT_BG },
  { name: 'White', value: '#ffffff' },
  { name: 'Sunshine', value: '#fdf3cf' },
  { name: 'Rose', value: '#fbe4e4' },
  { name: 'Sage', value: '#e4efe4' },
  { name: 'Sky', value: '#e0ecf9' },
  { name: 'Slate', value: '#2e3a44' },
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

// Graph/dot grid scaled to grade stage, using the same real-world classroom
// paper sizes a parent would actually buy — K-2 gets big 1" squares (easy
// counting, coloring, and early arrays); 3-5 gets a standard 1/2" grid; 6-8
// gets the tighter 1/4" grid this canvas always drew before grade scaling
// existed (standard pre-algebra/engineering graph paper). Dots share the
// same pitch as the graph grid at each stage so work translates between the
// two paper styles.
const GRID_SPACING_BY_STAGE: Record<string, number> = {
  'K-2': 1 * PRINT_DPI,
  '3-5': 0.5 * PRINT_DPI,
  '6-8': 0.25 * PRINT_DPI,
}
const DEFAULT_GRID_SPACING = GRID_SPACING_BY_STAGE['3-5']
const DOT_RADIUS = 1.5
// Composition ruling scaled to the writer, not one-size-fits-all, using
// the real inch spacings of classroom ruled paper (converted to px at
// PRINT_DPI so they print true-to-scale — see CANVAS_WIDTH/HEIGHT above).
// The dashed guide midline sits halfway between one baseline and the next,
// matching the classic elementary layout (top space, dashed midline,
// solid baseline) — K-2 writes big and needs the midline (5/8" primary
// ruling); 3-5 gets standard 3/8" ruling; 6-8 gets a tighter 1/4"
// college-style rule with no midline.
const RULING_BY_STAGE: Record<string, { lineHeight: number; midline: boolean }> = {
  'K-2': { lineHeight: 0.625 * PRINT_DPI, midline: true },
  '3-5': { lineHeight: 0.375 * PRINT_DPI, midline: true },
  '6-8': { lineHeight: 0.25 * PRINT_DPI, midline: false },
}
const DEFAULT_RULING = RULING_BY_STAGE['3-5']
// Nature-journal split page: the top portion is open sketch space (the
// specimen drawing), the bottom is ruled for the written observation —
// one page holds both halves of a Charlotte Mason notebook entry. A short
// date line sits top-right, as on a real nature-notebook page.
const JOURNAL_SPLIT_RATIO = 0.58
const JOURNAL_DATE_LINE_Y = 34
const JOURNAL_DATE_LINE_WIDTH = 150
// Musical staff paper: five lines per staff. K-2 gets "big note" beginner
// manuscript paper — the noticeably wider line gap published beginner staff
// paper uses so a young child can place large note heads by hand; 3-5 and
// 6-8 both use standard manuscript spacing (staff notation itself doesn't
// shrink with age the way handwriting ruling does, so there's no reason to
// tighten it further for older students — this is the exact spacing this
// canvas always drew before grade scaling existed). groupSpacing (top of one
// staff to the top of the next) and topMargin scale with lineGap so the
// clear space around each staff stays proportional at every stage.
const STAFF_BY_STAGE: Record<string, { lineGap: number; groupSpacing: number; topMargin: number }> = {
  'K-2': { lineGap: 0.1875 * PRINT_DPI, groupSpacing: 1.25 * PRINT_DPI, topMargin: 0.5 * PRINT_DPI },
  '3-5': { lineGap: 0.125 * PRINT_DPI, groupSpacing: 1 * PRINT_DPI, topMargin: 0.5 * PRINT_DPI },
  '6-8': { lineGap: 0.125 * PRINT_DPI, groupSpacing: 1 * PRINT_DPI, topMargin: 0.5 * PRINT_DPI },
}
const DEFAULT_STAFF = STAFF_BY_STAGE['3-5']

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

const PAPER_LABEL: Record<PaperStyle, string> = {
  composition: 'Composition',
  graph: 'Graph',
  dots: 'Dots',
  staff: 'Staff',
  journal: 'Journal',
  blank: 'Blank',
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
  gridSpacing: number,
  staff: { lineGap: number; groupSpacing: number; topMargin: number },
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
    for (let x = gridSpacing; x < width; x += gridSpacing) {
      ctx.beginPath()
      ctx.moveTo(x + 0.5, 0)
      ctx.lineTo(x + 0.5, height)
      ctx.stroke()
    }
    for (let y = gridSpacing; y < height; y += gridSpacing) {
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
    for (let x = gridSpacing; x < width; x += gridSpacing) {
      for (let y = gridSpacing; y < height; y += gridSpacing) {
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
    for (let top = staff.topMargin; top + 4 * staff.lineGap <= height; top += staff.groupSpacing) {
      for (let line = 0; line < 5; line++) {
        const y = top + line * staff.lineGap
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
// to having no export/download functionality anywhere else (see
// core/middleware.py's ExfiltrationGuard on the backend, which blocks any
// endpoint path containing /export, /download, /dump, /backup, /debug and
// strips Content-Disposition: attachment from every response). This is
// entirely client-side: it prints the already-rendered canvas bitmap
// via the browser's own print dialog, with no new backend endpoint and
// nothing sent anywhere, so it never touches that boundary at all.
const PRINT_AREA_ID = 'handwriting-print-area'

// A compact MS-Paint/Preview-style swatch row rather than a full color wheel —
// enough range for a nature-notebook sketch or a math diagram without
// overwhelming a touch toolbar. First entry is the historical default ink
// color this canvas always used, kept as the default selection.
const PALETTE = [
  { name: 'Ink', value: '#1b3a6b' },
  { name: 'Black', value: '#1a1a1a' },
  { name: 'Red', value: '#c0392b' },
  { name: 'Orange', value: '#d9791b' },
  { name: 'Gold', value: '#c9971e' },
  { name: 'Green', value: '#2f7d4f' },
  { name: 'Sky', value: '#2f7fc0' },
  { name: 'Purple', value: '#7a4fa3' },
  { name: 'Brown', value: '#7a5230' },
] as const

type SizePreset = 'thin' | 'medium' | 'thick'
const SIZE_PRESETS: Record<SizePreset, { min: number; max: number; base: number; dot: number }> = {
  thin: { min: 1, max: 3, base: 1.5, dot: 5 },
  medium: { min: 2, max: 6, base: 3, dot: 9 },
  thick: { min: 4, max: 12, base: 6, dot: 14 },
}

type Tool = 'pen' | 'eraser'

export default function HandwritingCanvas({ onSubmit, onCancel, subject, gradeStage }: HandwritingCanvasProps) {
  const [paperStyle, setPaperStyle] = useState<PaperStyle>(() => paperStyleFor(subject))
  const ruling = RULING_BY_STAGE[gradeStage ?? ''] ?? DEFAULT_RULING
  const gridSpacing = GRID_SPACING_BY_STAGE[gradeStage ?? ''] ?? DEFAULT_GRID_SPACING
  const staff = STAFF_BY_STAGE[gradeStage ?? ''] ?? DEFAULT_STAFF
  const [paperColor, setPaperColor] = useState<string>(PARCHMENT_BG)
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
  const strokesRef = useRef<Stroke[]>([])
  const dprRef = useRef(window.devicePixelRatio || 1)

  // Force re-render when strokes change so undo button updates
  const [strokeCount, setStrokeCount] = useState(0)
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

  // Fits the largest 8.5:11 box into the available backdrop — the same
  // letterbox math a photo viewer uses — so the on-screen drawing area is
  // always shaped like the real sheet of paper that will come out of the
  // printer, whatever shape the browser window itself is.
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
    drawPaper(ctx, CANVAS_WIDTH, CANVAS_HEIGHT, paperStyle, paperColor, ruling, gridSpacing, staff)
  }, [paperStyle, paperColor, ruling, gridSpacing, staff])

  // Redraw all strokes from scratch onto the canvas
  const redrawAll = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    const dpr = dprRef.current

    // Clear to paper (background + ruling/grid)
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.scale(dpr, dpr)
    drawPaper(ctx, canvas.width / dpr, canvas.height / dpr, paperStyle, paperColor, ruling, gridSpacing, staff)

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
  }, [paperStyle, paperColor, ruling, gridSpacing, staff])

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
  // them, pressure included where the hardware reports it. The displayed
  // box (rect) can be smaller than the fixed CANVAS_WIDTH/HEIGHT drawing
  // space (it's letterboxed to fit the screen — see paperBox above), so
  // pointer position is rescaled into that drawing space rather than used
  // as raw display pixels.
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
  }

  const handleRedo = () => {
    const restored = redoStackRef.current.pop()
    if (!restored) return
    strokesRef.current.push(restored)
    setRedoCount(redoStackRef.current.length)
    setStrokeCount(strokesRef.current.length)
    redrawAll()
  }

  const handleClear = () => {
    strokesRef.current = []
    setStrokeCount(0)
    redoStackRef.current = []
    setRedoCount(0)
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    const dpr = dprRef.current
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.scale(dpr, dpr)
    drawPaper(ctx, canvas.width / dpr, canvas.height / dpr, paperStyle, paperColor, ruling, gridSpacing, staff)
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
  // required), so a parent/child can print composition or graph paper on
  // its own, not only paper they've already drawn on.
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
          <span className="text-sm font-medium">Cancel</span>
        </button>

        {/* Right actions */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={handleUndo}
            disabled={strokeCount === 0}
            title="Undo last stroke"
            className="flex items-center gap-1 px-3 py-2 rounded-lg text-gray-600 hover:bg-gray-100 disabled:opacity-30 transition-colors text-sm"
          >
            <Undo2 size={16} />
            <span className="hidden sm:inline">Undo</span>
          </button>
          <button
            onClick={handleRedo}
            disabled={redoCount === 0}
            title="Redo"
            className="flex items-center gap-1 px-3 py-2 rounded-lg text-gray-600 hover:bg-gray-100 disabled:opacity-30 transition-colors text-sm"
          >
            <Redo2 size={16} />
            <span className="hidden sm:inline">Redo</span>
          </button>
          <button
            onClick={handleClear}
            disabled={strokeCount === 0}
            title="Clear all"
            className="flex items-center gap-1 px-3 py-2 rounded-lg text-gray-600 hover:bg-gray-100 disabled:opacity-30 transition-colors text-sm"
          >
            <Trash2 size={16} />
            <span className="hidden sm:inline">Clear</span>
          </button>
          <button
            onClick={handlePrint}
            title={`Print this ${PAPER_LABEL[paperStyle].toLowerCase()} paper`}
            className="flex items-center gap-1 px-3 py-2 rounded-lg text-gray-600 hover:bg-gray-100 transition-colors text-sm"
          >
            <Printer size={16} />
            <span className="hidden sm:inline">Print</span>
          </button>
          <button
            onClick={handleDone}
            title="Send drawing"
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-navy-500 text-white hover:bg-navy-600 transition-colors font-medium text-sm min-h-[44px]"
          >
            <Check size={16} />
            <span>Done</span>
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
              title={`${PAPER_LABEL[style]} paper`}
              className={`px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors flex-shrink-0 ${
                paperStyle === style ? 'bg-white shadow-sm text-navy-700' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {PAPER_LABEL[style]}
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
            title="Pen"
            aria-pressed={tool === 'pen'}
            className={`p-2 rounded-md transition-colors ${tool === 'pen' ? 'bg-white shadow-sm text-navy-700' : 'text-gray-500 hover:text-gray-700'}`}
          >
            <Pencil size={16} />
          </button>
          <button
            onClick={() => setTool('eraser')}
            title="Eraser"
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
              title={`${preset[0].toUpperCase()}${preset.slice(1)} brush`}
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
              title={swatch.name}
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
            title="More colors"
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
          <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Paper</span>
          {PAPER_COLORS.map((swatch) => (
            <button
              key={swatch.value}
              onClick={() => setPaperColor(swatch.value)}
              title={`${swatch.name} paper`}
              aria-pressed={paperColor === swatch.value}
              className={`w-7 h-7 rounded-md border-2 transition-transform flex-shrink-0 ${
                paperColor === swatch.value ? 'border-navy-500 scale-110' : 'border-white shadow-sm'
              }`}
              style={{ backgroundColor: swatch.value }}
            />
          ))}
        </div>
      </div>

      {/* Backdrop — letterboxes the paper (see the paperBox-fitting effect
          above) so it always keeps a real letter page's 8.5:11 shape,
          whatever shape the browser window itself is. */}
      <div ref={wrapperRef} className="flex-1 relative flex items-center justify-center overflow-hidden bg-parchment-200/40">
        {/* The paper itself — id'd so the print stylesheet below can isolate
            just this (background + ruling + strokes), not the toolbar or
            backdrop, when handlePrint() triggers window.print(). Sized to
            paperBox on screen (a scaled-down view of the fixed physical
            drawing resolution — see CANVAS_WIDTH/HEIGHT) but always an
            exact 8.5in x 11in at print time (below), so what's drawn on
            screen is what prints, true to scale. */}
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
