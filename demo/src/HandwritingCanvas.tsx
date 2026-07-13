import { useRef, useEffect, useCallback, useState } from 'react'
import { X, Undo2, Trash2, Check, Pencil, Eraser, Printer } from 'lucide-react'
import type { Subject } from './api'

interface Point {
  x: number
  y: number
  pressure: number
}

interface Stroke {
  points: Point[]
  width: number
  color: string
}

interface HandwritingCanvasProps {
  onSubmit: (imageDataUrl: string) => void
  onCancel: () => void
  // Picks the printed/drawn paper style below — mathematics gets graph
  // paper (for showing work, plotting, keeping columns aligned); Art &
  // Music gets staff paper (five-line musical staves for copying a hymn
  // line, notating a melody, or first composition exercises); everything
  // else (written narration, nature-notebook sketches, etc., per
  // invite_handwriting's own scope) gets composition paper, the classic
  // ruled handwriting-practice sheet. Optional/undefined falls back to
  // composition paper.
  subject?: Subject
}

const PARCHMENT_BG = '#faf8f0'
const GRAPH_LINE_COLOR = '#c9d6e8'
const COMPOSITION_RULE_COLOR = '#a9c3dc'
const COMPOSITION_MIDLINE_COLOR = '#c7d8ea'

const GRAPH_SPACING = 24
// Distance between baselines — the dashed guide midline sits halfway
// between one baseline and the next, matching the classic elementary
// composition-paper layout (top space, dashed midline, solid baseline).
const COMPOSITION_LINE_HEIGHT = 42
// Musical staff paper: five lines per staff. The line gap is generous
// (beginner manuscript paper, not engraver-tight) so a child can place
// note heads between lines with a stylus or pencil after printing.
const STAFF_LINE_GAP = 12
// Top of one staff to the top of the next — leaves clear space between
// staves for lyrics, solfège syllables, or ledger lines.
const STAFF_GROUP_SPACING = 96
const STAFF_TOP_MARGIN = 48

type PaperStyle = 'composition' | 'graph' | 'staff'

function paperStyleFor(subject?: Subject): PaperStyle {
  if (subject === 'mathematics') return 'graph'
  if (subject === 'art_music') return 'staff'
  return 'composition'
}

const PAPER_LABEL: Record<PaperStyle, string> = {
  composition: 'Composition Paper',
  graph: 'Graph Paper',
  staff: 'Staff Paper',
}

