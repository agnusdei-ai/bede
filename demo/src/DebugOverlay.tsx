// TEMPORARY — see debugBus.ts. Renders the last N logged events directly on
// screen (no devtools/remote debugger needed) so a duplicate-send repro can
// just be screenshotted. Remove alongside debugBus.ts once the bug is found.
import { useEffect, useRef, useState } from 'react'
import { onDebug } from './debugBus'

export function DebugOverlay() {
  const [lines, setLines] = useState<string[]>([])
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    return onDebug((line) => {
      setLines((prev) => [...prev.slice(-59), line])
    })
  }, [])

  useEffect(() => {
    boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight })
  }, [lines])

  return (
    <div
      ref={boxRef}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        maxHeight: '38vh',
        overflowY: 'auto',
        background: 'rgba(0,0,0,0.88)',
        color: '#7CFC00',
        fontSize: 10,
        lineHeight: 1.35,
        fontFamily: 'ui-monospace, Menlo, monospace',
        padding: '6px 8px',
        zIndex: 99999,
        whiteSpace: 'pre-wrap',
        pointerEvents: 'none',
      }}
    >
      {lines.length === 0 ? 'voice-debug: waiting for mic activity…' : lines.map((l, i) => <div key={i}>{l}</div>)}
    </div>
  )
}
