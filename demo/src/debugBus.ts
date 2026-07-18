// TEMPORARY diagnostic instrumentation for tracking down the iOS Safari
// duplicate-send bug — NOT meant to stay in the codebase. A tiny in-page
// event log so we can see exactly what fires, in what order, on a real
// device we have no direct access to (no remote debugger available).
// Remove this file and every logDebug() call site once the bug is found.

type Listener = (line: string) => void

const listeners: Listener[] = []
const startedAt = performance.now()

export function logDebug(line: string) {
  const ts = (performance.now() - startedAt).toFixed(0)
  const entry = `[${ts}ms] ${line}`
  // eslint-disable-next-line no-console
  console.log('[voice-debug]', entry)
  listeners.forEach((l) => l(entry))
}

export function onDebug(listener: Listener) {
  listeners.push(listener)
  return () => {
    const i = listeners.indexOf(listener)
    if (i >= 0) listeners.splice(i, 1)
  }
}