// Fills the page background and its ruling — called any time the canvas is
// (re)initialized, resized, cleared, or redrawn from the stroke history, so
// the paper style never needs separate "erase to blank" handling from
// "erase to ruled/gridded" handling.
function drawPaper(ctx: CanvasRenderingContext2D, width: number, height: number, style: PaperStyle) {
  ctx.fillStyle = PARCHMENT_BG
  ctx.fillRect(0, 0, width, height)

  if (style === 'graph') {
    ctx.strokeStyle = GRAPH_LINE_COLOR
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

  if (style === 'staff') {
    ctx.strokeStyle = COMPOSITION_RULE_COLOR
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

  for (let y = COMPOSITION_LINE_HEIGHT; y < height; y += COMPOSITION_LINE_HEIGHT) {
    const midY = y - COMPOSITION_LINE_HEIGHT / 2
    ctx.strokeStyle = COMPOSITION_MIDLINE_COLOR
    ctx.lineWidth = 1
    ctx.setLineDash([6, 6])
    ctx.beginPath()
    ctx.moveTo(0, midY + 0.5)
    ctx.lineTo(width, midY + 0.5)
    ctx.stroke()

    ctx.strokeStyle = COMPOSITION_RULE_COLOR
    ctx.setLineDash([])
    ctx.beginPath()
    ctx.moveTo(0, y + 0.5)
    ctx.lineTo(width, y + 0.5)
    ctx.stroke()
  }
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

export default function HandwritingCanvas({ onSubmit, onCancel, subject }: HandwritingCanvasProps) {
  const paperStyle = paperStyleFor(subject)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const isDrawingRef = useRef(false)
  const currentStrokeRef = useRef<Point[]>([])
  const strokesRef = useRef<Stroke[]>([])
  const dprRef = useRef(window.devicePixelRatio || 1)

  // Force re-render when strokes change so undo button updates
  const [strokeCount, setStrokeCount] = useState(0)

  // Paint controls — MS Paint/Preview-style: pick a tool, a size, a color.
  // Kept as plain state (not refs) so the toolbar re-renders immediately;
  // the pointer handlers below are plain functions re-created each render,
  // so they always see the latest selection with no extra plumbing.
  const [tool, setTool] = useState<Tool>('pen')
  const [sizePreset, setSizePreset] = useState<SizePreset>('medium')
  const [color, setColor] = useState<string>(PALETTE[0].value)

  const initCanvas = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const dpr = window.devicePixelRatio || 1
    dprRef.current = dpr
    canvas.width = canvas.offsetWidth * dpr
    canvas.height = canvas.offsetHeight * dpr
    const ctx = canvas.getContext('2d')!
    ctx.scale(dpr, dpr)
    drawPaper(ctx, canvas.offsetWidth, canvas.offsetHeight, paperStyle)
  }, [paperStyle])

  useEffect(() => {
    initCanvas()
  }, [initCanvas])

  // Redraw all strokes from scratch onto the canvas
  const redrawAll = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    const dpr = dprRef.current

    // Clear to paper (background + ruling/grid)
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.scale(dpr, dpr)
    drawPaper(ctx, canvas.width / dpr, canvas.height / dpr, paperStyle)

    // Replay all strokes — an "eraser" stroke is just one whose color is the
    // background color, so replaying strokes in order naturally covers
    // whatever ink was under it with no separate erase code path.
    for (const stroke of strokesRef.current) {
      if (stroke.points.length < 2) {
        // Single dot
        const pt = stroke.points[0]
        if (!pt) continue
        ctx.beginPath()
        ctx.arc(pt.x, pt.y, stroke.width / 2, 0, Math.PI * 2)
        ctx.fillStyle = stroke.color
        ctx.fill()
        continue
      }
      ctx.beginPath()
      ctx.strokeStyle = stroke.color
      ctx.lineWidth = stroke.width
      ctx.lineCap = 'round'
      ctx.lineJoin = 'round'
      ctx.moveTo(stroke.points[0].x, stroke.points[0].y)
      for (let i = 1; i < stroke.points.length; i++) {
        ctx.lineTo(stroke.points[i].x, stroke.points[i].y)
      }
      ctx.stroke()
    }
  }, [paperStyle])

  // Get canvas-relative coordinates from pointer event — works identically
  // for a Surface Pen, Apple Pencil, a finger, or a mouse, since the
  // Pointer Events API (not separate mouse/touch handlers) unifies all of
  // them, pressure included where the hardware reports it.
  const getPos = (e: React.PointerEvent<HTMLCanvasElement>): Point => {
    const canvas = canvasRef.current!
    const rect = canvas.getBoundingClientRect()
    return {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
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
  const activeColor = () => (tool === 'eraser' ? PARCHMENT_BG : color)

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
      })
      setStrokeCount(strokesRef.current.length)
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
    if (strokesRef.current.length === 0) return
    strokesRef.current.pop()
    setStrokeCount(strokesRef.current.length)
    redrawAll()
  }

  const handleClear = () => {
    strokesRef.current = []
    setStrokeCount(0)
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    const dpr = dprRef.current
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.scale(dpr, dpr)
    drawPaper(ctx, canvas.width / dpr, canvas.height / dpr, paperStyle)
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

  // Handle window resize
  useEffect(() => {
    const handleResize = () => {
      const canvas = canvasRef.current
      if (!canvas) return
      // Save existing image
      const tmpCanvas = document.createElement('canvas')
      tmpCanvas.width = canvas.width
      tmpCanvas.height = canvas.height
      tmpCanvas.getContext('2d')!.drawImage(canvas, 0, 0)

      initCanvas()

      // Restore image
      const ctx = canvas.getContext('2d')!
      const dpr = dprRef.current
      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.drawImage(tmpCanvas, 0, 0, canvas.width, canvas.height)
      ctx.scale(dpr, dpr)
    }

    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [initCanvas])

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-parchment-50">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2 bg-white shadow-sm border-b border-parchment-200 flex-shrink-0">
        {/* Cancel */}
        <button
          onClick={onCancel}
          className="flex items-center gap-1.5 text-gray-500 hover:text-gray-700 px-3 py-2 rounded-lg transition-colors"
        >
          <X size={18} />
          <span className="text-sm font-medium">Cancel</span>
        </button>

        {/* Center label */}
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-navy-700">{PAPER_LABEL[paperStyle]}</span>
        </div>

        {/* Right actions */}
        <div className="flex items-center gap-2">
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
            title={`Print this ${PAPER_LABEL[paperStyle].toLowerCase()}`}
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
      </div>

      {/* Canvas container — id'd so the print stylesheet below can isolate
          just the paper itself (background + ruling + strokes), not the
          toolbar, when handlePrint() triggers window.print(). */}
      <div ref={containerRef} id={PRINT_AREA_ID} className="flex-1 relative">
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

      {/* Scoped to this component's own overlay — isolates the paper
          (#handwriting-print-area) as the only thing that prints, hiding
          the toolbar and everything else on the page behind it. */}
      <style>{`
        @media print {
          body * { visibility: hidden !important; }
          #${PRINT_AREA_ID}, #${PRINT_AREA_ID} * { visibility: visible !important; }
          #${PRINT_AREA_ID} {
            position: fixed;
            inset: 0;
            width: 100%;
            height: 100%;
          }
        }
      `}</style>
    </div>
  )
}
