// Client for the demo — talks to a real homeschool-api backend instead of
// Anthropic directly, so the operator's key never reaches the browser. This
// is the ONLY safe way to do it: a purely static site cannot hide a secret
// from its own devtools, no matter how it's encoded, since the browser would
// have to hold the plaintext key to use it directly — that's why the old
// "bring your own key" path was removed. The shared-PIN trial tier was later
// removed too (single-active-session collisions under concurrent visitors);
// the self-service one-time code below is the sole entry point now.

import { logDebug } from './debugBus'

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

/** Events from GET /voice/stream/{id}/events — see homeschool-api's
 *  services/streaming_transcription.py. 'partial' arrives roughly once per
 *  chunk upload interval while still holding, 'final' once after finish(),
 *  'done' closes the stream, 'error' means the session id itself wasn't
 *  recognized (expired/unknown). */
export type VoiceStreamEvent =
  | { type: 'partial'; text: string }
  | { type: 'final'; text: string }
  | { type: 'done' }
  | { type: 'error'; message: string }

// Must point at a real, publicly-reachable homeschool-api deployment with
// DEMO_PIN set. Baked in at build time — set via VITE_DEMO_API_BASE. Without
// it, generateDemoCode() below surfaces a clear "not enabled" error the
// moment a visitor clicks the one button the demo offers.
const BASE = import.meta.env.VITE_DEMO_API_BASE as string | undefined

/** Thrown when the backend rejects a request as ended (message quota
 *  reached and code logged out, or the token was otherwise invalidated) —
 *  lets the UI route to a clear "session ended" screen instead of just
 *  showing an inline error bubble on a dead chat. */
export class TrialSessionEndedError extends Error {}

/** Thrown when this IP has used up its diagnostic-preview quota (see
 *  homeschool-api/core/diagnostic_preview_quota.py) — distinct from
 *  TrialSessionEndedError since the demo session itself is still fine,
 *  only the diagnostic preview specifically is capped. */
export class DiagnosticPreviewQuotaExceededError extends Error {}

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
  if (!BASE) throw new Error('The free demo is not configured on this deployment.')
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

/**
 * Mints a fresh one-time 6-digit code with no credentials required (see
 * auth.py's /auth/demo-code). The code is exchanged for a JWT immediately
 * via loginWithCode — the caller never needs to show a separate "enter your
 * code" screen.
 */
/** Grades a visitor can pick at login — mirrors the backend's VALID_GRADES
 *  allowlist (models/schemas.py); anything else is silently ignored server-side. */
export const DEMO_GRADES = ['K', '1', '2', '3', '4', '5', '6', '7', '8'] as const

export async function generateDemoCode(studentName?: string, grade?: string): Promise<string> {
  const hasBody = (studentName && studentName.trim()) || grade
  const res = await fetch(`${apiBase()}/auth/demo-code`, {
    method: 'POST',
    ...(hasBody && {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        student_name: studentName?.trim() || undefined,
        grade: grade || undefined,
      }),
    }),
  })
  if (res.status === 404) throw new Error('The free demo is not enabled on this deployment.')
  if (res.status === 429) throw new Error('Too many demo sessions are active right now. Please try again shortly.')
  if (!res.ok) throw new Error('Could not start a session right now. Please try again.')
  const data = await res.json()
  return data.code
}

/** Exchanges a code from generateDemoCode() for a JWT. One-time only — the
 *  backend rejects a code that's already been redeemed once. locale is the
 *  visitor's own choice from CodeScreen's language toggle (see
 *  docs/LOCALIZATION.md) — the backend embeds it as a JWT claim exactly the
 *  same way it does for the real app's parent/child logins; no backend
 *  change was needed to support the demo_code role here. */
