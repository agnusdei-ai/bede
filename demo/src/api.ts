// Client for the demo — talks to a real homeschool-api backend instead of
// Anthropic directly, so the operator's key never reaches the browser. This
// is the ONLY safe way to offer either tier: a purely static site cannot
// hide a secret from its own devtools, no matter how it's encoded, since the
// browser would have to hold the plaintext key to use it directly. That's
// why the old "bring your own key" path was removed — both tiers now run
// through this same backend-mediated flow instead.

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
  | { type: 'subject_complete'; reason: 'mastery' | 'frustration'; content: string }
  | { type: 'done' }

// Must point at a real, publicly-reachable homeschool-api deployment with
// DEMO_PIN set. Baked in at build time — set via VITE_DEMO_API_BASE. Both
// demo tiers (shared-PIN trial and self-service code) need this; without it
// the demo has nothing to offer at all (see ChoiceScreen's fallback).
const BASE = import.meta.env.VITE_DEMO_API_BASE as string | undefined

export function trialAvailable(): boolean {
  return !!BASE
}

/** Thrown when the backend rejects a request as ended (absolute expiry,
 *  server-enforced inactivity timeout, message quota reached and code
 *  logged out, or — for the shared trial — superseded by a newer login) —
 *  lets the UI route to a clear "session ended" screen instead of just
 *  showing an inline error bubble on a dead chat. */
export class TrialSessionEndedError extends Error {}

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

function apiBase(): string {
  if (!BASE) throw new Error('The free trial is not configured on this deployment.')
  // Every call site does `${apiBase()}/some/path` — a trailing slash on the
  // configured VITE_DEMO_API_BASE would otherwise produce a double slash
  // (".../onrender.com//auth/login"), which most backends (including this
  // one's FastAPI routes) won't match. Stripping it here means the exact
  // value entered for the GitHub Actions variable can never break every
  // request over one stray character.
  return BASE.replace(/\/+$/, '')
}

/** Decodes a JWT's payload without verifying the signature — fine for reading
 *  our own freshly-issued `exp` claim to drive the countdown UI; the server
 *  is what actually enforces expiry on every request regardless. */
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

/**
 * Self-service alternative to the shared-PIN trial: mints a fresh one-time
 * 6-digit code with no credentials required (see auth.py's /auth/demo-code).
 * The code is exchanged for a JWT immediately via loginWithCode — the caller
 * never needs to show a separate "enter your code" screen.
 */
export async function generateDemoCode(): Promise<string> {
  const res = await fetch(`${apiBase()}/auth/demo-code`, { method: 'POST' })
  if (res.status === 404) throw new Error('The free demo is not enabled on this deployment.')
  if (res.status === 429) throw new Error('Too many demo sessions are active right now — please try again shortly.')
  if (!res.ok) throw new Error('Could not start a session right now — please try again.')
  const data = await res.json()
  return data.code
}

/** Exchanges a code from generateDemoCode() for a JWT. One-time only — the
 *  backend rejects a code that's already been redeemed once. */
export async function loginWithCode(code: string): Promise<{ token: string; expiresAt: number | null }> {
  const res = await fetch(`${apiBase()}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role: 'demo_code', credential: code }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Could not start your session')
  }
  const data = await res.json()
  return { token: data.access_token, expiresAt: decodeExpiry(data.access_token) }
}

/** Instantly invalidates the trial session server-side (see auth.py's
 *  /auth/logout) rather than just discarding the token client-side, so a
 *  leaked/copied token can't keep being used after the visitor logs out. */
export async function logout(token: string): Promise<void> {
  try {
    await fetch(`${apiBase()}/auth/logout`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
  } catch {
    // best-effort — the token expires on its own within 15 minutes regardless
  }
}

/** Bede's spoken voice via the backend's self-hosted Kokoro model (see
 *  homeschool-api/services/voice_synthesis.py) — the same voice production
 *  uses. Returns null if unconfigured server-side (no model files placed
 *  yet) or the request fails; callers should fall back to the browser's own
 *  speech in that case, same contract as the production app's hook. */
export async function speakViaBackend(token: string, text: string): Promise<Blob | null> {
  try {
    const res = await fetch(`${apiBase()}/tutor/speak`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ text }),
    })
    if (res.status !== 200) return null // 204 = not configured server-side
    return await res.blob()
  } catch {
    return null
  }
}

export async function getDemoConfig(token: string): Promise<SessionConfig> {
  const res = await fetch(`${apiBase()}/tutor/demo-config`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Could not load the trial session — please try logging in again')
  return res.json()
}

/** Thrown when this trial session has already used its one allowed email
 *  send (see homeschool-api's core/demo_session.claim_email_send). */
export class TrialEmailCappedError extends Error {}

/** Emails Bede's end-of-demo notes to a parent-supplied address once, via
 *  the same backend the chat itself uses. The address is never sent
 *  anywhere else, never persisted by the backend, and the notes are never
 *  shown to the student in this browser — see
 *  homeschool-api/services/email_service.py. Offered on both backend-mediated
 *  demo tiers (shared-PIN trial and self-service code), each with its own
 *  per-session send cap to protect the operator's own Claude/Resend usage. */
export async function emailTrialSummary(
  token: string,
  email: string,
  config: SessionConfig,
  history: ChatMessage[],
  subjectsCompleted: Subject[],
  durationMinutes: number
): Promise<void> {
  const res = await fetch(`${apiBase()}/tutor/email-summary`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      email,
      session_config: config,
      conversation_history: history,
      subjects_completed: subjectsCompleted,
      duration_minutes: durationMinutes,
    }),
  })
  if (res.status === 401) throw new TrialSessionEndedError('Your free trial has ended.')
  if (res.status === 429) throw new TrialEmailCappedError('This trial has already sent its one email.')
  if (!res.ok) throw new Error('Could not send the email — please try again later.')
}

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
  signal?: AbortSignal,
  // Called once per request with the remaining-messages count from the
  // X-Demo-Remaining response header — set for both demo tiers, since both
  // now end at "time or messages, whichever comes first" (see
  // core/demo_session.py / core/demo_code_session.py).
  onQuotaHeader?: (remaining: number | null) => void
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

  if (res.status === 401) throw new TrialSessionEndedError('Your session has ended — get a new code or trial login to keep going.')
  if (!res.ok) throw new Error('Tutor request failed — check your connection')

  if (onQuotaHeader) {
    const h = res.headers.get('X-Demo-Remaining')
    onQuotaHeader(h !== null ? parseInt(h, 10) : null)
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

/**
 * Preview of the parent-only "Ask Bede" sandbox (direct answers, not
 * Socratic, free topic-switching) — reachable on this shared trial only,
 * since it needs the same server-side session that gates the regular demo
 * chat (single active login, 5-minute inactivity timeout). Nothing said
 * here is saved server-side either — see homeschool-api/routers/sandbox.py's
 * /demo-chat.
 */
export async function* streamSandboxDemoChat(
  token: string,
  history: ChatMessage[],
  message: string,
  customInstructions: string,
  signal?: AbortSignal
): AsyncGenerator<StreamChunk> {
  const res = await fetch(`${apiBase()}/sandbox/demo-chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      conversation_history: history,
      message,
      custom_instructions: customInstructions,
    }),
    signal,
  })

  if (res.status === 401) throw new TrialSessionEndedError('Your free trial has ended — log in again or use your own key to keep going.')
  if (!res.ok) throw new Error('Sandbox request failed — check your connection')

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
