import type { SessionConfig, Subject, ChatMessage, StreamChunk, NarrationAssessmentData, LearnerProfileData, LearnerBehaviorCheck, MasteryProfileSummary, UsageSummary, LicenseStatus } from '../types'
import type { TimeOfDay } from '../store/sessionStore'
import { logDebug } from '../hooks/debugBus'

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

export interface AvailableLocale {
  code: string
  name: string
}

// Public, pre-auth — Login.tsx calls this before a token exists to decide
// whether to render the language toggle at all. Empty array on an
// English-only deployment (the default), same "toggle just isn't there"
// behavior as before this feature existed.
export async function fetchAvailableLocales(): Promise<AvailableLocale[]> {
  try {
    const res = await fetch(`${BASE}/auth/locales`)
    if (!res.ok) return []
    const data = await res.json()
    return data.locales ?? []
  } catch {
    return []
  }
}

export async function login(role: 'parent' | 'child', credential: string, locale?: string): Promise<LoginResult> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(locale ? { role, credential, locale } : { role, credential }),
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

export type RecoverySecretKind = 'pin' | 'code' | null

export interface MfaStatus {
  webauthn_available: boolean
  security_keys: Array<{ id: number; nickname: string; created_at: string }>
  totp_enabled: boolean
  // Which shape of the "something you know" recovery factor is enrolled,
  // if either — mutually exclusive (see services/parent_recovery.py).
  recovery_secret: RecoverySecretKind
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

// Change password (requires a full parent session — the non-emergency
// counterpart to the recovery flow below):
export async function changePassword(token: string, currentPassword: string, newPassword: string): Promise<void> {
  await postJson('/mfa/change-password', token, { current_password: currentPassword, new_password: newPassword })
}

// Recovery PIN/code enrollment (the "something you know" leg of account
// recovery below) — mutually exclusive; enrolling one clears the other.

export async function enrollRecoveryPin(token: string, pin: string): Promise<void> {
  await postJson('/mfa/recovery-pin/enroll', token, { pin })
}

export async function disableRecoveryPin(token: string): Promise<void> {
  const res = await fetch(`${BASE}/mfa/recovery-pin`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } })
  if (!res.ok) throw new Error('Failed to remove the recovery PIN')
}

export const enrollRecoveryCode = (token: string): Promise<{ recovery_code: string }> =>
  postJson('/mfa/recovery-code/enroll', token)

export async function disableRecoveryCode(token: string): Promise<void> {
  const res = await fetch(`${BASE}/mfa/recovery-code`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } })
  if (!res.ok) throw new Error('Failed to remove the recovery code')
}

// ── Parent account recovery (public — no session required; that's the point) ─

export interface RecoveryMethods {
  recovery_secret: RecoverySecretKind
  totp: boolean
  webauthn: boolean
  recovery_possible: boolean
}

export async function fetchRecoveryMethods(): Promise<RecoveryMethods> {
  const res = await fetch(`${BASE}/auth/recovery/methods`)
  if (!res.ok) throw new Error('Could not check account recovery availability')
  return res.json()
}

export async function recoveryWebauthnOptions(): Promise<object> {
  const res = await fetch(`${BASE}/auth/recovery/webauthn/options`, { method: 'POST' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'No security key is enrolled')
  }
  return res.json()
}

export interface RecoveryVerifyPayload {
  // Either a recovery PIN or a recovery code — whichever this parent
  // enrolled (they're mutually exclusive; the backend tries both).
  recovery_secret?: string
  totp_code?: string
  webauthn_credential?: object
}

