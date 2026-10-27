import type { SessionConfig, Subject, ChatMessage, StreamChunk, NarrationAssessmentData, LearnerProfileData, LearnerBehaviorCheck, MasteryProfileSummary, UsageSummary, AgenticLoopStats, LicenseStatus, AIProviderStatus, AIProviderName, WorkLedger, PodWorkRoster } from '../types'
import type { TimeOfDay } from '../store/sessionStore'
import { logDebug } from '../hooks/debugBus'
import { getOrCreateDeviceId } from '../utils/deviceId'
import { isNetworkFailure } from '../utils/networkFailure'
import { ApiRequestError } from '../utils/requestFailure'

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
  // P9 device revocation (core/device_registry.py) — identifies this
  // physical device so a parent can later revoke it (see fetchDevices/
  // revokeDevice below) if it's lost or compromised. null when
  // localStorage is unavailable (getOrCreateDeviceId's own fallback);
  // JSON.stringify drops a null-valued key entirely, so an omitted
  // device_id here is indistinguishable from an older client that never
  // sent one — LoginRequest.device_id is optional server-side for exactly
  // that reason.
  const deviceId = getOrCreateDeviceId()
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role, credential, ...(locale ? { locale } : {}), ...(deviceId ? { device_id: deviceId } : {}) }),
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

// ── Privileged-access step-up (P8, core/elevation.py) ────────────────────
// Management-plane actions (the audit log, licensing, the AI provider
// switch, any auth/recovery factor change, permanent student deletion)
// additionally require a recent elevation. ElevationPrompt.tsx is what
// actually calls this — it intercepts the 403 those endpoints return when
// unelevated and prompts for the password itself, so no individual call
// site above needs to know elevation exists at all.
export interface ElevationResult {
  elevated: boolean
  expiresAt: string
  ttlSeconds: number
}

