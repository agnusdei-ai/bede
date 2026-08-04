/**
 * login()'s P9 device_id wiring (core/device_registry.py) — the real
 * function against a mocked global fetch (same approach as
 * useTextToSpeech.priority.test.ts/Sandbox.test.tsx), not a mocked
 * login() itself, since this file's whole point is proving what the real
 * implementation actually sends.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../utils/deviceId', () => ({ getOrCreateDeviceId: vi.fn() }))

import { getOrCreateDeviceId } from '../utils/deviceId'
import { login } from './api'

function jsonResponse(body: unknown, ok = true) {
  return { ok, json: async () => body } as Response
}

beforeEach(() => {
  vi.mocked(getOrCreateDeviceId).mockReset()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('login() sends device_id when available', () => {
  it('includes device_id in the request body when one exists', async () => {
    vi.mocked(getOrCreateDeviceId).mockReturnValue('dev-123')
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ access_token: 't', role: 'parent' }))
    vi.stubGlobal('fetch', fetchMock)

    await login('parent', 'password')

    const [, init] = fetchMock.mock.calls[0]
    const body = JSON.parse(init.body)
    expect(body.device_id).toBe('dev-123')
  })

  it('omits device_id entirely (not null) when localStorage was unavailable', async () => {
    vi.mocked(getOrCreateDeviceId).mockReturnValue(null)
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ access_token: 't', role: 'parent' }))
    vi.stubGlobal('fetch', fetchMock)

    await login('parent', 'password')

    const [, init] = fetchMock.mock.calls[0]
    const body = JSON.parse(init.body)
    expect('device_id' in body).toBe(false)
  })

  it('still sends locale alongside device_id when both are present', async () => {
    vi.mocked(getOrCreateDeviceId).mockReturnValue('dev-123')
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ access_token: 't', role: 'parent' }))
    vi.stubGlobal('fetch', fetchMock)

    await login('parent', 'password', 'es')

    const [, init] = fetchMock.mock.calls[0]
    const body = JSON.parse(init.body)
    expect(body).toEqual({ role: 'parent', credential: 'password', locale: 'es', device_id: 'dev-123' })
  })

  it('surfaces a device-revoked error message the same way any other login failure is surfaced', async () => {
    vi.mocked(getOrCreateDeviceId).mockReturnValue('dev-123')
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ detail: "This device's access was revoked — please contact the parent" }, false)
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(login('parent', 'password')).rejects.toThrow(/revoked/i)
  })
})
