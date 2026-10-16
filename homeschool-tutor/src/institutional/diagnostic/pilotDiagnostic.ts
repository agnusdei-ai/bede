/**
 * Typed, fail-closed client for #616's read-only pilot diagnostic route.
 * This module has no authority to approve instruction or deliver tutoring.
 * Integration is deliberately deferred until G1/#613 and #616 are accepted.
 */
export interface PilotDiagnosticCitation {
  evidence_id: string
  assessment_id: string
  instrument: string
  measure: string
  grade: string
  administered_at: string
  administration_purpose: string
  snapshot_sha256: string
  recorded_at: string
}

export interface PilotDiagnosticView {
  learner_id: string
  status: 'no_evidence' | 'evidence_available'
  sources: PilotDiagnosticCitation[]
  has_more: boolean
  message: string
}

export type PilotDiagnosticFailure = 'sign_in' | 'unavailable' | 'changed' | 'offline'

export class PilotDiagnosticError extends Error {
  constructor(readonly reason: PilotDiagnosticFailure) {
    super(reason === 'sign_in' ? 'Sign in again to review evidence.'
      : reason === 'unavailable' ? 'This record is unavailable or you no longer have access.'
      : reason === 'changed' ? 'The evidence changed. Reload to review verified sources.'
      : 'Evidence is unavailable right now. Try again.')
    this.name = 'PilotDiagnosticError'
  }
}

const UUID4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
const SHA256 = /^[0-9a-f]{64}$/
const object = (x: unknown): x is Record<string, unknown> =>
  typeof x === 'object' && x !== null && !Array.isArray(x)

function citation(x: unknown): x is PilotDiagnosticCitation {
  if (!object(x)) return false
  return ['evidence_id', 'assessment_id', 'instrument', 'measure', 'grade',
    'administered_at', 'administration_purpose', 'snapshot_sha256', 'recorded_at']
    .every(key => typeof x[key] === 'string' && (x[key] as string).length > 0)
    && SHA256.test(x.snapshot_sha256 as string)
    && UUID4.test(x.evidence_id as string)
    && UUID4.test(x.assessment_id as string)
}

function parseView(data: unknown, learnerId: string, limit: number): PilotDiagnosticView {
  if (!object(data) || data.learner_id !== learnerId
      || (data.status !== 'no_evidence' && data.status !== 'evidence_available')
      || !Array.isArray(data.sources) || data.sources.length > limit
      || !data.sources.every(citation) || typeof data.has_more !== 'boolean'
      || typeof data.message !== 'string'
      || (data.status === 'no_evidence' && data.sources.length !== 0)
      || (data.status === 'evidence_available' && data.sources.length === 0)) {
    // A mismatched learner or malformed payload must never reach the UI.
    throw new PilotDiagnosticError('offline')
  }
  return data as unknown as PilotDiagnosticView
}

export async function getPilotDiagnostic(
  token: string, learnerId: string, signal?: AbortSignal, limit = 10,
): Promise<PilotDiagnosticView> {
  if (!UUID4.test(learnerId) || !Number.isInteger(limit) || limit < 1 || limit > 25 || !token) {
    throw new PilotDiagnosticError('unavailable')
  }
  let response: Response
  try {
    response = await fetch(
      `/api/pilot/me/learners/${encodeURIComponent(learnerId)}/diagnostic?limit=${limit}`,
      { method: 'GET', headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
        cache: 'no-store', credentials: 'same-origin', signal },
    )
  } catch (error) {
    if (signal?.aborted) throw error
    throw new PilotDiagnosticError('offline')
  }
  if (response.status === 401) throw new PilotDiagnosticError('sign_in')
  if (response.status === 403 || response.status === 404) throw new PilotDiagnosticError('unavailable')
  if (response.status === 409) throw new PilotDiagnosticError('changed')
  if (!response.ok) throw new PilotDiagnosticError('offline')
  let body: unknown
  try { body = await response.json() } catch { throw new PilotDiagnosticError('offline') }
  return parseView(body, learnerId, limit)
}
