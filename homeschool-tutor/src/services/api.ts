import type { SessionConfig, Subject, ChatMessage, StreamChunk, NarrationAssessmentData, LearnerProfileData } from '../types'

const BASE = '/api'

// ── Auth ────────────────────────────────────────────────────────────────────

export async function login(role: 'parent' | 'child', credential: string): Promise<string> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role, credential }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Login failed')
  }
  const data = await res.json()
  return data.access_token
}

// ── Streaming tutor chat ─────────────────────────────────────────────────────

export async function* streamTutorChat(
  token: string,
  config: SessionConfig,
  subject: Subject,
  history: ChatMessage[],
  childMessage: string,
  signal?: AbortSignal
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
