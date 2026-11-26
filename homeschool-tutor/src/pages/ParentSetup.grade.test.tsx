import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import i18n from '../i18n'
import { useSessionStore } from '../store/sessionStore'

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return {
    ...actual,
    fetchHouseholdConsent: vi.fn().mockResolvedValue({
      needs_consent: false, install_ack: true, notice_hash: 'h', notice_version: '1', notice_text: '', students: [],
    }),
    fetchSystemStatus: vi.fn().mockResolvedValue({
      voice_profiles_enrolled: 0, student_names: [], locale: 'en', encryption: 'AES', key_storage: 'db',
      audit_log: 'on', usage: { estimated_cost_usd: 0 }, license: null,
    }),
    isFeedbackEnabled: vi.fn().mockResolvedValue(false),
    listPodConfigs: vi.fn().mockResolvedValue([]),
  }
})
vi.mock('../services/voiceApi', () => ({ listVoiceProfiles: vi.fn().mockResolvedValue([]) }))

import ParentSetup from './ParentSetup'

beforeEach(() => {
  i18n.changeLanguage('en')
  sessionStorage.clear()
  act(() => {
    useSessionStore.getState().logout()
    useSessionStore.getState().setAuth('parent-token', 'parent')
  })
})
afterEach(cleanup)

async function gradeSelect() {
  render(<MemoryRouter><ParentSetup /></MemoryRouter>)
  return (await screen.findByRole('combobox', { name: i18n.t('parentSetup.grade') })) as HTMLSelectElement
}

describe('ParentSetup grade selector', () => {
  it('does not add opt-in Grade8 subjects to a new family plan', async () => {
    await gradeSelect()
    for (const subject of ['spanish', 'computing', 'movement_health']) {
      expect(screen.queryByText(i18n.t(`subjects.${subject}`))).toBeNull()
    }
  })
  it('offers Kindergarten and grades 1-12 as choices, with no free text', async () => {
    const select = await gradeSelect()
    const values = Array.from(select.options).map((o) => o.value).filter(Boolean)
    expect(values).toEqual(['K', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12'])
  })

  it('moves the stage with the grade: 10 selects the top stage, K the first', async () => {
    const select = await gradeSelect()
    fireEvent.change(select, { target: { value: '10' } })
    expect(screen.getByText('6–12').closest('button')?.className).toContain('border-navy-500')
    fireEvent.change(select, { target: { value: 'K' } })
    expect(screen.getByText('K–2').closest('button')?.className).toContain('border-navy-500')
  })
})