export async function elevateSession(token: string, password: string, totpCode?: string): Promise<ElevationResult> {
  const res = await fetch(`${BASE}/auth/elevate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ password, totp_code: totpCode || '' }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    // /auth/elevate's own failures are always plain-string details (wrong
    // password, missing/invalid TOTP, no session id) — never the structured
    // {elevation_required: true} shape the endpoints IT unlocks return.
    throw new Error(typeof err.detail === 'string' ? err.detail : 'Could not confirm your password')
  }
  const data = await res.json()
  return { elevated: data.elevated, expiresAt: data.expires_at, ttlSeconds: data.ttl_seconds }
}

// ── P9 device revocation (core/device_registry.py) ────────────────────────
// "Revoke that lost tablet" — the visible device list
// docs/DEVICE_IDENTITY_DESIGN.md calls "the feature families actually ask
// for". See utils/deviceId.ts for what device_id is and is not (a
// revocation mechanism, not a cryptographic identity).

export interface DeviceInfo {
  device_id: string
  first_seen_at: string
  last_seen_at: string
  last_role: string
  last_user_agent: string
  revoked: boolean
  revoked_at: string | null
}

export async function fetchDevices(token: string): Promise<DeviceInfo[]> {
  const res = await fetch(`${BASE}/admin/devices`, { headers: { Authorization: `Bearer ${token}` } })
  if (!res.ok) throw new Error('Failed to load devices')
  return res.json()
}

// require_elevated_parent server-side (P8) — revoking a device is exactly
// the class of consequential, hard-to-undo-by-retrying action step-up
// exists for. ElevationPrompt.tsx (App.tsx) handles the 403 this can
// return the same way it handles every other elevation-gated call; this
// function needs no awareness of that itself.
export async function revokeDevice(token: string, deviceId: string): Promise<DeviceInfo> {
  const res = await fetch(`${BASE}/admin/devices/${encodeURIComponent(deviceId)}/revoke`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(typeof err.detail === 'string' ? err.detail : 'Failed to revoke device')
  }
  return res.json()
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
  if (!res.ok) {
    // A parent who just tripped the login lockout is exactly who needs this
    // call to succeed next — AccountRecovery.tsx tells a transient 429 apart
    // from a genuine "recovery isn't configured" failure via this flag,
    // rather than showing the same permanent-looking message for both.
    const err = new Error('Could not check account recovery availability') as Error & { status?: number }
    err.status = res.status
    throw err
  }
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

// ── A dropped connection is not a lost turn ─────────────────────────────
//
// `fetch()` rejecting with a TypeError means no response was received at
// all: the request never reached a server, or the connection died before
// any headers came back. On a child's tablet on mobile data that is an
// ordinary event, not an exceptional one — a real trace from a 5G phone
// mid-lesson shows the POST failing after 12.9 seconds, the child's own
// answer ("I was coughing the whole day") discarded, and nothing but
// Safari's own words, "Load failed", where Bede's reply should have been.
//
// The turn was simply gone. Nothing retried it, and the only thing that
// eventually spoke was the 60-second idle timer sending [CONTINUE], which
// asks the child to go on as though they had said nothing at all.
//
// `useHybridVoiceInput.ts` already reached this conclusion for the request
// that OPENS a voice stream — see its START_STREAM_MAX_ATTEMPTS, whose own
// comment records that without a retry "every single hold immediately gave
// up ... making voice input feel unusable on anything less than a
// rock-solid connection." That reasoning was never applied to the turn
// carrying the child's actual words, which is the more costly of the two
// to lose. This applies it.
//
// Three properties keep it honest:
//
//   1. **Only a transport failure retries.** A 4xx/5xx is a decision the
//      server actually made; repeating it just asks to be refused twice.
//      `isNetworkFailure` is the same predicate the voice path uses.
//   2. **Only before anything has been shown.** Once a single chunk has
//      reached the caller, text is on screen and a retry would duplicate
//      it mid-sentence, so a failure after that point is final.
//   3. **Never past an abort.** A child who navigated away, or a turn
//      superseded by the next one, must not have a request quietly
//      reissued on their behalf.
//
// Deliberately NOT retried: a stall. `parseSSEStream`'s 60-second
// StreamStallError means the server accepted the request and then went
// quiet, so it is very likely still working — reissuing costs a second
// model call for a family and buys nothing a longer wait would not.
const TUTOR_MAX_ATTEMPTS = 3
const TUTOR_RETRY_BASE_DELAY_MS = 600

/** A cancellable pause, so a retry delay can't outlive the turn it belongs to. */
function retryPause(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms)
    signal?.addEventListener(
      'abort',
      () => {
        clearTimeout(timer)
        reject(new DOMException('Aborted', 'AbortError'))
      },
      { once: true },
    )
  })
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
  localDate?: string | null,
  sessionId?: string | null,
  timeRemainingSeconds?: number | null,
  previousSubject?: Subject | null
): AsyncGenerator<StreamChunk> {
  // The debug panel is the only way a report like "greeting doesn't match
  // the time of day" or "wrong week's poem" can actually be diagnosed
  // remotely — neither value was ever traced anywhere before, so a family
  // hitting either had no way to show what the client thought "now" was.
  logDebug(`streamTutorChat local_date=${localDate ?? 'null'} local_time_of_day=${timeOfDay ?? 'null'}`)
  // See TUTOR_MAX_ATTEMPTS above for why this loop exists and what it
  // deliberately will not retry.
  for (let attempt = 1; ; attempt++) {
    // Set before the first yield, so a failure that arrives after the child
    // has already seen part of Bede's reply is final rather than restarting
    // the sentence they are mid-way through reading.
    let delivered = false
    try {
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
          // Keys this sitting's mastery estimate when the deployment is set to
          // keep no profile between sessions (see the backend's
          // retain_mastery_profiles). Ignored entirely otherwise.
          session_id: sessionId ?? null,
          // The subject the child just came from, so Bede marks the change
          // instead of greeting them again (TutorRequest.previous_subject).
          previous_subject: previousSubject ?? null,
          // Seconds left on whichever of the child's clocks runs out first
          // (TutorSession.tsx's taskBudgetSecs). Lets Bede decline to START a
          // narration or a drawing the block cannot hold, rather than the
          // timer cutting the child off mid-task — see the backend's
          // _time_remaining_note and services/action_governance.py. Null
          // during a break, and null here disables both rules rather than
          // assuming the worst.
          time_remaining_seconds: timeRemainingSeconds ?? null,
        }),
        signal,
      })

      if (!res.ok) {
        throw new Error('Tutor request failed — check your connection')
      }

      for await (const chunk of parseSSEStream<StreamChunk>(res)) {
        delivered = true
        yield chunk
      }
      return
    } catch (err) {
      if (delivered || attempt >= TUTOR_MAX_ATTEMPTS || signal?.aborted || !isNetworkFailure(err)) {
        throw err
      }
      const wait = TUTOR_RETRY_BASE_DELAY_MS * attempt
      logDebug(`streamTutorChat retrying after network failure (attempt ${attempt}/${TUTOR_MAX_ATTEMPTS}, waiting ${wait}ms)`)
      await retryPause(wait, signal)
    }
  }
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
  signal?: AbortSignal,
  educatorPlanning = false
): AsyncGenerator<StreamChunk> {
  const res = await fetch(`${BASE}/sandbox/${educatorPlanning ? 'educator-chat' : 'chat'}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      ...(educatorPlanning ? {} : { sandbox_pin: sandboxPin }),
      conversation_history: history,
      message,
      custom_instructions: customInstructions,
    }),
    signal,
  })

  if (res.status === 401) throw new Error(educatorPlanning ? 'Please sign in again with your educator passkey' : 'Incorrect sandbox PIN')
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
  if (!res.ok) {
    const detail: unknown = data?.detail
    const reason = typeof detail === 'string' ? detail :
      Array.isArray(detail) ? detail
        .map((entry: unknown) =>
          typeof entry === 'object' && entry !== null && 'msg' in entry &&
          typeof entry.msg === 'string' ? entry.msg : '')
        .filter(Boolean).join('; ') : ''
    throw new Error(reason || 'Could not apply that activation code. Verify the full code and try again.')
  }
  return data.license
}

export async function fetchAIProviderStatus(token: string): Promise<AIProviderStatus> {
  const res = await fetch(`${BASE}/admin/ai-provider`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Could not load AI provider status')
  return res.json()
}

/** Switches which configured adapter serves as primary — effective
 *  immediately (no .env edit, no restart). Pass `null` to clear the
 *  override and revert to this deployment's env-configured order. Throws
 *  with the server's own message if the chosen provider isn't configured. */
export async function setAIProvider(token: string, provider: AIProviderName | null): Promise<AIProviderStatus> {
  const res = await fetch(`${BASE}/admin/ai-provider`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ provider }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || 'Could not switch AI provider')
  return data
}

/** Chooses which configured adapter is tried first if primary errors —
 *  only meaningful with 3+ adapters configured. Pass `null` to clear the
 *  override and revert to whichever adapter is next in the env order. */
export async function setAIProviderSecondary(token: string, provider: AIProviderName | null): Promise<AIProviderStatus> {
  const res = await fetch(`${BASE}/admin/ai-provider/secondary`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ provider }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || 'Could not switch the failover AI provider')
  return data
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

