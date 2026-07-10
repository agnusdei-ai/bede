// Client for the optional "Try it now" shared-trial path — talks to a real
// homeschool-api backend instead of Anthropic directly, so a shared demo key
// never reaches the browser. This is the ONLY safe way to offer a shared key
// at all: a purely static site cannot hide a secret from its own devtools,
// no matter how it's encoded, since the browser must hold the plaintext key
// to use it. The bring-your-own-key path (claude.ts) stays fully static and
// needs none of this — this file is additive, not a replacement.
//
// Reuses claude.ts's shared shapes (Subject, ChatMessage, VisualAidData,
// StreamChunk) rather than redefining them, since both paths render into the
// same chat UI.

import type { GradeStage, Subject, ChatMessage, VisualAidData, StreamChunk } from './claude'

// Must point at a real, publicly-reachable homeschool-api deployment with
// DEMO_PIN set. Baked in at build time — set via VITE_DEMO_API_BASE. Until
// that deployment exists, the "Try it now" path simply isn't offered (see
// App.tsx's isTrialAvailable check) — bring-your-own-key keeps working
// regardless.
const BASE = import.meta.env.VITE_DEMO_API_BASE as string | undefined

export function trialAvailable(): boolean {
  return !!BASE
}

/** Thrown when the backend rejects a trial request as ended (absolute expiry,
 *  server-enforced 5-minute inactivity timeout, or superseded by a newer
 *  login) — lets the UI route to a clear "session ended" screen instead of
 *  just showing an inline error bubble on a dead chat. */
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
  return BASE
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
 *  homeschool-api/services/email_service.py. Only offered on this
 *  shared-trial path (not bring-your-own-key), since it's the only path
 *  with server-side auth and a per-session send cap to protect the
 *  operator's own Claude/Resend usage. */
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

  if (res.status === 401) throw new TrialSessionEndedError('Your free trial has ended — log in again or use your own key to keep going.')
  if (!res.ok) throw new Error('Tutor request failed — check your connection')

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
