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
  it('never blocks when nothing is outstanding or state is unknown', () => {
    expect(tickRequiredToSave(consent({ needs_consent: false, install_ack: true }))).toBe(false)
    expect(tickRequiredToSave(null)).toBe(false)
  })
})

describe('noticeChanged', () => {
  it('is true only when a student agreed to an earlier version', () => {
    expect(noticeChanged(consent())).toBe(false)
    expect(noticeChanged(consent({ students: [{ student_name: 'Ada', consented: true, stale: true }] }))).toBe(true)
  })
})