export async function loginWithCode(code: string, locale?: string): Promise<{ token: string; expiresAt: number | null }> {
  const res = await fetch(`${apiBase()}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(locale ? { role: 'demo_code', credential: code, locale } : { role: 'demo_code', credential: code }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Could not start your session')
  }
  const data = await res.json()
  return { token: data.access_token, expiresAt: decodeExpiry(data.access_token) }
}

export interface AvailableLocale {
  code: string
  name: string
}

// Public, pre-auth — CodeScreen calls this on mount to decide whether to
// render the language toggle at all. Empty array on an English-only
// deployment (the default), same "toggle just isn't there" behavior as
// homeschool-tutor's Login.tsx.
export async function fetchAvailableLocales(): Promise<AvailableLocale[]> {
  try {
    const res = await fetch(`${apiBase()}/auth/locales`)
    if (!res.ok) return []
    const data = await res.json()
    return data.locales ?? []
  } catch {
    return []
  }
}

/** Instantly invalidates the demo code server-side (see auth.py's
 *  /auth/logout) rather than just discarding the token client-side, so a
 *  leaked/copied token can't keep being used after the visitor logs out. */
export async function logout(token: string): Promise<void> {
  try {
    await fetch(`${apiBase()}/auth/logout`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
  } catch {
    // best-effort — the token expires on its own eventually regardless
  }
}

/** Bede's spoken voice via the backend's OpenAI TTS (see
 *  homeschool-api/services/voice_synthesis.py) — the same voice production
 *  uses. `configured` reflects the X-TTS-Configured header — whether SOME
 *  backend TTS is set up at all, not just whether this one call succeeded —
 *  so callers can tell "nothing configured, fall back to the browser's own
 *  speech" apart from "configured but this call failed, stay silent rather
 *  than degrading to a different voice mid-conversation" (see
 *  useTextToSpeech.ts's speak()). */
// Once a real response confirms the backend has TTS configured, remember it
// for the rest of the tab session. A network-level exception below (timeout,
// connection reset, a Render free-tier cold start mid-request) tells us
// NOTHING about whether TTS is configured — it's a transient failure of this
// one call, not a fact about the deployment. Treating that exception as
// "unconfigured" was the actual cause of voice audibly flipping from Fable
// to the browser's robotic fallback partway through a conversation: the very
// first hiccupy request lied about the deployment being unconfigured, even
// though every other request that same session succeeded fine.
let lastKnownTtsConfigured = false

export async function speakViaBackend(
  token: string,
  text: string,
): Promise<{ audio: Blob | null; configured: boolean }> {
  try {
    const res = await fetch(`${apiBase()}/tutor/speak`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ text }),
    })
    const configured = res.headers.get('X-TTS-Configured') === 'True'
    lastKnownTtsConfigured = configured
    if (res.status !== 200) return { audio: null, configured }
    return { audio: await res.blob(), configured }
  } catch {
    return { audio: null, configured: lastKnownTtsConfigured }
  }
}

export type FeedbackCategory = 'cx' | 'ux' | 'content_quality' | 'plans' | 'other' | 'beta_close'

/** Wakes the demo backend the moment the page loads. The demo API sleeps
 *  between visitors on Render's free plan, and without this the FIRST real
 *  request (generating a code) silently eats the whole cold start — the
 *  visitor just sees a long spinner. Pinging /health at page load starts
 *  the wake-up in parallel with the part of the visit that needs no
 *  server at all: reading the consent notice and typing a name. Fire and
 *  forget — a failure means nothing here (the backend may simply still be
 *  waking, or the demo unconfigured), and every real call handles its own
 *  errors. */
export function warmDemoBackend(): void {
  try {
    fetch(`${apiBase()}/health`).catch(() => {})
  } catch {
    // VITE_DEMO_API_BASE unset (apiBase throws) — nothing to warm.
  }
}

// ── Server-side streaming transcription (primary voice-input path) ──────────
//
// Replaces browser-native SpeechRecognition entirely — see
// useHybridVoiceInput.ts and homeschool-api's services/streaming_transcription.py
// for the full design. The client always captures raw mic audio locally
// (useVoiceRecorder.ts) and periodically uploads the growing buffer here;
// each upload is re-transcribed server-side and the result appears on the
// SSE event stream below.

/** Starts a new server-side streaming-transcription session. Returns its id
 *  — pass it to pushVoiceStreamChunk/finishVoiceStream/streamVoiceEvents. */
export async function startVoiceStream(token: string, language = 'en'): Promise<string> {
  const res = await fetch(`${apiBase()}/voice/stream/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ language }),
  })
  if (!res.ok) throw new Error('Could not start voice streaming')
  const data = await res.json()
  return data.session_id as string
}

