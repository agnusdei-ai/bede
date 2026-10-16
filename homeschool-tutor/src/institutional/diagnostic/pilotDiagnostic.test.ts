import { afterEach, expect, it, vi } from 'vitest'
import { getPilotDiagnostic } from './pilotDiagnostic'

const learner = '11111111-1111-4111-8111-111111111111'
afterEach(() => vi.unstubAllGlobals())

it('reads a source-only diagnostic view', async () => {
  const fetcher = vi.fn().mockResolvedValue({
    ok: true, status: 200,
    json: async () => ({ learner_id: learner, status: 'no_evidence',
      sources: [], has_more: false, message: 'No finalized evidence' }),
  })
  vi.stubGlobal('fetch', fetcher)
  const result = await getPilotDiagnostic('fixture', learner)
  expect(result.status).toBe('no_evidence')
  expect(fetcher).toHaveBeenCalledOnce()
})

it('refuses a response for another learner', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true, status: 200,
    json: async () => ({ learner_id: '22222222-2222-4222-8222-222222222222',
      status: 'no_evidence', sources: [], has_more: false, message: 'No evidence' }),
  }))
  await expect(getPilotDiagnostic('fixture', learner)).rejects.toThrow()
})
