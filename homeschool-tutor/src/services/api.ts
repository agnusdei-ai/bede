import type { SessionConfig, Subject, ChatMessage, StreamChunk, NarrationAssessmentData, LearnerProfileData } from '../types'

const BASE = '/api'

// ── Auth ────────────────────────────────────────────────────────────────────

export type MfaMethod = 'webauthn' | 'totp'

export interface LoginResult {
  accessToken: string
  role: string
  // True when accessToken is only a "parent_pending" stepping-stone — the
  // password was correct, but an enrolled security key/TOTP code is still
  // required before a real "parent" token is issued (see /mfa/*/authenticate).
  mfaRequired: boolean
  mfaMethods: MfaMethod[]
}

function toLoginResult(data: any): LoginResult {
  return {
    accessToken: data.access_token,
    role: data.role,
    mfaRequired: !!data.mfa_required,
    mfaMethods: data.mfa_methods ?? [],
  }
}

export async function login(role: 'parent' | 'child', credential: string): Promise<LoginResult> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role, credential }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Login failed')
  }
  return toLoginResult(await res.json())
}

export async function logout(token: string): Promise<void> {
  try {
    await fetch(`${BASE}/auth/logout`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
  } catch {
    // best-effort — parent/child tokens are stateless JWTs anyway
  }
}

// ── Parent MFA: FIDO2 security keys + TOTP ───────────────────────────────────

export interface MfaStatus {
  webauthn_available: boolean
  security_keys: Array<{ id: number; nickname: string; created_at: string }>
  totp_enabled: boolean
}

export async function fetchMfaStatus(token: string): Promise<MfaStatus> {
  const res = await fetch(`${BASE}/mfa/status`, { headers: { Authorization: `Bearer ${token}` } })
  if (!res.ok) throw new Error('Failed to load security settings')
  return res.json()
}

async function postJson(path: string, token: string, body?: unknown): Promise<any> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Request failed')
  }
  return res.json()
}

// Enrollment (requires a full parent session):
export const webauthnRegisterOptions = (token: string) => postJson('/mfa/webauthn/register/options', token)
export const webauthnRegisterVerify = (token: string, credential: object, nickname: string) =>
  postJson('/mfa/webauthn/register/verify', token, { credential, nickname })

export async function deleteSecurityKey(token: string, keyId: number): Promise<void> {
  const res = await fetch(`${BASE}/mfa/webauthn/${keyId}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } })
  if (!res.ok) throw new Error('Failed to remove security key')
}

export const enrollTotp = (token: string): Promise<{ secret: string; otpauth_uri: string }> =>
  postJson('/mfa/totp/enroll', token)
export const confirmTotp = (token: string, code: string) => postJson('/mfa/totp/confirm', token, { code })

export async function disableTotp(token: string): Promise<void> {
  const res = await fetch(`${BASE}/mfa/totp`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } })
  if (!res.ok) throw new Error('Failed to disable authenticator app')
}

// Completing a pending login (requires the "parent_pending" token):
export const webauthnAuthOptions = (pendingToken: string) => postJson('/mfa/webauthn/authenticate/options', pendingToken)
export const webauthnAuthVerify = async (pendingToken: string, credential: object): Promise<LoginResult> =>
  toLoginResult(await postJson('/mfa/webauthn/authenticate/verify', pendingToken, { credential }))
export const totpAuthVerify = async (pendingToken: string, code: string): Promise<LoginResult> =>
  toLoginResult(await postJson('/mfa/totp/authenticate/verify', pendingToken, { code }))

// ── Streaming tutor chat ─────────────────────────────────────────────────────

/** Strips the "data:image/png;base64," prefix a canvas data URL carries. */
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
  signal?: AbortSignal,
  drawingImageDataUrl?: string | null
): AsyncGenerator<StreamChunk> {
  const res = await fetch(`${BASE}/tutor/chat`, {
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
      if (line.startsWith('data: ')) {
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
}

// ── Sandbox (parent-only, direct-answer, nothing persisted) ──────────────────

export async function* streamSandboxChat(
  token: string,
  sandboxPin: string,
  history: ChatMessage[],
  message: string,
  customInstructions: string,
  signal?: AbortSignal
): AsyncGenerator<StreamChunk> {
  const res = await fetch(`${BASE}/sandbox/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      sandbox_pin: sandboxPin,
      conversation_history: history,
      message,
      custom_instructions: customInstructions,
    }),
    signal,
  })

  if (res.status === 401) throw new Error('Incorrect sandbox PIN')
  if (res.status === 404) throw new Error('Sandbox mode is not enabled on this deployment')
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
      if (line.startsWith('data: ')) {
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
}