/** Uploads the FULL audio captured so far (not a delta) — the server always
 *  re-transcribes the whole growing buffer, matching how useVoiceRecorder.ts
 *  already accumulates one continuous PCM capture per hold. Throws on
 *  failure; the caller decides whether a single dropped chunk is worth
 *  surfacing (the next chunk a few seconds later carries everything anyway). */
export async function pushVoiceStreamChunk(token: string, sessionId: string, wavBlob: Blob): Promise<void> {
  const form = new FormData()
  form.append('audio', wavBlob, 'chunk.wav')
  const res = await fetch(`${apiBase()}/voice/stream/${sessionId}/chunk`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  })
  if (!res.ok) throw new Error('Voice chunk upload failed')
}

/** Signals no more chunks are coming — the server transcribes the final
 *  buffer once more, emits a 'final' event, then 'done' closes the stream. */
export async function finishVoiceStream(token: string, sessionId: string): Promise<void> {
  const res = await fetch(`${apiBase()}/voice/stream/${sessionId}/finish`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Voice stream finish failed')
}

/** Consumed via fetch() + parseSSEStream, NOT the browser's native
 *  EventSource API — EventSource can't attach an Authorization header (see
 *  homeschool-api's routers/voice.py's stream_events_endpoint docstring). */
export async function* streamVoiceEvents(token: string, sessionId: string): AsyncGenerator<VoiceStreamEvent> {
  const res = await fetch(`${apiBase()}/voice/stream/${sessionId}/events`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Could not open the voice event stream')
  yield* parseSSEStream<VoiceStreamEvent>(res)
}

/** Whether FEEDBACK_EMAIL is configured on this deployment — checked before
 *  showing the feedback button at all, so it never appears only to fail on
 *  submit. Unauthenticated — see homeschool-api's routers/feedback.py. */
export async function isFeedbackEnabled(): Promise<boolean> {
  try {
    const res = await fetch(`${apiBase()}/feedback/enabled`)
    if (!res.ok) return false
    const data = await res.json()
    return Boolean(data.enabled)
  } catch {
    return false
  }
}

/** Sends beta CX/UX/content-quality feedback to the operator's own inbox —
 *  never persisted server-side beyond that one email (see
 *  homeschool-api/routers/feedback.py). */
export async function submitFeedback(
  token: string,
  category: FeedbackCategory,
  message: string,
  rating?: number,
  contactEmail?: string,
): Promise<void> {
  const res = await fetch(`${apiBase()}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      category,
      message,
      rating: rating || undefined,
      contact_email: contactEmail?.trim() || undefined,
    }),
  })
  if (res.status === 401) throw new TrialSessionEndedError('Your session has ended.')
  if (!res.ok) throw new Error('Could not send feedback right now. Please try again later.')
}

export async function getDemoConfig(token: string): Promise<SessionConfig> {
  const res = await fetch(`${apiBase()}/tutor/demo-config`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Could not load your session. Please generate a new code.')
  return res.json()
}

/** Thrown when this session has already used its one allowed email send
 *  (see homeschool-api's core/demo_code_session.claim_email_send). */
export class TrialEmailCappedError extends Error {}

/** Emails Bede's end-of-demo notes to a parent-supplied address once, via
 *  the same backend the chat itself uses. The address is never sent
 *  anywhere else, never persisted by the backend, and the notes are never
 *  shown to the student in this browser — see
 *  homeschool-api/services/email_service.py. Capped at one send per code to
 *  protect the operator's own Claude/Resend usage. */
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
  if (res.status === 401) throw new TrialSessionEndedError('Your session has ended.')
  if (res.status === 429) throw new TrialEmailCappedError('This session has already sent its one email.')
  if (!res.ok) throw new Error('Could not send the email. Please try again later.')
}

function stripDataUrlPrefix(dataUrl: string): string {
  const idx = dataUrl.indexOf(',')
  return idx === -1 ? dataUrl : dataUrl.slice(idx + 1)
}

/**
 * Pulls text out of a narration file the child already has — e.g. exported
 * from a smart pen/notebook app like inq (https://inq.shop), whose own AI
 * already transcribed their handwriting to a .txt/.pdf. There's no public
 * inq API to integrate against, so this is the realistic integration
 * surface: the family exports the file themselves and uploads it here. The
 * returned text is meant to be dropped into the normal chat input for the
 * child to review/edit before sending — see homeschool-api's
 * services/document_extraction.py.
 */
export async function extractNarrationText(token: string, filename: string, contentBase64: string): Promise<string> {
  const res = await fetch(`${apiBase()}/tutor/extract-narration`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ filename, content_base64: contentBase64 }),
  })
  if (res.status === 401) throw new TrialSessionEndedError('Your session has ended.')
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Could not read that file. Try a .txt or .pdf export instead.')
  }
  const data = await res.json()
  return data.text
}

// How long a gap between consecutive SSE chunks this client will tolerate
// before giving up on the stream. The backend has its own matching
// server-side stall guard (core/sse_utils.py) that normally closes a
// stuck stream with a clean, recoverable error chunk well before this —
// this is the client's own backstop for the case that guard can't catch:
// a network path that goes silent without properly closing the
// connection (a black-holed proxy, a dropped wifi/cellular handoff),
// where the server-side fix alone can't help since the server itself may
// still think it's fine. Without this, reader.read() below just waits
// forever with nothing to time it out, and the send button spins
// indefinitely with no way to recover short of reloading the page.
const SSE_STALL_TIMEOUT_MS = 60_000

class StreamStallError extends Error {}

/** Shared line-buffered SSE parser used by the tutor, sandbox, diagnostic,
 *  and voice-streaming chat streams — generic over the event shape since
 *  the voice stream (VoiceStreamEvent) and tutor chat stream (StreamChunk)
 *  differ, but both are a sequence of plain-JSON "data: " lines ending in
 *  a {type: 'done'} sentinel. */
async function* parseSSEStream<T extends { type: string }>(res: Response): AsyncGenerator<T> {
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    let timeoutId: ReturnType<typeof setTimeout>
    const stallTimeout = new Promise<never>((_, reject) => {
      timeoutId = setTimeout(() => reject(new StreamStallError("Bede's connection stalled. Please try again.")), SSE_STALL_TIMEOUT_MS)
    })
    let done: boolean, value: Uint8Array | undefined
    try {
      ;({ done, value } = await Promise.race([reader.read(), stallTimeout]))
    } catch (err) {
      // Release the underlying connection rather than leaving it dangling
      // in the background — reader.read() itself is still pending at this
      // point (that's exactly what stalled), so this is what actually
      // frees it up instead of just abandoning the promise.
      reader.cancel().catch(() => {})
      throw err
    } finally {
      clearTimeout(timeoutId!)
    }
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const jsonStr = line.slice(6).trim()
      if (!jsonStr) continue
      try {
        const chunk: T = JSON.parse(jsonStr)
        yield chunk
        if (chunk.type === 'done') return
      } catch {
        // skip malformed chunk
      }
    }
  }
}

// The visitor's own device calendar date (YYYY-MM-DD), computed fresh at
// each request — mirrors homeschool-tutor/src/store/sessionStore.ts's
// deriveLocalDate. Sent as local_date so the backend's weekly poetry/prayer
// rotation (services/poetry_catalog.py, services/prayer_catalog.py) picks
// the week the VISITOR's calendar is on, not the server's — otherwise a
// server running in a different timezone (typically UTC) could show a
// different week's poem near a Sunday/Monday boundary in the visitor's own
// timezone. getFullYear/getMonth/getDate (not toISOString, which converts
// to UTC first) — the same local-vs-UTC distinction that bug is about.
export function deriveLocalDate(): string {
  const now = new Date()
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

export type TimeOfDay = 'morning' | 'afternoon' | 'evening'

// Mirrors homeschool-tutor/src/store/sessionStore.ts's deriveTimeOfDay —
// see that file's comment for the exact hour boundaries and why Bede's
// greeting/prayer framing needs this. Unlike deriveLocalDate above, this
// is meant to be called ONCE per session (DemoFlow derives it from
// sessionStartRef, the same stable timestamp already used for the
// session's hard-stop/break rules) rather than fresh per request — a
// session that happens to run past an hour boundary should keep
// greeting/framing itself the way it opened, not flip mid-session.
export function deriveTimeOfDay(date: Date): TimeOfDay {
  const hour = date.getHours()
  if (hour < 12) return 'morning'
  if (hour < 17) return 'afternoon'
  return 'evening'
}

export async function* streamTutorChat(
  token: string,
  config: SessionConfig,
  subject: Subject,
  history: ChatMessage[],
  childMessage: string,
  drawingImageDataUrl: string | null,
  signal?: AbortSignal,
  timeOfDay?: TimeOfDay | null,
): AsyncGenerator<StreamChunk> {
  const localDate = deriveLocalDate()
  // The debug panel is the only way a report like "greeting doesn't match
  // the time of day" or "wrong week's poem" can actually be diagnosed
  // remotely — neither value was ever traced anywhere before, so a family
  // hitting either had no way to show what the client thought "now" was.
  logDebug(`streamTutorChat local_date=${localDate} local_time_of_day=${timeOfDay ?? 'null'}`)
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
      local_date: localDate,
      local_time_of_day: timeOfDay ?? null,
    }),
    signal,
  })

  if (res.status === 401) throw new TrialSessionEndedError('Your session has ended. Generate a new code to keep going.')
  if (!res.ok) throw new Error('Tutor request failed. Check your connection.')

  yield* parseSSEStream<StreamChunk>(res)
}

/**
 * Preview of the parent-only "Ask Bede" sandbox (direct answers, not
 * Socratic, free topic-switching) — reachable from the demo-code session,
 * since it needs the same server-side session that gates the regular demo
 * chat. Nothing said here is saved server-side either — see
 * homeschool-api/routers/sandbox.py's /demo-chat.
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

  if (res.status === 401) throw new TrialSessionEndedError('Your session has ended. Generate a new code to keep going.')
  if (!res.ok) throw new Error('Sandbox request failed. Check your connection.')

  yield* parseSSEStream<StreamChunk>(res)
}

// ── Diagnostic preview (demo-scoped, no separate login) ───────────────────────
//
// Reachable with the exact same demo_code token the current session
// already has — no separate login, same precedent as the "Ask Bede"
// sandbox preview. See routers/diagnostic.py. Single-session only: nothing
// here survives past that demo code's own lifetime, same as everything
// else about it.

export type MasteryLevel = 'gap' | 'developing' | 'secure'

export interface SkillMasteryView {
  skill_id: string
  label: string
  domain: string
  grade_band: string
  probability: number
  level: MasteryLevel
}

export interface DomainMasteryView {
  domain: string
  average_probability: number
  level: MasteryLevel
  skills: SkillMasteryView[]
}

export interface MasteryProfileSummary {
  student_name: string
  subject_area: string
  evidence_count: number
  calibration: boolean
  domains: DomainMasteryView[]
  gaps: SkillMasteryView[]
  next_steps: SkillMasteryView[]
  updated_at: string
}

// Reads the backend's own detail message (routers/diagnostic.py's
// _require_diagnostic_quota — mentions the real contact info) rather than
// duplicating a hardcoded copy here that would silently drift out of sync
// the next time that message is updated server-side.
async function diagnosticQuotaError(res: Response): Promise<DiagnosticPreviewQuotaExceededError> {
  const body = await res.json().catch(() => ({}))
  return new DiagnosticPreviewQuotaExceededError(
    body.detail || "You've reached the diagnostic preview limit for this demo."
  )
}

export async function fetchDiagnosticSummary(token: string): Promise<MasteryProfileSummary | null> {
  const res = await fetch(`${apiBase()}/diagnostic/summary`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (res.status === 404) return null
  if (res.status === 401) throw new TrialSessionEndedError('This diagnostic session has ended.')
  if (res.status === 429) throw await diagnosticQuotaError(res)
  if (!res.ok) throw new Error('Could not load the mastery summary right now.')
  return res.json()
}

export async function* streamDiagnosticChat(
  token: string,
  history: ChatMessage[],
  message: string,
  signal?: AbortSignal
): AsyncGenerator<StreamChunk> {
  const res = await fetch(`${apiBase()}/diagnostic/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ conversation_history: history, message }),
    signal,
  })

  if (res.status === 401) throw new TrialSessionEndedError('This diagnostic session has ended.')
  if (res.status === 429) throw await diagnosticQuotaError(res)
  if (!res.ok) throw new Error('Diagnostic chat request failed. Check your connection.')

  yield* parseSSEStream<StreamChunk>(res)
}
