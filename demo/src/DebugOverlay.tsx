import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { clearDebugEntries, subscribeDebug, type DebugEntry } from './debugBus'

/**
 * Fixed-position, screenshot-able log of voice-flow internals (mic
 * press/release, mode transitions, barge-in, review confirm/cancel) —
 * toggled from the chat input bar's bug icon. Exists because "the
 * recorder isn't doing what I expect" reports have no other way to see
 * WHAT it actually did on a device we can't attach a remote debugger to.
 * See debugBus.ts's logDebug() call sites for what gets recorded.
 */
export default function DebugOverlay({ onClose }: { onClose: () => void }) {
  const [entries, setEntries] = useState<DebugEntry[]>([])

  useEffect(() => subscribeDebug(setEntries), [])

  return (
    <div className="fixed inset-x-0 top-0 z-[100] max-h-[40vh] overflow-y-auto bg-black/95 text-green-400 font-mono text-[11px] leading-tight p-2 pt-8">
      <div className="fixed top-1 right-1 flex gap-1 z-[101]">
        <button
          onClick={clearDebugEntries}
          className="px-2 py-1 rounded bg-white/10 text-white hover:bg-white/20 text-[10px]"
        >
          Clear
        </button>
        <button onClick={onClose} className="p-1 rounded bg-white/10 text-white hover:bg-white/20">
          <X size={12} />
        </button>
      </div>
      {entries.length === 0 ? (
        <div className="text-white/40">No debug events yet — press the mic or send a message.</div>
      ) : (
        entries.map((e) => (
          <div key={e.id}>
            [{Math.round(e.time)}ms] {e.message}
          </div>
        ))
      )}
    </div>
  )
}