export async function fetchAgenticLoopStats(token: string, days: number): Promise<AgenticLoopStats> {
  const res = await fetch(`${BASE}/admin/agentic-loop-stats?days=${encodeURIComponent(days)}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Failed to load tool-loop stats')
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
  durationMinutes: number,
  sessionId?: string | null
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
      // Lets the summary report (and then release) this session's mastery
      // estimate on deployments that keep no profile between sessions.
      session_id: sessionId ?? null,
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

export type FeedbackCategory = 'cx' | 'ux' | 'content_quality' | 'other' | 'onboarding' | 'beta_survey'

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
  studentName: string,
  subjectArea: 'mathematics' | 'composition' | 'phonics' | 'language_exposure' | 'literacy' | 'music_knowledge' = 'mathematics'
): Promise<MasteryProfileSummary | null> {
  const res = await fetch(
    `${BASE}/diagnostic/${encodeURIComponent(studentName)}/summary?subject_area=${subjectArea}`,
    { headers: { Authorization: `Bearer ${token}` } }
  )
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Failed to load the ${subjectArea} mastery summary for ${studentName}`)
  return res.json()
}

/**
 * The work ledger: what this student has actually finished. Distinct from
 * fetchMasteryProfileSummary above, which reports inferred mastery.
 */
export async function fetchStudentActivity(
  token: string,
  studentName: string,
  sinceDays = 90,
): Promise<WorkLedger> {
  const res = await fetch(
    `${BASE}/diagnostic/${encodeURIComponent(studentName)}/activity?since_days=${sinceDays}`,
    { headers: { Authorization: `Bearer ${token}` } }
  )
  if (!res.ok) throw new Error(`Failed to load the work ledger for ${studentName}`)
  return res.json()
}

export interface SubjectCoverage {
  stale_after_days: number
  subjects: Array<{
    subject: string
    label: string
    last_taught: string | null
    days_since: number | null
    needs_attention: boolean
  }>
  note: string
}

/**
 * Which scheduled subjects are actually getting taught. Answers a question
 * a parent could not previously ask — a subject with nothing to show for it
 * might never have been scheduled, or might have been scheduled for six
 * weeks and opened twice. Reports the SCHEDULE, never the child.
 */
export async function fetchSubjectCoverage(
  token: string,
  studentName: string,
): Promise<SubjectCoverage | null> {
  const res = await fetch(
    `${BASE}/diagnostic/${encodeURIComponent(studentName)}/coverage`,
    { headers: { Authorization: `Bearer ${token}` } }
  )
  if (res.status === 404) return null
  if (!res.ok) return null
  return res.json()
}

/**
 * The same ledger across the parent's own students, keyed by skill. Used
 * to arrange peer teaching from evidence of completed work — never to rank
 * children, which is why the payload has no per-student total.
 */
export async function fetchPodActivity(
  token: string,
  studentNames: string[],
  sinceDays = 90,
): Promise<PodWorkRoster> {
  // One repeated `students=` parameter per name, NOT a comma-joined list:
  // student_name is free text a parent types (max 50 chars, no character
  // restriction), so a comma in a name would have split it into two
  // students that don't exist and silently returned a short roster.
  const params = new URLSearchParams()
  for (const name of studentNames) params.append('students', name)
  params.set('since_days', String(sinceDays))
  const res = await fetch(
    `${BASE}/diagnostic/pod/activity?${params.toString()}`,
    { headers: { Authorization: `Bearer ${token}` } }
  )
  if (!res.ok) throw new Error('Failed to load the pod work roster')
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


// ── Parent-entered external & classical assessment evidence ─────────────────
// Never merge these values into Bede's diagnostic mastery engine. Scores
// and benchmark categories are reported by the educator, not computed here.
export type EducatorAssessmentFramework = 'dibels8' | 'classical' | 'external_other'
export type EducatorAssessmentAssistance = 'unaided' | 'with_a_hint' | 'with_help'
export type EducatorAssessmentBand =
  | 'not_reported'
  | 'core_negligible_risk'
  | 'core_minimal_risk'
  | 'strategic_some_risk'
  | 'intensive_at_risk'
  // Pre-upgrade labels retained to display older records accurately.
  | 'at_or_above_benchmark'
  | 'below_benchmark'
  | 'well_below_benchmark'
export type EducatorAssessmentScoreUnit = 'count' | 'correct_per_minute' | 'percent' | 'points' | 'other'
export type DibelsGrade = 'K' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8'
export type DibelsWindow = 'beginning_of_year' | 'middle_of_year' | 'end_of_year' | 'progress_monitoring'
export interface AssessmentFrameworkMetadata {
  id: EducatorAssessmentFramework
  label: string
  supported_measures: string[]
  measure_units?: Record<string, EducatorAssessmentScoreUnit>
  grades?: DibelsGrade[]
  windows?: DibelsWindow[]
  reported_bands?: EducatorAssessmentBand[]
  administration: string
  interpretation: string
}
export async function fetchAssessmentFrameworks(token: string): Promise<AssessmentFrameworkMetadata[]> {
  const res = await fetch(`${BASE}/diagnostic/assessment-frameworks`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Could not load the current assessment framework catalog')
  return res.json()
}

export interface EducatorAssessmentInput {
  framework: EducatorAssessmentFramework
  measure: string
  assessed_on: string
  source_name: string
  score?: number | null
  score_unit?: EducatorAssessmentScoreUnit | null
  reported_band?: EducatorAssessmentBand | null
  assistance?: EducatorAssessmentAssistance | null
  assessed_grade?: DibelsGrade | null
  assessment_window?: DibelsWindow | null
}

export interface EducatorAssessmentRecord extends EducatorAssessmentInput {
  id: number
  student_name: string
  created_at: string
  record_status: 'educator_entered_unverified'
  quality_flags: string[]
}

export async function fetchEducatorAssessments(
  token: string, studentName: string,
): Promise<EducatorAssessmentRecord[]> {
  const res = await fetch(
    `${BASE}/diagnostic/${encodeURIComponent(studentName)}/assessment-records`,
    { headers: { Authorization: `Bearer ${token}` } },
  )
  if (!res.ok) throw new Error('Could not load educator-entered assessments')
  return res.json()
}

export async function saveEducatorAssessment(
  token: string, studentName: string, payload: EducatorAssessmentInput,
): Promise<EducatorAssessmentRecord> {
  const res = await fetch(
    `${BASE}/diagnostic/${encodeURIComponent(studentName)}/assessment-records`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
    },
  )
  if (!res.ok) throw new Error('Could not save assessment. Check the fields and try again.')
  return res.json()
}

export async function removeEducatorAssessment(
  token: string, studentName: string, id: number,
): Promise<void> {
  const res = await fetch(
    `${BASE}/diagnostic/${encodeURIComponent(studentName)}/assessment-records/${id}`,
    { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } },
  )
  if (!res.ok) throw new Error('Could not remove assessment')
}


