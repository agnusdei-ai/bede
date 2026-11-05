/**
 * Progress while the Practice Coach reads a long upload.
 *
 * The browser names each request with a random id and asks the server about
 * once a second how far that request has got (services/practice/progress.py:
 * how many pages there are and how many are read). A long upload goes in
 * several parts (uploadParts.ts), so the bar shows the whole upload: parts
 * already sent count in full, the part being read counts by its pages.
 *
 * A poll that fails or answers "unknown" (a network blip, or another API
 * process) changes nothing on screen: the bar never goes backwards.
 *
 * Mirrored in demo/src/readingProgress.ts; demo/src/readingProgress.test.ts
 * keeps the two the same.
 */
export type ProgressStage = 'sending' | 'checking' | 'reading' | 'drafting'

export interface ProgressSnapshot {
  stage: ProgressStage
  done: number
  total: number | null
}

export interface ProgressState extends ProgressSnapshot {
  part: number
  parts: number
  percent: number
}

export const POLL_MS = 1200

export function newProgressId(): string {
  const c = globalThis.crypto as Crypto | undefined
  if (c?.randomUUID) return c.randomUUID()
  return `p-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

/** The whole upload's percentage, from where the current part has got. */
export function overallPercent(part: number, parts: number, snap: ProgressSnapshot | null): number {
  const total = Math.max(1, parts)
  const index = Math.min(Math.max(1, part), total) - 1
  let within = 0
  if (snap?.stage === 'drafting') within = 0.95
  else if (snap?.total) within = Math.min(1, snap.done / snap.total) * (parts === 1 && snap.stage === 'reading' ? 0.95 : 1)
  return Math.max(0, Math.min(100, Math.round(((index + within) / total) * 100)))
}

/** Poll for one request's progress until the returned stop() is called. */
export function watchProgress(
  fetcher: (id: string) => Promise<ProgressSnapshot | null>,
  id: string,
  onUpdate: (snap: ProgressSnapshot) => void,
  intervalMs = POLL_MS,
): () => void {
  let stopped = false
  let timer: ReturnType<typeof setTimeout> | undefined
  const tick = async () => {
    if (stopped) return
    try {
      const snap = await fetcher(id)
      if (snap && !stopped) onUpdate(snap)
    } catch {
      // Unknown or unreachable: keep what is on screen.
    }
    if (!stopped) timer = setTimeout(() => { void tick() }, intervalMs)
  }
  timer = setTimeout(() => { void tick() }, intervalMs)
  return () => {
    stopped = true
    if (timer) clearTimeout(timer)
  }
}

/**
 * Run one request per part with a live progress state. `send(part, index, id)`
 * performs the request; `fetcher` asks for its progress. The state only moves
 * forwards.
 */
export async function withProgress<P, R>(
  parts: P[],
  send: (part: P, index: number, progressId: string) => Promise<R>,
  fetcher: (id: string) => Promise<ProgressSnapshot | null>,
  onState: (state: ProgressState) => void,
): Promise<R[]> {
  const results: R[] = []
  let best = 0
  const show = (part: number, snap: ProgressSnapshot) => {
    const percent = Math.max(best, overallPercent(part, parts.length, snap))
    best = percent
    onState({ ...snap, part, parts: parts.length, percent })
  }
  for (let i = 0; i < parts.length; i++) {
    const id = newProgressId()
    show(i + 1, { stage: 'sending', done: 0, total: null })
    const stop = watchProgress(fetcher, id, (snap) => show(i + 1, snap))
    try {
      results.push(await send(parts[i], i, id))
    } finally {
      stop()
    }
    show(i + 1, { stage: 'reading', done: 1, total: 1 })
  }
  return results
}
