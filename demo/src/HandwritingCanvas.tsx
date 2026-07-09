import { useRef, useEffect, useCallback, useState } from 'react'
import { X, Undo2, Trash2, Check } from 'lucide-react'

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
}

const INK_COLOR = '#1b3a6b'
const PARCHMENT_BG = '#faf8f0'

export default function HandwritingCanvas({ onSubmit, onCancel }: HandwritingCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const isDrawingRef = useRef(false)
  const currentStrokeRef = useRef<Point[]>([])
  const strokesRef = useRef<Stroke[]>([])
  const dprRef = useRef(window.devicePixelRatio || 1)

  // Force re-render when strokes change so undo button updates
  const [strokeCount, setStrokeCount] = useState(0)

  const initCanvas = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const dpr = window.devicePixelRatio || 1
    dprRef.current = dpr
    canvas.width = canvas.offsetWidth * dpr
    canvas.height = canvas.offsetHeight * dpr
    const ctx = canvas.getContext('2d')!
    ctx.scale(dpr, dpr)
    ctx.fillStyle = PARCHMENT_BG
    ctx.fillRect(0, 0, canvas.offsetWidth, canvas.offsetHeight)
  }, [])

  useEffect(() => {
    initCanvas()
  }, [initCanvas])

  // Redraw all strokes from scratch onto the canvas
  const redrawAll = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    const dpr = dprRef.current

    // Clear to parchment
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.fillStyle = PARCHMENT_BG
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.scale(dpr, dpr)

    // Replay all strokes
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
  }, [])

  // Get canvas-relative coordinates from pointer event
  const getPos = (e: React.PointerEvent<HTMLCanvasElement>): Point => {
    const canvas = canvasRef.current!
    const rect = canvas.getBoundingClientRect()
    return {
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
      pressure: e.pressure,
    }
  }

  const getStrokeWidth = (pressure: number) =>
    Math.max(1.5, Math.min(4, pressure * 6 || 2))

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
    ctx.fillStyle = INK_COLOR
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
    ctx.strokeStyle = INK_COLOR
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
        color: INK_COLOR,
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
    ctx.fillStyle = PARCHMENT_BG
    ctx.fillRect(0, 0, canvas.width, canvas.height)
    ctx.scale(dpr, dpr)
  }

  const handleDone = () => {
    const canvas = canvasRef.current
    if (!canvas) return
    onSubmit(canvas.toDataURL('image/png'))
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
          <span className="text-sm font-semibold text-navy-700">Draw</span>
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
            onClick={handleDone}
            title="Send drawing"
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-navy-500 text-white hover:bg-navy-600 transition-colors font-medium text-sm min-h-[44px]"
          >
            <Check size={16} />
            <span>Done</span>
          </button>
        </div>
      </div>

      {/* Canvas container */}
      <div ref={containerRef} className="flex-1 relative">
        <canvas
          ref={canvasRef}
          className="absolute inset-0 w-full h-full"
          style={{ touchAction: 'none', cursor: 'crosshair' }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={onPointerLeave}
        />
      </div>
    </div>
  )
}