// ── Classroom/household roster capacity from the signed Bede license ───
// Locuto's v1 10-person *messaging* Pod cap never caps the number of
// enrolled learners in a school. Organizational Locuto entitlement
// synchronization is not implemented; the API explicitly says so.
export interface RosterCapacity {
  schema_version: 1
  enrolled_students: number
  licensed_children: number | null
  remaining_licensed_children: number | null
  capacity_authority: 'signed_bede_license' | 'no_active_signed_student_limit'
  locuto_organization_max_children: null
  locuto_entitlement_verified: false
  locuto_messaging_pod_max_members: number
  messaging_limit_applies_to_student_roster: false
  roster_scope: 'one_installation'
}
export async function fetchRosterCapacity(token: string): Promise<RosterCapacity> {
  const res = await fetch(`${BASE}/pod/roster-capacity`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Could not load roster capacity')
  return res.json()
}


// ── Standalone Classical Educator pilot ───────────────────────────────────
// This is NOT a parent session and never inherits admin permissions.
export interface InstructorAccount {
  id: string
  username: string
  enabled: boolean
  learner_count: number
}
export interface InstructorProvisioned {
  id: string
  username: string
  totp_secret: string
  totp_provisioning_uri: string
  security_notice: string
}
export interface LocutoCapacity {
  provider: string
  integration_status: 'planning_only_not_connected'
  active_group_messages_enabled: false
  roster_or_student_data_transferred: false
  maximum_members: number
  minimum_members: number
  groups: Array<{ learner_count: number; member_count_including_educator: number }>
}
export interface DibelsProgress {
  source: string
  cannot_establish_causal_learning_efficacy: true
  data_quality: string
  automatic_benchmark_scoring: false
  total_dibels_records: number
  records_excluded_from_comparison: number
  series: Array<{
    measure: string
    assessed_grade: string
    unit: string
    same_instrument_same_grade_only: true
    points: Array<{
      date: string
      assessment_window: string | null
      score_as_reported: number
      difference_from_previous_same_grade_measure: number | null
      risk_category_as_reported: string | null
      source: string
      record_id: number
    }>
  }>
}

async function educatorApi<T>(path: string, token: string, method = 'GET', body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new ApiRequestError(
      res.status, typeof detail.detail === 'string' ? detail.detail : 'Educator request failed')
  }
  return res.status === 204 ? undefined as T : res.json()
}

export async function fetchEducatorPilotMode(): Promise<{ enabled: boolean; shared_child_pin_disabled: boolean }> {
  const res = await fetch(`${BASE}/auth/educator-mode`)
  if (!res.ok) return { enabled: false, shared_child_pin_disabled: false }
  return res.json()
}

/** Real WebAuthn UV, using the browser-native helper shared with parent MFA. */
export async function educatorPasskeyLogin(username: string): Promise<LoginResult> {
  const { authenticateSecurityKey } = await import('./webauthn')
  const first = await fetch(`${BASE}/auth/educator-passkey/login/options`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username }), cache: 'no-store',
  })
  if (!first.ok) throw new Error('No active educator passkey is available. Contact your school administrator.')
  const ceremony = await first.json()
  const credential = await authenticateSecurityKey(ceremony.options)
  const verified = await fetch(`${BASE}/auth/educator-passkey/login/verify`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, ceremony_id: ceremony.ceremony_id, credential }),
    cache: 'no-store',
  })
  if (!verified.ok) throw new Error('Passkey verification did not succeed. Try again or contact your school.')
  return toLoginResult(await verified.json())
}

export async function educatorPasskeyEnroll(ticket_id: string, ticket_token: string): Promise<void> {
  const { registerSecurityKey } = await import('./webauthn')
  const request = { ticket_id, ticket_token }
  const first = await fetch(`${BASE}/auth/educator-passkey/register/options`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request), cache: 'no-store',
  })
  if (!first.ok) throw new Error('Invitation expired or invalid. Request a new invitation.')
  const ceremony = await first.json()
  const credential = await registerSecurityKey(ceremony.options)
  const verified = await fetch(`${BASE}/auth/educator-passkey/register/verify`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...request, ceremony_id: ceremony.ceremony_id, credential }),
    cache: 'no-store',
  })
  if (!verified.ok) throw new Error('Passkey enrollment could not be verified. Request a fresh invitation.')
}

