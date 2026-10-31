import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ConsentNoticeChangedError,
  ParentalConsentRequiredError,
  grantHouseholdConsent,
  savePodConfigs,
  streamTutorChat,
} from './api'
import type { SessionConfig, Subject } from '../types'

const CONFIG = { student_name: 'Ada', grade: '4', subjects: [] } as unknown as SessionConfig

function json(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: async () => body } as unknown as Response
}

afterEach(() => vi.unstubAllGlobals())

describe('savePodConfigs consent hash', () => {
  it('sends consent_notice_hash only when one is given', async () => {
    const f = vi.fn().mockResolvedValue(json(200, {}))
    vi.stubGlobal('fetch', f)
    await savePodConfigs('t', [CONFIG])
    expect(JSON.parse(f.mock.calls[0][1].body)).toEqual({ configs: [CONFIG] })
    await savePodConfigs('t', [CONFIG], null)
    expect(JSON.parse(f.mock.calls[1][1].body)).toEqual({ configs: [CONFIG] })
    await savePodConfigs('t', [CONFIG], 'abc')
    expect(JSON.parse(f.mock.calls[2][1].body)).toEqual({ configs: [CONFIG], consent_notice_hash: 'abc' })
  })

  it('surfaces a stale notice as ConsentNoticeChangedError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(409, { detail: { error: 'notice_changed' } })))
    await expect(savePodConfigs('t', [CONFIG], 'abc')).rejects.toBeInstanceOf(ConsentNoticeChangedError)
  })
})

describe('grantHouseholdConsent', () => {
  it('posts the hash and label, and maps 409 notice_changed', async () => {
    const f = vi.fn().mockResolvedValue(json(201, { granted: ['Ada'], already: [], refreshed: [] }))
    vi.stubGlobal('fetch', f)
    await grantHouseholdConsent('t', 'h1', 'parent')
    expect(f.mock.calls[0][0]).toBe('/api/household/consent')
    expect(JSON.parse(f.mock.calls[0][1].body)).toEqual({ notice_hash: 'h1', parent_label: 'parent' })
    f.mockResolvedValue(json(409, { detail: { error: 'notice_changed' } }))
    await expect(grantHouseholdConsent('t', 'h1', 'parent')).rejects.toBeInstanceOf(ConsentNoticeChangedError)
  })
})

describe('tutor chat consent refusal', () => {
  it('raises ParentalConsentRequiredError, without retrying', async () => {
    const f = vi.fn().mockResolvedValue(
      json(403, { detail: { error: 'parental_consent_required', message: 'x', parent_action: 'open_parent_setup' } }),
    )
    vi.stubGlobal('fetch', f)
    const gen = streamTutorChat('t', CONFIG, 'mathematics' as Subject, [], 'hi')
    await expect(gen.next()).rejects.toBeInstanceOf(ParentalConsentRequiredError)
    expect(f).toHaveBeenCalledTimes(1)
  })
})
