// Thin client for the public demo — calls the real homeschool-api backend
// instead of Anthropic directly. All persona, curriculum, and tool logic now
// lives server-side (services/ai_service.py), so this file no longer
// duplicates any of that; it's just fetch + SSE parsing, mirroring
// homeschool-tutor/src/services/api.ts.
//
// The demo logs in as the scoped "demo" role: one fixed shared PIN, a
// 15-minute token, and a fixed server-defined SessionConfig the demo can
// never edit — see routers/tutor.py's _demo_session_config() and
// core/deps.py's require_real_user for what that role can and can't reach.

// Must point at a real, publicly-reachable homeschool-api deployment with
// DEMO_PIN set — this demo cannot work purely as a static site the way the
// old bring-your-own-key build did, since the backend now holds the real
// Anthropic key server-side. Set at build time via VITE_DEMO_API_BASE.
const BASE = import.meta.env.VITE_DEMO_API_BASE as string | undefined

export type GradeStage = 'K-2' | '3-5' | '6-8'

export const SUBJECTS = [
  'morning_time', 'living_books', 'mathematics', 'nature_study', 'history',
  'language_arts', 'science', 'art_music', 'saints', 'free_study',
] as const
export type Subject = typeof SUBJECTS[number]

export const SUBJECT_LABELS: Record<Subject, string> = {
  morning_time: 'Morning Time', living_books: 'Living Books', mathematics: 'Mathematics',
  nature_study: 'Nature Study', history: 'History & Geography', language_arts: 'Language Arts',
  science: 'Science', art_music: 'Art & Music', saints: 'Saints & Catechism', free_study: 'Free Study',
}

export interface SessionConfig {
  student_name: string
  grade: string
  grade_stage: GradeStage
  subjects: Subject[]
  lesson_focus?: string | null
  faith_emphasis?: string | null
  current_unit?: string | null
  voice_required?: boolean
  screen_time_limit_minutes?: number | null
  eye_rest_break_minutes?: number
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface VisualAidData {
  id: string
  title: string
  creator: string
  year: string
  wiki_title: string
  description: string
  category: string
}

export type StreamChunk =
  | { type: 'text'; content: string }
  | { type: 'tool'; tool: string; content: string }
  | { type: 'visual_aid'; visualAid: VisualAidData }
  | { type: 'assessment' }
  | { type: 'done' }

function apiBase(): string {
  if (!BASE) {
    throw new Error(
      'This demo is not configured — VITE_DEMO_API_BASE was not set at build time, ' +
      'so there is no backend to talk to.'
    )
  }
  return BASE
}

// ── Auth ─────────────────────────────────────────────────────────────────────

/** Decodes a JWT's payload without verifying the signature — fine for reading
 *  our own freshly-issued `exp` claim to drive the countdown UI; the server
 *  is the one actually enforcing expiry on every request regardless. */
export function decodeExpiry(token: string): number | null {
  try {
    const [, payloadB64] = token.split('.')
    const json = atob(payloadB64.replace(/-/g, '+').replace(/_/g, '/'))
    const payload = JSON.parse(json)
    return typeof payload.exp === 'number' ? payload.exp * 1000 : null
  } catch {
    return null
  }
}

export async function login(pin: string): Promise<{ token: string; expiresAt: number | null }> {
  const res = await fetch(`${apiBase()}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role: 'demo', credential: pin }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Incorrect PIN')
  }
  const data = await res.json()
  return { token: data.access_token, expiresAt: decodeExpiry(data.access_token) }
}

export async function getDemoConfig(token: string): Promise<SessionConfig> {
  const res = await fetch(`${apiBase()}/tutor/demo-config`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Could not load the demo session — please try logging in again')
  return res.json()
}

// ── Streaming tutor chat ─────────────────────────────────────────────────────

function stripDataUrlPrefix(dataUrl: string): string {
  const idx = dataUrl.indexOf(',')
  return idx === -1 ? dataUrl : dataUrl.slice(idx + 1)
}

export async function* streamTutorChat(
  token: string,
  config: SessionConfig,
  subject: Subject,
  history: ChatMessage[],
  childMessage: string,
  drawingImageDataUrl: string | null,
  signal?: AbortSignal
): AsyncGenerator<StreamChunk> {
  const res = await fetch(`${apiBase()}/tutor/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      session_config: config,
      current_subject: subject,
      conversation_history: history,
      child_message: childMessage,
      drawing_image: drawingImageDataUrl ? stripDataUrlPrefix(drawingImageDataUrl) : null,
    }),
    signal,
  })

  if (res.status === 401) {
    throw new Error('Your demo session has ended — please log in again.')
  }
  if (!res.ok) {
    throw new Error('Tutor request failed — check your connection')
  }

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const jsonStr = line.slice(6).trim()
      if (!jsonStr) continue
      try {
        const chunk: StreamChunk = JSON.parse(jsonStr)
        yield chunk
        if (chunk.type === 'done') return
      } catch {
        // skip malformed chunk
      }
    }
  }
}