export const invitePasskeyInstructor = (token: string, username: string, institutional_email: string) =>
  educatorApi<{ sent: boolean; username: string }>('/auth/educator-passkey/invite',
    token, 'POST', { username, institutional_email })

export interface EducatorPasskeySummary {
  id: string
  created_at: string
}

export const fetchMyEducatorPasskeys = (token: string) =>
  educatorApi<EducatorPasskeySummary[]>('/auth/educator-passkey/credentials', token)

export const revokeMyEducatorPasskey = (token: string, id: string) =>
  educatorApi<{ revoked: boolean; all_previous_sessions_invalidated: boolean }>(
    `/auth/educator-passkey/credentials/${encodeURIComponent(id)}/revoke`, token, 'POST',
  )

export const fetchInstructors = (token: string) =>
  educatorApi<InstructorAccount[]>('/educators/accounts', token)

export const provisionInstructor = (token: string, username: string, password: string) =>
  educatorApi<InstructorProvisioned>(
    '/educators/accounts', token, 'POST', { username, password },
  )

export const assignInstructorRoster = (token: string, educatorId: string, configs: SessionConfig[]) =>
  educatorApi<{ learner_count: number; new_learner_count: number; messaging: LocutoCapacity }>(
    `/educators/accounts/${encodeURIComponent(educatorId)}/roster`,
    token, 'PUT', { configs },
  )

export const disableInstructor = (token: string, educatorId: string) =>
  educatorApi<void>(
    `/educators/accounts/${encodeURIComponent(educatorId)}/disable`, token, 'POST',
  )

export const fetchInstructorRoster = (token: string) =>
  educatorApi<SessionConfig[]>('/educators/me/roster', token)

export const fetchInstructorLocutoCapacity = (token: string) =>
  educatorApi<LocutoCapacity>('/educators/me/locuto-capacity', token)

export const fetchInstructorFrameworks = (token: string) =>
  educatorApi<AssessmentFrameworkMetadata[]>('/educators/me/assessment-frameworks', token)

export const fetchInstructorDibelsProgress = (token: string, student: string) =>
  educatorApi<DibelsProgress>(
    `/educators/me/students/${encodeURIComponent(student)}/dibels-progress`, token,
  )

export const fetchInstructorAssessments = (token: string, student: string) =>
  educatorApi<EducatorAssessmentRecord[]>(
    `/educators/me/students/${encodeURIComponent(student)}/assessments`, token,
  )

export const saveInstructorAssessment = (
  token: string, student: string, payload: EducatorAssessmentInput,
) =>
  educatorApi<EducatorAssessmentRecord>(
    `/educators/me/students/${encodeURIComponent(student)}/assessments`,
    token, 'POST', payload,
  )

export const fetchInstructorActivity = (token: string, student: string) =>
  educatorApi<{ total: number; skills: unknown[] }>(
    `/educators/me/students/${encodeURIComponent(student)}/activity`, token,
  )


// ── Valor pilot G2 teacher journey (/pilot/me/learners/*) ──────────────────
// UUID-scoped: every call names an immutable learner id the server re-checks
// against the educator's active campus grant. Display names are never keys.

export interface PilotLearner {
  learner_id: string
  campus_id: string
  display_name: string
}

export interface PilotEvidence {
  evidence_id: string
  recorded_at: string
  framework: 'dibels8' | 'classical' | 'external_other'
  measure: string
  assessed_on: string
  source_name: string
  score?: number | null
  score_unit?: string | null
  reported_band?: EducatorAssessmentBand | null
  assistance?: string | null
}

export interface PilotRecommendation {
  recommendation_id: string
  learner_id: string
  status: 'pending' | 'approved' | 'edited' | 'rejected'
  version: number
  // The only state that exists: delivery to a learner is unavailable
  // (Owner Decision 7, #585). Optional so an older server still type-checks.
  delivery_state?: 'NOT_REQUESTED'
  policy_version: string
  source_evidence_ids: string[]
  proposal: string
  rationale: string[]
  authorized_instruction: string | null
  created_at: string
  decided_at: string | null
}

export type PilotRecommendationResult =
  | ({ abstained: false } & PilotRecommendation)
  | { abstained: true; reason: string; policy_version: string }

export interface PilotDecisionInput {
  action: 'approve' | 'edit' | 'reject'
  expected_version: number
  edited_text?: string
  note?: string
}

export interface PilotLedger {
  chain_valid: boolean
  entries: Array<{ seq: number; action: string; educator_id: string; created_at: string; note: string | null }>
}

const pilot = (learnerId: string) => `/pilot/me/learners/${encodeURIComponent(learnerId)}`

export const fetchPilotLearners = (token: string) =>
  educatorApi<PilotLearner[]>('/pilot/me/learners', token)

export const fetchPilotEvidence = (token: string, learnerId: string) =>
  educatorApi<PilotEvidence[]>(`${pilot(learnerId)}/evidence`, token)

export const recordPilotEvidence = (token: string, learnerId: string, entry: EducatorAssessmentInput) =>
  educatorApi<PilotEvidence>(`${pilot(learnerId)}/evidence`, token, 'POST', entry)

export const fetchPilotRecommendations = (token: string, learnerId: string) =>
  educatorApi<PilotRecommendation[]>(`${pilot(learnerId)}/recommendations`, token)