export async function verifyRecovery(payload: RecoveryVerifyPayload): Promise<{ recovery_token: string }> {
  const res = await fetch(`${BASE}/auth/recovery/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Could not verify enough recovery factors')
  }
  return res.json()
}

export async function resetPasswordRecovery(recoveryToken: string, newPassword: string): Promise<void> {
  const res = await fetch(`${BASE}/auth/recovery/reset-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${recoveryToken}` },
    body: JSON.stringify({ new_password: newPassword }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Could not reset the password')
  }
}

// ── Streaming tutor chat ─────────────────────────────────────────────────────

/** Strips the "data:image/png;base64," prefix a canvas data URL carries. */
function stripDataUrlPrefix(dataUrl: string): string {
  const idx = dataUrl.indexOf(',')
  return idx === -1 ? dataUrl : dataUrl.slice(idx + 1)
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

/** Shared line-buffered SSE parser used by the tutor, sandbox, and
 *  voice-streaming chat streams — generic over the event shape since the
 *  voice stream (VoiceStreamEvent, see services/voiceApi.ts) and tutor
 *  chat stream (StreamChunk) differ, but both are a sequence of plain-JSON
 *  "data: " lines ending in a {type: 'done'} sentinel. */
export async function* parseSSEStream<T extends { type: string }>(res: Response): AsyncGenerator<T> {
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
      if (line.startsWith('data: ')) {
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
}

export async function* streamTutorChat(
  token: string,
  config: SessionConfig,
  subject: Subject,
  history: ChatMessage[],
  childMessage: string,
  signal?: AbortSignal,
  drawingImageDataUrl?: string | null,
  timeOfDay?: TimeOfDay | null,
  localDate?: string | null
): AsyncGenerator<StreamChunk> {
  // The debug panel is the only way a report like "greeting doesn't match
  // the time of day" or "wrong week's poem" can actually be diagnosed
  // remotely — neither value was ever traced anywhere before, so a family
  // hitting either had no way to show what the client thought "now" was.
  logDebug(`streamTutorChat local_date=${localDate ?? 'null'} local_time_of_day=${timeOfDay ?? 'null'}`)
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
      local_time_of_day: timeOfDay ?? null,
      local_date: localDate ?? null,
    }),
    signal,
  })

  if (!res.ok) {
    throw new Error('Tutor request failed — check your connection')
  }

  yield* parseSSEStream<StreamChunk>(res)
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
  const res = await fetch(`${BASE}/tutor/extract-narration`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ filename, content_base64: contentBase64 }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Could not read that file — try a .txt or .pdf export instead.')
  }
  const data = await res.json()
  return data.text
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

  yield* parseSSEStream<StreamChunk>(res)
}

// ── Admin ────────────────────────────────────────────────────────────────────

export interface SystemStatus {
  voice_profiles_enrolled: number
  student_names: string[]
  locale: string
  encryption: string
  key_storage: string
  audit_log: string
  usage: UsageSummary
  license: LicenseStatus | null
}

export async function fetchLicenseStatus(token: string): Promise<LicenseStatus | null> {
  const res = await fetch(`${BASE}/admin/license`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Could not load license status')
  const data = await res.json()
  return data.license
}

/** Applies a new license key (renewal/upgrade) — verified server-side and
 *  effective immediately, no restart. Throws with the server's own message
 *  on an invalid or expired key. */
export async function applyLicenseKey(token: string, licenseKey: string): Promise<LicenseStatus | null> {
  const res = await fetch(`${BASE}/admin/license`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ license_key: licenseKey }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || 'Could not apply that license key')
  return data.license
}

export async function fetchSystemStatus(token: string): Promise<SystemStatus> {
  const res = await fetch(`${BASE}/admin/status`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Status unavailable')
  return res.json()
}

export async function fetchStudentUsage(token: string, studentName: string): Promise<UsageSummary> {
  const res = await fetch(`${BASE}/admin/usage/${encodeURIComponent(studentName)}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`Failed to load usage for ${studentName}`)
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

/**
 * Permanently deletes a student and ALL of their data — narration history,
 * learner profile, mastery tracking, session transcripts, usage events,
 * voice enrollment, not just today's pod config. Irreversible — the
 * caller (PodDashboard.tsx) requires the parent to type the student's
 * name to confirm before calling this. See docs/DATA_RETENTION.md.
 */
export async function deleteStudentData(token: string, studentName: string): Promise<void> {
  const res = await fetch(`${BASE}/pod/configs/${encodeURIComponent(studentName)}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`Failed to delete ${studentName}'s data`)
}

/**
 * Persists the child's own mute/unmute choice for Bede's spoken narration,
 * so it's remembered next session — see SocraticChat.tsx's TTS toggle.
 * Best-effort: a failed save shouldn't interrupt the session the child is
 * already in, so callers should treat this as fire-and-forget.
 */
export async function updateVoiceNarrationPreference(
  token: string,
  studentName: string,
  voiceNarrationEnabled: boolean
): Promise<void> {
  await fetch(`${BASE}/pod/configs/${encodeURIComponent(studentName)}/voice-narration`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ voice_narration_enabled: voiceNarrationEnabled }),
  })
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

// ── Beta feedback ──────────────────────────────────────────────────────────
// Routes CX/UX/content-quality feedback to the operator's own inbox — never
// persisted server-side beyond that one email. See
// homeschool-api/routers/feedback.py.

export type FeedbackCategory = 'cx' | 'ux' | 'content_quality' | 'other' | 'onboarding'

/** Checked before showing the feedback button at all, so it never appears
 *  only to fail on submit on a deployment where FEEDBACK_EMAIL isn't set. */
export async function isFeedbackEnabled(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/feedback/enabled`)
    if (!res.ok) return false
    const data = await res.json()
    return Boolean(data.enabled)
  } catch {
    return false
  }
}

export async function submitFeedback(
  token: string,
  category: FeedbackCategory,
  message: string,
  rating?: number,
  contactEmail?: string,
): Promise<void> {
  const res = await fetch(`${BASE}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      category,
      message,
      rating: rating || undefined,
      contact_email: contactEmail?.trim() || undefined,
    }),
  })
  if (!res.ok) throw new Error('Could not send feedback right now — please try again later.')
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

export async function fetchLearnerBehaviorCheck(
  token: string,
  studentName: string
): Promise<LearnerBehaviorCheck | null> {
  const res = await fetch(`${BASE}/narration/${encodeURIComponent(studentName)}/behavior-check`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error(`Failed to load the behavior check for ${studentName}`)
  return res.json() // null body when not currently profiled kinesthetic
}

export async function fetchMasteryProfileSummary(
  token: string,
  studentName: string
): Promise<MasteryProfileSummary | null> {
  const res = await fetch(`${BASE}/diagnostic/${encodeURIComponent(studentName)}/summary`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Failed to load the math mastery summary for ${studentName}`)
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
