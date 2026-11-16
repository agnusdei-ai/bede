/**
 * The per-child K-2 practice setting (docs/K2_PRACTICE.md §4, decision
 * 40(a)): three choices, defaulting to "today's subjects too", Off one tap
 * away, shown only for a K-2 student, and saved with that child's config.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import i18n from '../i18n'
import en from '../i18n/locales/en.json'
import es from '../i18n/locales/es.json'
import { useSessionStore } from '../store/sessionStore'
import { DEFAULT_PRACTICE_OFFERS, PRACTICE_OFFERS } from '../types'

const m = vi.hoisted(() => ({ listPodConfigs: vi.fn(), savePodConfigs: vi.fn() }))

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return {
    ...actual,
    listPodConfigs: m.listPodConfigs,
    savePodConfigs: m.savePodConfigs,
    fetchChildPins: vi.fn().mockResolvedValue({}),
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

const base = { student_name: 'Sample Learner One', grade: '1', grade_stage: 'K-2', subjects: ['language_arts'] }

beforeEach(() => {
  i18n.changeLanguage('en')
  sessionStorage.clear()
  act(() => {
    useSessionStore.getState().logout()
    useSessionStore.getState().setAuth('parent-token', 'parent')
  })
  m.savePodConfigs.mockResolvedValue(undefined)
})
afterEach(() => { cleanup(); vi.clearAllMocks(); sessionStorage.clear() })

const radio = (key: string) => screen.getByRole('radio', { name: new RegExp(i18n.t(`parentSetup.practiceOffers_${key}`)) })

describe('ParentSetup K-2 practice setting', () => {
  it('defaults to Bede choosing from today’s subjects, the owner’s ruling', async () => {
    expect(DEFAULT_PRACTICE_OFFERS).toBe('todays_subjects')
    expect(PRACTICE_OFFERS).toEqual(['off', 'approved_only', 'todays_subjects'])
    m.listPodConfigs.mockResolvedValue([base])
    render(<MemoryRouter><ParentSetup /></MemoryRouter>)
    await screen.findByTestId('practice-offers')
    expect(radio('todays_subjects').getAttribute('aria-checked')).toBe('true')
  })

  it('round-trips: a saved choice loads back, and one tap to Off is what gets saved', async () => {
    m.listPodConfigs.mockResolvedValue([{ ...base, practice_offers: 'approved_only' }])
    render(<MemoryRouter><ParentSetup /></MemoryRouter>)
    await screen.findByTestId('practice-offers')
    expect(radio('approved_only').getAttribute('aria-checked')).toBe('true')
    fireEvent.click(radio('off'))
    expect(radio('off').getAttribute('aria-checked')).toBe('true')
    const boxes = screen.getAllByRole('checkbox')
    fireEvent.click(boxes[boxes.length - 1]) // the existing parent acknowledgement
    const save = screen.getByRole('button', { name: /begin|open/i }) as HTMLButtonElement
    await waitFor(() => expect(save.disabled).toBe(false))
    fireEvent.click(save)
    await waitFor(() => expect(m.savePodConfigs).toHaveBeenCalled())
    expect(m.savePodConfigs.mock.calls[0][1][0].practice_offers).toBe('off')
  })

  it('is not shown for a student past grade 2', async () => {
    m.listPodConfigs.mockResolvedValue([{ ...base, grade: '4', grade_stage: '3-5', subjects: ['history'] }])
    render(<MemoryRouter><ParentSetup /></MemoryRouter>)
    await screen.findByText(i18n.t('parentSetup.beginSession'))
    expect(screen.queryByTestId('practice-offers')).toBeNull()
  })

  it('has every label in both languages', () => {
    const keys = ['practiceOffersLabel', 'practiceOffersHelp',
      ...PRACTICE_OFFERS.flatMap((v) => [`practiceOffers_${v}`, `practiceOffers_${v}Help`])]
    for (const key of keys) {
      expect((en.parentSetup as Record<string, string>)[key], key).toBeTruthy()
      expect((es.parentSetup as Record<string, string>)[key], key).toBeTruthy()
    }
  })
})
