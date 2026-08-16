/**
 * P9 device revocation (core/device_registry.py) — the client half.
 * getOrCreateDeviceId() must persist across calls (it identifies the
 * DEVICE, not one login) and degrade gracefully when localStorage is
 * unavailable rather than throwing and breaking login.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getOrCreateDeviceId } from './deviceId'

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('getOrCreateDeviceId', () => {
  it('generates a fresh id on first call', () => {
    const id = getOrCreateDeviceId()
    expect(id).toBeTruthy()
    expect(typeof id).toBe('string')
  })

  it('returns the SAME id on every subsequent call', () => {
    const first = getOrCreateDeviceId()
    const second = getOrCreateDeviceId()
    const third = getOrCreateDeviceId()
    expect(second).toBe(first)
    expect(third).toBe(first)
  })

  it('persists to localStorage, not sessionStorage — must survive a closed tab/browser restart', () => {
    const id = getOrCreateDeviceId()
    expect(localStorage.getItem('bede-device-id')).toBe(id)
    expect(sessionStorage.getItem('bede-device-id')).toBeNull()
  })

  it('reuses an id that was already stored (a fresh module load / new tab)', () => {
    localStorage.setItem('bede-device-id', 'pre-existing-id')
    expect(getOrCreateDeviceId()).toBe('pre-existing-id')
  })

  it('generates two different ids across two cleared storages', () => {
    const first = getOrCreateDeviceId()
    localStorage.clear()
    const second = getOrCreateDeviceId()
    expect(second).not.toBe(first)
  })

  it('returns null rather than throwing when localStorage.getItem throws (private browsing)', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError')
    })
    expect(() => getOrCreateDeviceId()).not.toThrow()
    expect(getOrCreateDeviceId()).toBeNull()
  })

  it('returns null rather than throwing when localStorage.setItem throws (quota exceeded)', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError')
    })
    expect(() => getOrCreateDeviceId()).not.toThrow()
    expect(getOrCreateDeviceId()).toBeNull()
  })
})
