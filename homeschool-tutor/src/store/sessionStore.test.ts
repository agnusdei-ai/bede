import { describe, expect, it } from 'vitest'
import { deriveLocalDate, deriveTimeOfDay } from './sessionStore'

// Mirrors demo/src/api.test.ts's coverage of the same two functions (kept
// in sync by hand between the two apps) — see that file for the fuller
// rationale on why local vs. UTC derivation matters for each.
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

describe('deriveLocalDate', () => {
  it('matches the YYYY-MM-DD shape', () => {
    expect(deriveLocalDate(new Date())).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('reflects the LOCAL date, not the UTC date, near a day boundary', () => {
    // 11:30pm local time — if the system's local offset is anything other
    // than UTC+0 this instant may already be tomorrow in UTC. toISOString()
    // would report that UTC date; deriveLocalDate must not.
    expect(deriveLocalDate(new Date(2027, 0, 15, 23, 30))).toBe('2027-01-15')
  })

  it('zero-pads single-digit months and days', () => {
    expect(deriveLocalDate(new Date(2027, 2, 5, 9, 0))).toBe('2027-03-05')
  })
})
