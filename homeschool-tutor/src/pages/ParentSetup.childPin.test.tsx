/**
 * The per-child PIN control is actually mounted in Parent Setup's student
 * card (ChildPinSettings.test.tsx covers the control itself): offered for a
 * student the server already holds, with the parent's own token, and not
 * for a student who has not been saved yet.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import i18n from '../i18n'
import { useSessionStore } from '../store/sessionStore'

const m = vi.hoisted(() => ({
  listPodConfigs: vi.fn(),
  fetchChildPins: vi.fn(),
  setChildPin: vi.fn(),
}))

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return {
    ...actual,
    listPodConfigs: m.listPodConfigs,
    fetchChildPins: m.fetchChildPins,
    setChildPin: m.setChildPin,
    fetchHouseholdConsent: vi.fn().mockResolvedValue({
      needs_consent: false, install_ack: true, notice_hash: 'h', notice_version: '1', notice_text: '', students: [],
    }),
    fetchSystemStatus: vi.fn().mockResolvedValue({
      voice_profiles_enrolled: 0, student_names: [], locale: 'en', encryption: 'AES', key_storage: 'db',
      audit_log: 'on', usage: { estimated_cost_usd: 0 }, license: null,
    }),
    isFeedbackEnabled: vi.fn().mockResolvedValue(false),
  }
})
vi.mock('../services/voiceApi', () => ({ listVoiceProfiles: vi.fn().mockResolvedValue([]) }))

import ParentSetup from './ParentSetup'

const NAME = 'Synthetic Learner One'

beforeEach(() => {
  i18n.changeLanguage('en')
  sessionStorage.clear()
  act(() => {
    useSessionStore.getState().logout()
    useSessionStore.getState().setAuth('parent-token', 'parent')
  })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  sessionStorage.clear()
})

describe('ParentSetup per-child PIN', () => {
  it('offers a saved student their own PIN, using the parent token', async () => {
    m.listPodConfigs.mockResolvedValue([
      { student_name: NAME, grade: '3', grade_stage: '3-5', subjects: ['history'] },
    ])
    m.fetchChildPins.mockResolvedValue({})
    m.setChildPin.mockResolvedValue(undefined)
    render(<MemoryRouter><ParentSetup /></MemoryRouter>)
    fireEvent.click(await screen.findByText('Set a PIN for this child'))
    await waitFor(() => expect(m.fetchChildPins).toHaveBeenCalledWith('parent-token'))
    fireEvent.change(screen.getByLabelText('New PIN for this child'), { target: { value: '481937' } })
    fireEvent.click(screen.getByText('Save PIN'))
    await waitFor(() => expect(m.setChildPin).toHaveBeenCalledWith('parent-token', NAME, '481937'))
  })

  it('asks to save first for a student the server does not hold yet', async () => {
    m.listPodConfigs.mockResolvedValue([])
    render(<MemoryRouter><ParentSetup /></MemoryRouter>)
    fireEvent.change(await screen.findByPlaceholderText(i18n.t('parentSetup.namePlaceholder')), { target: { value: NAME } })
    expect(await screen.findByText(/Save this student first/)).toBeTruthy()
    expect(screen.queryByText('Set a PIN for this child')).toBeNull()
    expect(m.fetchChildPins).not.toHaveBeenCalled()
  })
})