// ── Admin ────────────────────────────────────────────────────────────────────

export interface SystemStatus {
  voice_profiles_enrolled: number
  student_names: string[]
  encryption: string
  key_storage: string
  audit_log: string
}

export async function fetchSystemStatus(token: string): Promise<SystemStatus> {
  const res = await fetch(`${BASE}/admin/status`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Status unavailable')
  return res.json()
}

// ── Pod session configs ──────────────────────────────────────────────────────

export async function savePodConfigs(token: string, configs: SessionConfig[]): Promise<void> {
  const res = await fetch(`${BASE}/pod/configs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ configs }),
  })
  if (!res.ok) throw new Error('Failed to save pod configuration')
}

export async function listPodConfigs(token: string): Promise<SessionConfig[]> {
  const res = await fetch(`${BASE}/pod/configs`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Failed to load pod configuration')
  return res.json()
}

export async function fetchStudentConfig(token: string, studentName: string): Promise<SessionConfig> {
  const res = await fetch(`${BASE}/pod/configs/${encodeURIComponent(studentName)}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`No configuration found for ${studentName} — ask a parent to set up today's pod.`)
  return res.json()
}

// ── Session summary ──────────────────────────────────────────────────────────

export async function fetchSessionSummary(
  token: string,
  config: SessionConfig,
  history: ChatMessage[],
  subjectsCompleted: Subject[],
  durationMinutes: number
): Promise<string> {
  const res = await fetch(`${BASE}/tutor/summary`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      session_config: config,
      conversation_history: history,
      subjects_completed: subjectsCompleted,
      duration_minutes: durationMinutes,
    }),
  })
  if (!res.ok) throw new Error('Failed to generate summary')
  const data = await res.json()
  return data.summary
}

// Emails the same summary to a parent-supplied address once via Resend.
// The address is never sent anywhere else and the backend never persists
// it — see homeschool-api/services/email_service.py.
export async function emailSessionSummary(
  token: string,
  email: string,
  config: SessionConfig,
  history: ChatMessage[],
  subjectsCompleted: Subject[],
  durationMinutes: number
): Promise<void> {
  const res = await fetch(`${BASE}/tutor/email-summary`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      email,
      session_config: config,
      conversation_history: history,
      subjects_completed: subjectsCompleted,
      duration_minutes: durationMinutes,
    }),
  })
  if (!res.ok) {
    if (res.status === 429) throw new Error('This trial has already sent its one email.')
    throw new Error('Could not send the email — please try again later.')
  }
}

// ── Narration assessments & learner profile ──────────────────────────────────

export async function fetchNarrationAssessments(
  token: string,
  studentName: string
): Promise<NarrationAssessmentData[]> {
  const res = await fetch(`${BASE}/narration/${encodeURIComponent(studentName)}/assessments`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`Failed to load assessments for ${studentName}`)
  return res.json()
}

export async function fetchLearnerProfile(
  token: string,
  studentName: string
): Promise<LearnerProfileData | null> {
  const res = await fetch(`${BASE}/narration/${encodeURIComponent(studentName)}/profile`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Failed to load learner profile for ${studentName}`)
  return res.json()
}

export async function buildLearnerProfile(
  token: string,
  studentName: string,
  sessionCount: number
): Promise<LearnerProfileData> {
  const res = await fetch(
    `${BASE}/narration/${encodeURIComponent(studentName)}/profile?session_count=${sessionCount}`,
    {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    }
  )
  if (!res.ok) throw new Error(`Failed to build learner profile for ${studentName}`)
  return res.json()
}