export const requestPilotRecommendation = (token: string, learnerId: string) =>
  educatorApi<PilotRecommendationResult>(`${pilot(learnerId)}/recommendations`, token, 'POST')

export const decidePilotRecommendation = (
  token: string, learnerId: string, recommendationId: string, decision: PilotDecisionInput,
) => educatorApi<PilotRecommendation>(
  `${pilot(learnerId)}/recommendations/${encodeURIComponent(recommendationId)}/decision`,
  token, 'POST', decision,
)

export const fetchPilotLedger = (token: string, learnerId: string) =>
  educatorApi<PilotLedger>(`${pilot(learnerId)}/decisions`, token)

// ── Canonical DIBELS record + separate teacher observation ────────────────
// Uses the existing campus UUID/learner UUID G1-gated routes. Official forms
// stay at the University of Oregon / authorized provider, not in this app.
export type OfficialMeasureStatus =
  | 'scored' | 'not_administered_by_rule' | 'not_administered_other'
  | 'skipped' | 'not_applicable' | 'interrupted' | 'invalid' | 'voided'
export type OfficialAdministrationState =
  | 'DRAFT' | 'READY_FOR_ADMINISTRATION' | 'IN_PROGRESS'
  | 'COMPLETED_PENDING_REVIEW' | 'FINALIZED' | 'EVIDENCE_AVAILABLE'
  | 'TEACHER_DECISION_PENDING' | 'TEACHER_DECISION_RECORDED'
  | 'INSTRUCTIONAL_PLAN_READY' | 'PROGRESS_MONITORING_SCHEDULED'
  | 'INTERRUPTED' | 'INVALID_ADMINISTRATION'
  | 'VOIDED_BY_TEACHER' | 'SUPERSEDED_WITH_AUDIT_LINK'

export interface OfficialMarks {
  started_at?: string | null
  ended_at?: string | null
  elapsed_seconds?: number | null
  last_item_attempted?: number | null
  correct_marks?: number | null
  error_marks?: number | null
  self_corrections?: number | null
  discontinue_rule_result?: 'not_checked' | 'met' | 'not_met' | 'not_applicable' | null
  interruption?: string | null
  administration_fidelity_note?: string | null
  accuracy_percent?: number | null
  teacher_reviewed?: boolean
}
export interface OfficialScoreEntry {
  measure: string
  administration_status: OfficialMeasureStatus
  raw_score: number | null
  score_unit: string | null
  reason?: string | null
  benchmark_label?: 'Well Below Benchmark' | 'Below Benchmark' | 'At Benchmark' | 'Above Benchmark' | null
  support_label?: 'Most Support' | 'Some Support' | 'Goal' | 'Above Goal' | null
  calculation_version?: string
  official_marks?: OfficialMarks | null
  composite_eligible?: boolean | null
}
export interface OfficialAssessment {
  assessment_id: string
  campus_id: string
  learner_id: string
  administrator_id: string
  instrument: 'dibels8'
  edition: string
  form_id: string
  measure: string
  grade: DibelsGrade
  administration_purpose: 'benchmark' | 'progress_monitoring' | 'instructional_check' | 'teacher_observation'
  instructional_cycle: string
  administered_at: string
  report_source: string
  official_benchmark_window: 'BOY' | 'MOY' | 'EOY' | 'none'
  state: OfficialAdministrationState
  snapshot_sha256: string | null
  scores?: OfficialScoreEntry[]
  finalized_at: string | null
}
export interface TeacherObservation {
  accuracy_fluency?: string
  error_patterns?: string
  administration_circumstances?: string
  narration_comprehension?: string
  curriculum_already_taught?: string
  teacher_interpretation?: string
  suggested_next_step?: string
}
export interface OfficialProposal {
  proposal_id: string
  assessment_id: string
  version: number
  proposed_next_step: string
  rationale: string[]
  status: string
}
export interface OfficialDataDay {
  proposed_next_steps: OfficialProposal[]
  prior_teacher_decisions: Array<{ assessment_id: string; action: string; outcome: { plan_id: string | null; plan_recorded: boolean; delivery_state: 'NOT_REQUESTED' } }>
  boundaries: { changes_official_scores: false; starts_instruction: false; delivers_instruction: false }
}
const officialBase = (campusId: string, learnerId: string) =>
  `/pilot/campuses/${encodeURIComponent(campusId)}/learners/${encodeURIComponent(learnerId)}`
export const fetchOfficialAssessments = (token: string, campusId: string, learnerId: string) =>
  educatorApi<OfficialAssessment[]>(`${officialBase(campusId, learnerId)}/assessments`, token)
export const fetchOfficialAssessment = (token: string, campusId: string, learnerId: string, id: string) =>
  educatorApi<OfficialAssessment>(`${officialBase(campusId, learnerId)}/assessments/${encodeURIComponent(id)}`, token)
export const createOfficialAssessment = (token: string, campusId: string, learnerId: string, payload: object) =>
  educatorApi<OfficialAssessment>(`${officialBase(campusId, learnerId)}/assessments`, token, 'POST', payload)
export const transitionOfficialAssessment = (
  token: string, campusId: string, learnerId: string, id: string, action: string, expectedState: OfficialAdministrationState,
  resolution?: string,
) => educatorApi<OfficialAssessment>(
  `${officialBase(campusId, learnerId)}/assessments/${encodeURIComponent(id)}/transitions`,
  token, 'POST', { action, expected_state: expectedState, ...(resolution ? { resolution } : {}) },
)
export const enterOfficialScores = (
  token: string, campusId: string, learnerId: string, id: string, scores: OfficialScoreEntry[],
) => educatorApi<OfficialAssessment>(
  `${officialBase(campusId, learnerId)}/assessments/${encodeURIComponent(id)}/scores`,
  token, 'PUT', { scores, responses: [] },
)
export const supersedeOfficialAssessment = (
  token: string, campusId: string, learnerId: string, id: string, reason: string,
) => educatorApi<OfficialAssessment>(
  `${officialBase(campusId, learnerId)}/assessments/${encodeURIComponent(id)}/supersede`,
  token, 'POST', { reason },
)

