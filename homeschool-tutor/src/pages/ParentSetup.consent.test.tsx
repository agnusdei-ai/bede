import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import i18n from '../i18n'
import { useSessionStore } from '../store/sessionStore'
import type { HouseholdConsent } from '../services/api'

const m = vi.hoisted(() => ({
  fetchHouseholdConsent: vi.fn(),
  savePodConfigs: vi.fn(),
  grantHouseholdConsent: vi.fn(),
}))

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return {
    ...actual,
    fetchHouseholdConsent: m.fetchHouseholdConsent,
    grantHouseholdConsent: m.grantHouseholdConsent,
    savePodConfigs: m.savePodConfigs,
    fetchSystemStatus: vi.fn().mockResolvedValue({
      voice_profiles_enrolled: 0, student_names: [], locale: 'en', encryption: 'AES', key_storage: 'db',
      audit_log: 'on', usage: { estimated_cost_usd: 0 }, license: null,
    }),
    isFeedbackEnabled: vi.fn().mockResolvedValue(false),
    listPodConfigs: vi.fn().mockResolvedValue([]),
  }
})
vi.mock('../services/voiceApi', () => ({ listVoiceProfiles: vi.fn().mockResolvedValue([]) }))

import { ConsentNoticeChangedError } from '../services/api'
import ParentSetup from './ParentSetup'

function consent(over: Partial<HouseholdConsent> = {}): HouseholdConsent {
  return {
    needs_consent: true,
    install_ack: false,
    notice_hash: 'hash-1',
    notice_version: '1',
    notice_text: 'Notice body.',
    students: [{ student_name: 'Ada', consented: false, stale: false }],
    ...over,
  }
}

beforeEach(() => {
  i18n.changeLanguage('en')
  sessionStorage.clear()
  act(() => {
    useSessionStore.getState().logout()
    useSessionStore.getState().setAuth('parent-token', 'parent')
  })
  m.savePodConfigs.mockResolvedValue(undefined)
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  sessionStorage.clear()
})

function consentBoxes() {
  return screen.queryAllByRole('checkbox', { name: /parent or legal guardian of each child/i })
}

async function fillForm() {
  render(<MemoryRouter><ParentSetup /></MemoryRouter>)
  fireEvent.change(await screen.findByPlaceholderText(i18n.t('parentSetup.namePlaceholder')), { target: { value: 'Ada' } })
  fireEvent.change(screen.getByPlaceholderText(i18n.t('parentSetup.gradePlaceholder')), { target: { value: '4' } })
  const others = screen.getAllByRole('checkbox').filter((b) => !consentBoxes().includes(b as HTMLInputElement))
  fireEvent.click(others[others.length - 1]) // the existing parent acknowledgement
}

const saveButton = () => screen.getByRole('button', { name: /begin|open/i }) as HTMLButtonElement

describe('ParentSetup consent', () => {
  it('shows neither banner nor checkbox when the family agreed at install time', async () => {
    m.fetchHouseholdConsent.mockResolvedValue(consent({ needs_consent: false, install_ack: true }))
    render(<MemoryRouter><ParentSetup /></MemoryRouter>)
    await waitFor(() => expect(m.fetchHouseholdConsent).toHaveBeenCalled())
    expect(consentBoxes()).toHaveLength(0)
    expect(screen.queryByRole('button', { name: 'I Consent' })).toBeNull()
  })

  it('does not block saving, nor send a hash, when nothing is outstanding', async () => {
    m.fetchHouseholdConsent.mockResolvedValue(consent({ needs_consent: false, install_ack: true }))
    await fillForm()
    await waitFor(() => expect(saveButton().disabled).toBe(false))
    fireEvent.click(saveButton())
    await waitFor(() => expect(m.savePodConfigs).toHaveBeenCalled())
    expect(m.savePodConfigs.mock.calls[0][2]).toBeNull()
  })

  it('requires the current notice when the first student is configured without an install ack', async () => {
    m.fetchHouseholdConsent.mockResolvedValue(consent({ needs_consent: false, students: [] }))
    await fillForm()
    await waitFor(() => expect(consentBoxes()).toHaveLength(2))
    expect(saveButton().disabled).toBe(true)
    fireEvent.click(consentBoxes()[1])
    await waitFor(() => expect(saveButton().disabled).toBe(false))
    fireEvent.click(saveButton())
    await waitFor(() => expect(m.savePodConfigs).toHaveBeenCalled())
    expect(m.savePodConfigs.mock.calls[0][2]).toBe('hash-1')
  })

  it('does not inherit an existing child\'s consent when adding another child', async () => {
    m.fetchHouseholdConsent.mockResolvedValue(consent({
      needs_consent: false,
      students: [{ student_name: 'Grace', consented: true, stale: false }],
    }))
    await fillForm() // Ada is new to the previously consented Grace household
    await waitFor(() => expect(consentBoxes()).toHaveLength(2))
    expect(saveButton().disabled).toBe(true)
  })

  it('does not save student configuration when the consent status request fails', async () => {
    m.fetchHouseholdConsent.mockRejectedValue(new Error('Consent status unavailable'))
    await fillForm()
    await waitFor(() => expect(m.fetchHouseholdConsent).toHaveBeenCalled())
    expect(consentBoxes()).toHaveLength(0)
    expect(saveButton().disabled).toBe(true)
    fireEvent.click(saveButton())
    expect(m.savePodConfigs).not.toHaveBeenCalled()
  })

  it('requires the tick before saving when consent is outstanding', async () => {
    m.fetchHouseholdConsent.mockResolvedValue(consent())
    await fillForm()
    await waitFor(() => expect(consentBoxes()).toHaveLength(2))
    expect(saveButton().disabled).toBe(true)
    expect(screen.getByText('Please tick the box above to save.')).toBeTruthy()
  })

  it('sends the current notice hash with the save once ticked', async () => {
    m.fetchHouseholdConsent.mockResolvedValue(consent())
    await fillForm()
    await waitFor(() => expect(consentBoxes()).toHaveLength(2))
    fireEvent.click(consentBoxes()[1]) // inline, directly above Save
    await waitFor(() => expect(saveButton().disabled).toBe(false))
    fireEvent.click(saveButton())
    await waitFor(() => expect(m.savePodConfigs).toHaveBeenCalled())
    expect(m.savePodConfigs.mock.calls[0][2]).toBe('hash-1')
  })

  it('on a notice change while saving, refetches, unticks and shows the new notice', async () => {
    m.fetchHouseholdConsent.mockResolvedValueOnce(consent())
      .mockResolvedValue(consent({ notice_hash: 'hash-2', notice_text: 'Newer notice.' }))
    m.savePodConfigs.mockRejectedValue(new ConsentNoticeChangedError())
    await fillForm()
    await waitFor(() => expect(consentBoxes()).toHaveLength(2))
    fireEvent.click(consentBoxes()[1])
    await waitFor(() => expect(saveButton().disabled).toBe(false))
    fireEvent.click(saveButton())
    expect(await screen.findByText(/notice was just updated/i)).toBeTruthy()
    expect(m.fetchHouseholdConsent).toHaveBeenCalledTimes(2)
    expect((consentBoxes()[1] as HTMLInputElement).checked).toBe(false)
    expect(saveButton().disabled).toBe(true)
  })
})
