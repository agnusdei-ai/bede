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

/** Which learner an EDUCATOR's voice session is for. The server binds the
 *  session to the teacher, campus, learner and grant it resolves from this,
 *  and refuses an educator session without it (homeschool-api's
 *  routers/voice.py). `learner_id` is a campus learner's UUID; `student_name`
 *  is the single-household roster name, which the server refuses once any
 *  campus exists. Parent, child and demo sessions send nothing. */
export type VoiceLearnerScope =
  | { learner_id: string; campus_id?: string }
  | { student_name: string }

/** The scope to send for the current session, or undefined when the role is
 *  not an educator (or no learner is loaded, which the server then refuses). */
export function voiceScopeFor(
  role: string | null | undefined,
  sessionConfig: { student_name?: string } | null | undefined,
): VoiceLearnerScope | undefined {
  if (role !== 'educator' || !sessionConfig?.student_name) return undefined
  return { student_name: sessionConfig.student_name }
}

/** Starts a new server-side streaming-transcription session. Returns its id
 *  — pass it to pushVoiceStreamChunk/finishVoiceStream/streamVoiceEvents. */
export async function startVoiceStream(
  token: string, language = 'en', scope?: VoiceLearnerScope,
): Promise<string> {
  const res = await fetch(`${BASE}/voice/stream/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ language, ...(scope ?? {}) }),
  })
  if (!res.ok) throw new Error('Could not start voice streaming')
  const data = await res.json()
  return data.session_id as string
}

/** Uploads a DELTA — only what was captured since the caller's last upload,
 *  as raw headerless PCM (see useVoiceRecorder.ts's snapshotPcmDelta and
 *  audioUtils.ts's encodePcm16). The server appends deltas into one growing
 *  buffer and wraps it in a WAV header once, at transcription time (see
 *  homeschool-api/services/streaming_transcription.py's push_chunk/
 *  _wav_from_pcm16) — it tells this apart from the legacy whole-buffer
 *  upload by sniffing for a RIFF header, so an older client still works
 *  against a newer server.
 *
 *  The 'chunk.wav' filename below is sent unconditionally regardless of
 *  which protocol the payload actually is; the server does not use it to
 *  decide which path to take, only routers/voice.py's own upload-size and
 *  container/extension allowlist check reads it.
 *
 *  Throws on failure. Unlike the old whole-buffer protocol, a dropped delta
 *  is genuinely lost unless the caller holds and resends it — see
 *  useHybridVoiceInput.ts's pendingPartsRef, which prepends a failed upload
 *  to the next one rather than assuming a later chunk will cover it. */
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