export const recordOfficialObservation = (
  token: string, campusId: string, learnerId: string, id: string, observation: TeacherObservation,
) => educatorApi<{ evidence_id: string }>(
  `${officialBase(campusId, learnerId)}/assessments/${encodeURIComponent(id)}/evidence`,
  token, 'POST', { teacher_observation: observation },
)
export const requestOfficialProposal = (token: string, campusId: string, learnerId: string, id: string) =>
  educatorApi<OfficialProposal | { abstained: true; reason: string }>(
    `${officialBase(campusId, learnerId)}/assessments/${encodeURIComponent(id)}/proposal`, token, 'POST')
export const fetchOfficialDataDay = (token: string, campusId: string, learnerId: string, cycle: string) =>
  educatorApi<OfficialDataDay>(
    `${officialBase(campusId, learnerId)}/data-day?cycle=${encodeURIComponent(cycle)}`, token)
export const decideOfficialProposal = (
  token: string, campusId: string, learnerId: string, id: string, proposalId: string,
  decision: { action: 'approve' | 'edit' | 'reject'; expected_version: number; edited_text?: string; rationale?: string },
) => educatorApi<{ action: string; authorized_text: string | null }>(
  `${officialBase(campusId, learnerId)}/assessments/${encodeURIComponent(id)}/proposals/${encodeURIComponent(proposalId)}/decision`,
  token, 'POST', decision,
)
export const recordOfficialPlan = (token: string, campusId: string, learnerId: string, id: string, text: string) =>
  educatorApi<{ plan_id: string; decision_id: string; delivery_state: 'NOT_REQUESTED'; status: string }>(
    `${officialBase(campusId, learnerId)}/assessments/${encodeURIComponent(id)}/plan`,
    token, 'POST', { plan_text: text },
  )

export interface OfficialTeacherArtifact {
  artifact_type: 'teacher_use_instructional_plan'
  status: 'teacher_approved_for_offline_use'
  campus_id: string; learner_id: string; assessment_id: string; plan_id: string
  decision_id: string; approved_by: string; approval_action: 'approve' | 'edit'
  assessment_snapshot_sha256: string; plan_text: string; prepared_at: string
  delivery_state: 'NOT_REQUESTED'; disclaimer: string
}
export interface OfficialTeacherFollowUp {
  follow_up_id: string; assessment_id: string; plan_id: string; decision_id: string
  campus_id: string; learner_id: string; teacher_id: string; observed_on: string
  teaching_mode: 'in_person' | 'offline'; observation: string; next_step: string | null
  recorded_at: string; evidence_class: 'teacher_reported_follow_up'
  is_official_assessment: false
}

const officialPlanPath = (campusId: string, learnerId: string, assessmentId: string, planId: string) =>
  `${officialBase(campusId, learnerId)}/assessments/${encodeURIComponent(assessmentId)}/plans/${encodeURIComponent(planId)}`

export const fetchTeacherArtifact = (token: string, campusId: string, learnerId: string, assessmentId: string, planId: string) =>
  educatorApi<OfficialTeacherArtifact>(`${officialPlanPath(campusId, learnerId, assessmentId, planId)}/artifact`, token)
export const fetchTeacherFollowUps = (token: string, campusId: string, learnerId: string, assessmentId: string, planId: string) =>
  educatorApi<OfficialTeacherFollowUp[]>(`${officialPlanPath(campusId, learnerId, assessmentId, planId)}/follow-ups`, token)
export const recordTeacherFollowUp = (
  token: string, campusId: string, learnerId: string, assessmentId: string, planId: string,
  body: { observed_on: string; teaching_mode: 'in_person' | 'offline'; observation: string; next_step?: string },
) => educatorApi<OfficialTeacherFollowUp>(
  `${officialPlanPath(campusId, learnerId, assessmentId, planId)}/follow-ups`, token, 'POST', body,
)

// ── Valor pilot: owner-led learner deletion ────────────────────────────────
// Every call needs the administrator passkey; ElevationPrompt asks for it.
// There is deliberately no session plan or session launch here: delivering
// approved instruction to a learner stays unavailable (Owner Decision 7,
// #585; homeschool-api/tests/test_valor_pilot_delivery_disabled.py).

export interface PilotOwnerCampus { campus_id: string; title: string; enabled: boolean }
export interface PilotOwnerLearner extends PilotLearner { enabled: boolean }
export interface PilotDeletionReceipt {
  receipt_id: string
  campus_id: string
  learner_id: string
  actor: string
  deleted_counts: Record<string, number>
  remaining_counts: Record<string, number>
  deleted_at: string
  receipt_sha256: string
  hash_verified?: boolean
}

const owner = (path: string) => `/pilot/owner${path}`

export const fetchPilotOwnerCampuses = (token: string) =>
  educatorApi<PilotOwnerCampus[]>(owner('/campuses'), token)
