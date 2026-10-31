import { describe, expect, it } from 'vitest'
import type { HouseholdConsent } from '../services/api'
import { noticeChanged, tickRequiredToSave } from './consent'

function consent(over: Partial<HouseholdConsent> = {}): HouseholdConsent {
  return {
    needs_consent: true,
    install_ack: false,
    notice_hash: 'h1',
    notice_version: '1',
    notice_text: 'text',
    students: [{ student_name: 'Ada', consented: false, stale: false }],
    ...over,
  }
}

describe('tickRequiredToSave', () => {
  it('requires the tick whenever consent is outstanding, with no exception', () => {
    expect(tickRequiredToSave(consent())).toBe(true)
  })
  it('allows a verified current or install-time acknowledgement', () => {
    expect(tickRequiredToSave(consent({ needs_consent: false, install_ack: true }))).toBe(false)
  })
  it('fails closed when the consent lookup is unavailable', () => {
    expect(tickRequiredToSave(null)).toBe(true)
    expect(tickRequiredToSave(null, ['Ada'])).toBe(true)
  })
  it('requires acknowledgement for the first pod when no child is configured', () => {
    expect(tickRequiredToSave(consent({ needs_consent: false, students: [] }), ['Ada'])).toBe(true)
  })
  it('does not carry consent from an existing child to a newly added child', () => {
    const household = consent({
      needs_consent: false,
      students: [{ student_name: 'Ada', consented: true, stale: false }],
    })
    expect(tickRequiredToSave(household, ['Ada'])).toBe(false)
    expect(tickRequiredToSave(household, ['Ada', 'Noah'])).toBe(true)
  })
  it('keeps the valid install acknowledgement for a newly configured child', () => {
    expect(tickRequiredToSave(consent({ needs_consent: false, install_ack: true, students: [] }), ['Ada'])).toBe(false)
  })
})

describe('noticeChanged', () => {
  it('is true only when a student agreed to an earlier version', () => {
    expect(noticeChanged(consent())).toBe(false)
    expect(noticeChanged(consent({ students: [{ student_name: 'Ada', consented: true, stale: true }] }))).toBe(true)
  })
})
