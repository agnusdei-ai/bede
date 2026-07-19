/**
 * Minimal pub/sub logger for the voice-flow debug panel (see
 * DebugOverlay.tsx). A permanent, toggleable version of the temporary
 * on-screen tracer used to root-cause the iOS Safari duplicate-send bug
 * (this file existed once before, removed once that bug was fixed) — kept
 * around this time since "I can't see what the voice UI is actually
 * doing" is a recurring class of report, not a one-off. logDebug() is a
 * no-op with effectively zero cost when the panel is closed (DebugOverlay
 * isn't subscribed, so entries accumulate in the ring buffer and are
 * simply never read).
 */

export interface DebugEntry {
  id: number
  time: number // performance.now(), ms since navigation — matches log timestamps across a session
  message: string
}

const MAX_ENTRIES = 100
let entries: DebugEntry[] = []
let nextId = 0
type Listener = (entries: DebugEntry[]) => void
const listeners = new Set<Listener>()

export function logDebug(message: string): void {
  entries = [...entries.slice(-(MAX_ENTRIES - 1)), { id: nextId++, time: performance.now(), message }]
  listeners.forEach((l) => l(entries))
}

export function getDebugEntries(): DebugEntry[] {
  return entries
}

export function clearDebugEntries(): void {
  entries = []
  listeners.forEach((l) => l(entries))
}

export function subscribeDebug(listener: Listener): () => void {
  listeners.add(listener)
  listener(entries)
  return () => listeners.delete(listener)
}
