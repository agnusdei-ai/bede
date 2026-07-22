import { parseSSEStream } from './api'

const BASE = '/api'

export interface VerifyResult {
  verified: boolean
  score: number | null
  level: 'high' | 'medium' | 'low'
  message: string
  student_name?: string
  parent_override?: boolean
}

export async function enrollVoice(
  token: string,
  studentName: string,
  wavBlobs: Blob[]
): Promise<{ success: boolean; samples_used: number; method: string }> {
  const form = new FormData()
  form.append('student_name', studentName)
  wavBlobs.forEach((blob, i) => form.append('samples', blob, `sample_${i}.wav`))

  const res = await fetch(`${BASE}/voice/enroll`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Enrolment failed')
  }
  return res.json()
}

export async function verifyVoice(
  token: string,
  studentName: string,
  wavBlob: Blob
): Promise<VerifyResult> {
  const form = new FormData()
  form.append('student_name', studentName)
  form.append('audio', wavBlob, 'verification.wav')

  const res = await fetch(`${BASE}/voice/verify`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Verification failed')
  }
  return res.json()
}

export async function parentOverrideVoice(
  token: string,
  studentName: string
): Promise<VerifyResult> {
  const form = new FormData()
  form.append('student_name', studentName)

  const res = await fetch(`${BASE}/voice/override`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  })
  if (!res.ok) throw new Error('Override failed')
  return res.json()
}

export async function listVoiceProfiles(token: string): Promise<string[]> {
  const res = await fetch(`${BASE}/voice/profiles`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) return []
  const data = await res.json()
  return data.enrolled_students ?? []
}

// ── Server-side streaming transcription (primary voice-input path) ──────────
//
// Replaces browser-native SpeechRecognition entirely — see
// hooks/useHybridVoiceInput.ts and homeschool-api's
// services/streaming_transcription.py for the full design. The client
// always captures raw mic audio locally (hooks/useVoiceRecorder.ts) and
// periodically uploads the growing buffer here; each upload is
// re-transcribed server-side and the result appears on the SSE event
// stream below.

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

/** Starts a new server-side streaming-transcription session. Returns its id
 *  — pass it to pushVoiceStreamChunk/finishVoiceStream/streamVoiceEvents. */
export async function startVoiceStream(token: string, language = 'en'): Promise<string> {
  const res = await fetch(`${BASE}/voice/stream/start`, {
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
  const res = await fetch(`${BASE}/voice/stream/${sessionId}/chunk`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  })
  if (!res.ok) throw new Error('Voice chunk upload failed')
}

/** Signals no more chunks are coming — the server transcribes the final
 *  buffer once more, emits a 'final' event, then 'done' closes the stream. */
export async function finishVoiceStream(token: string, sessionId: string): Promise<void> {
  const res = await fetch(`${BASE}/voice/stream/${sessionId}/finish`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Voice stream finish failed')
}

/** Consumed via fetch() + parseSSEStream, NOT the browser's native
 *  EventSource API — EventSource can't attach an Authorization header (see
 *  homeschool-api's routers/voice.py's stream_events_endpoint docstring). */
export async function* streamVoiceEvents(token: string, sessionId: string): AsyncGenerator<VoiceStreamEvent> {
  const res = await fetch(`${BASE}/voice/stream/${sessionId}/events`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Could not open the voice event stream')
  yield* parseSSEStream<VoiceStreamEvent>(res)
}
