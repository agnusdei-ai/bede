import { afterEach, describe, expect, it, vi } from 'vitest'
import { deriveLocalDate, deriveTimeOfDay } from './api'

// Regression guard for the exact bug class local_date exists to fix: using
// toISOString() (UTC) instead of getFullYear/getMonth/getDate (local) would
// silently report the WRONG calendar date for any visitor west of UTC
// during these hours, defeating the whole point of sending a visitor-local
// date to the backend's weekly poetry/prayer rotation.
describe('deriveLocalDate', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('matches the YYYY-MM-DD shape', () => {
    expect(deriveLocalDate()).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('reflects the LOCAL date, not the UTC date, near a day boundary', () => {
    // 11:30pm local time — if the system's local offset is anything other
    // than UTC+0 this instant may already be tomorrow in UTC. toISOString()
    // would report that UTC date; deriveLocalDate must not.
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2027, 0, 15, 23, 30)) // local Jan 15, 2027, 11:30pm
    expect(deriveLocalDate()).toBe('2027-01-15')
  })

  it('zero-pads single-digit months and days', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2027, 2, 5, 9, 0)) // local Mar 5, 2027
    expect(deriveLocalDate()).toBe('2027-03-05')
  })
})

// Mirrors homeschool-tutor/src/store/sessionStore.ts's deriveTimeOfDay test
// coverage (that version had none before this — same gap, closed in both
// places at once) — 9am/12pm/5pm boundaries.
describe('deriveTimeOfDay', () => {
  it('buckets before noon as morning', () => {
    expect(deriveTimeOfDay(new Date(2027, 0, 15, 9, 0))).toBe('morning')
    expect(deriveTimeOfDay(new Date(2027, 0, 15, 11, 59))).toBe('morning')
  })

  it('buckets noon through 4:59pm as afternoon', () => {
    expect(deriveTimeOfDay(new Date(2027, 0, 15, 12, 0))).toBe('afternoon')
    expect(deriveTimeOfDay(new Date(2027, 0, 15, 16, 59))).toBe('afternoon')
  })

  it('buckets 5pm and later as evening', () => {
    expect(deriveTimeOfDay(new Date(2027, 0, 15, 17, 0))).toBe('evening')
    expect(deriveTimeOfDay(new Date(2027, 0, 15, 23, 30))).toBe('evening')
  })
})