export interface PilotCampusStopResult {
  campus_id: string
  status: 'disabled'
  memberships_disabled: number
  grants_revoked: number
  prior_educator_sessions_invalidated: boolean
  learner_records_preserved: boolean
}
export const disablePilotOwnerCampus = (token: string, campusId: string, confirmTitle: string) =>
  educatorApi<PilotCampusStopResult>(
    owner(`/campuses/${encodeURIComponent(campusId)}/disable`),
    token, 'POST', { confirm_campus_id: campusId, confirm_title: confirmTitle },
  )
export const fetchPilotOwnerLearners = (token: string, campusId: string) =>
  educatorApi<PilotOwnerLearner[]>(owner(`/campuses/${encodeURIComponent(campusId)}/learners`), token)
export const deletePilotLearner = (
  token: string, campusId: string, learnerId: string, confirmDisplayName: string,
) => educatorApi<PilotDeletionReceipt>(
  owner(`/campuses/${encodeURIComponent(campusId)}/learners/${encodeURIComponent(learnerId)}/delete`),
  token, 'POST', { confirm_learner_id: learnerId, confirm_display_name: confirmDisplayName },
)
export const fetchPilotDeletionReceipts = (token: string) =>
  educatorApi<PilotDeletionReceipt[]>(owner('/deletion-receipts'), token)


// ── Practice Coach (docs/PRACTICE_COACH.md) ──────────────────────────────
// Parent-only. The backend reads, diagnoses and drafts; nothing reaches the
// child until a parent approves a set.

export type TeacherMark = 'correct' | 'incorrect' | 'partial' | 'unmarked'

export interface PracticeItemReading {
  number: number
  prompt: string
  stimulus?: string | null
  student_response?: string | null
  teacher_mark: TeacherMark
  teacher_correction?: string | null
  confidence: number
  ask_parent?: string | null
}

export interface PracticeSection {
  label: string
  instructions: string
  required_format: 'complete_sentence' | 'single_word' | 'color_fill' | 'free' | 'unknown'
  word_bank: string[]
  items: PracticeItemReading[]
}

export interface GradedAssessment {
  subject: string
  sections: PracticeSection[]
}

export interface PracticeReading {
  id: number
  status: 'needs_review' | 'confirmed'
  assessment: GradedAssessment
  ask_parent: string[]
  teacher_mark_count: { correct: number; total: number; source: 'teacher_marks' }
}

export interface PracticeSetItem {
  kind: 'drill' | 'sentence_habit' | 'retrieval'
  target: string
  prompt: string
  expected_answer: string
  hint: string
}

export interface PracticeSetDraft {
  targets: string[]
  mode: 'drill' | 'retrieval'
  est_minutes: number
  items: PracticeSetItem[]
  parent_script: string
  recheck_schedule: string[]
}

export interface PracticePlan {
  summary: string
  diagnosis: {
    errors: { item_ref: string; category: string; evidence: string; audience: 'parent_and_child' | 'parent_only' }[]
    strengths: { category: string; note: string }[]
    ask_parent: string[]
  }
  practice_set: PracticeSetDraft | null
  set_id: number | null
  status: 'draft' | null
}

export interface ReadingRoute {
  local_available: boolean
  cloud_provider: string | null
}

/** A refusal the parent can act on: the backend wants consent to send the
 *  pages to `provider` for this upload only. */
export class PracticeConsentRequired extends Error {
  constructor(public provider: string | null, message: string) {
    super(message)
  }
}

async function practiceFetch<T>(token: string, path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}/practice${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...(init?.headers || {}) },
  })
  if (!res.ok) {
    let detail: unknown = null
    try { detail = (await res.json())?.detail } catch { /* not json */ }
    if (res.status === 409 && detail && typeof detail === 'object' && (detail as { consent_required?: boolean }).consent_required) {
      const d = detail as { provider: string | null; message: string }
      throw new PracticeConsentRequired(d.provider, d.message)
    }
    throw new Error(typeof detail === 'string' ? detail : 'The practice coach could not complete that step.')
  }
  return res.json()
}

export const fetchPracticePacks = (token: string) =>
  practiceFetch<{ id: string; display_name: string }[]>(token, '/packs')

export const fetchReadingRoute = (token: string) =>
  practiceFetch<ReadingRoute>(token, '/reading-route')

export const readPracticePhotos = (
  token: string, studentName: string,
  body: { subject: string; pages: { data: string }[]; route?: 'local' | 'cloud'; cloud_consent: boolean },
) => practiceFetch<PracticeReading>(token, `/${encodeURIComponent(studentName)}/assessments/read`, {
  method: 'POST', body: JSON.stringify(body),
})

export const confirmPracticeReading = (token: string, studentName: string, id: number, assessment: GradedAssessment) =>
  practiceFetch<PracticeReading>(token, `/${encodeURIComponent(studentName)}/assessments/${id}`, {
    method: 'PUT', body: JSON.stringify({ assessment }),
  })

export const planPractice = (token: string, studentName: string, id: number) =>
  practiceFetch<PracticePlan>(token, `/${encodeURIComponent(studentName)}/assessments/${id}/plan`, { method: 'POST' })

export const approvePracticeSet = (token: string, studentName: string, setId: number, practiceSet?: PracticeSetDraft) =>
  practiceFetch<{ id: number; status: 'approved' }>(token, `/${encodeURIComponent(studentName)}/sets/${setId}/approve`, {
    method: 'POST', body: JSON.stringify({ practice_set: practiceSet ?? null }),
  })

export const discardPracticeSet = (token: string, studentName: string, setId: number) =>
  practiceFetch<{ id: number; status: 'discarded' }>(token, `/${encodeURIComponent(studentName)}/sets/${setId}/discard`, {
    method: 'POST',
  })
