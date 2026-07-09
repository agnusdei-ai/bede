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

export async function transcribeFallback(
  token: string,
  wavBlob: Blob,
  language = 'en'
): Promise<string> {
  const form = new FormData()
  form.append('audio', wavBlob, 'audio.wav')
  form.append('language', language)

  const res = await fetch(`${BASE}/voice/transcribe`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  })
  if (!res.ok) return ''
  const data = await res.json()
  return data.text ?? ''
}
