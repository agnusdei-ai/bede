import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { useSessionStore } from '../store/sessionStore'
import type { HouseholdConsent } from '../services/api'

const { fetchHouseholdConsent, grantHouseholdConsent } = vi.hoisted(() => ({
  fetchHouseholdConsent: vi.fn(),
  grantHouseholdConsent: vi.fn(),
}))

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return { ...actual, fetchHouseholdConsent, grantHouseholdConsent }
})

import { ConsentNoticeChangedError } from '../services/api'
import ConsentBanner from './ConsentBanner'

function consent(over: Partial<HouseholdConsent> = {}): HouseholdConsent {
  return {
    needs_consent: true,
    install_ack: false,
    notice_hash: 'hash-1',
    notice_version: '2026-10',
    notice_text: 'We keep lesson data on your own computer.',
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
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  sessionStorage.clear()
})

describe('ConsentBanner', () => {
  it('shows only when consent is needed', async () => {
    fetchHouseholdConsent.mockResolvedValue(consent())
    render(<ConsentBanner />)
    expect(await screen.findByRole('button', { name: 'I Consent' })).toBeTruthy()
  })

  it('renders nothing when no consent is needed', async () => {
    fetchHouseholdConsent.mockResolvedValue(consent({ needs_consent: false }))
    const { container } = render(<ConsentBanner />)
    await waitFor(() => expect(fetchHouseholdConsent).toHaveBeenCalled())
    expect(container.innerHTML).toBe('')
  })

  it('renders nothing for a child session and does not even ask the server', async () => {
    act(() => {
      useSessionStore.getState().logout()
      useSessionStore.getState().setAuth('child-token', 'child')
    })
    const { container } = render(<ConsentBanner />)
    expect(container.innerHTML).toBe('')
    expect(fetchHouseholdConsent).not.toHaveBeenCalled()
  })

  it('keeps Agree disabled until the box is ticked', async () => {
    fetchHouseholdConsent.mockResolvedValue(consent())
    render(<ConsentBanner />)
    const agree = (await screen.findByRole('button', { name: 'I Consent' })) as HTMLButtonElement
    expect(agree.disabled).toBe(true)
    fireEvent.click(screen.getByRole('checkbox'))
    expect(agree.disabled).toBe(false)
  })

  it('posts the current notice hash and refetches, then disappears', async () => {
    fetchHouseholdConsent.mockResolvedValueOnce(consent()).mockResolvedValue(consent({ needs_consent: false }))
    grantHouseholdConsent.mockResolvedValue({ granted: ['Ada'], already: [], refreshed: [] })
    const { container } = render(<ConsentBanner />)
    fireEvent.click(await screen.findByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'I Consent' }))
    await waitFor(() => expect(container.innerHTML).toBe(''))
    expect(grantHouseholdConsent).toHaveBeenCalledWith('parent-token', 'hash-1', 'parent')
    expect(fetchHouseholdConsent).toHaveBeenCalledTimes(2)
  })

  it('on 409 notice_changed refetches, shows the new notice and clears the tick', async () => {
    fetchHouseholdConsent
      .mockResolvedValueOnce(consent())
      .mockResolvedValue(consent({ notice_hash: 'hash-2', notice_text: 'Updated notice text.' }))
    grantHouseholdConsent.mockRejectedValue(new ConsentNoticeChangedError())
    render(<ConsentBanner />)
    fireEvent.click(await screen.findByRole('checkbox'))
    fireEvent.click(screen.getByRole('button', { name: 'I Consent' }))
    expect(await screen.findByText(/notice was just updated/i)).toBeTruthy()
    expect(fetchHouseholdConsent).toHaveBeenCalledTimes(2)
    expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false)
    expect(screen.getByText('Updated notice text.')).toBeTruthy()
  })

  it('renders nothing for a family that agreed at install time', async () => {
    fetchHouseholdConsent.mockResolvedValue(consent({ needs_consent: false, install_ack: true }))
    const { container } = render(<ConsentBanner />)
    await waitFor(() => expect(fetchHouseholdConsent).toHaveBeenCalled())
    expect(container.innerHTML).toBe('')
    expect(screen.queryByRole('checkbox')).toBeNull()
  })

  it('uses the formal checkbox wording, one tick for every child', async () => {
    fetchHouseholdConsent.mockResolvedValue(consent())
    render(<ConsentBanner />)
    expect(await screen.findByRole('checkbox', { name: /^I am the parent or legal guardian of each child who will use Bede\..*responsibilities of custodian set out in Section 2\.$/ })).toBeTruthy()
  })

  it('has no grace-period wording at all', async () => {
    fetchHouseholdConsent.mockResolvedValue(consent())
    render(<ConsentBanner />)
    await screen.findByRole('button', { name: 'I Consent' })
    expect(screen.queryByText(/keep working|more day/i)).toBeNull()
  })

  it('says plainly when the notice changed, versus first-time consent', async () => {
    fetchHouseholdConsent.mockResolvedValue(consent())
    const first = render(<ConsentBanner />)
    expect(await first.findByText('Parental Consent Required')).toBeTruthy()
    first.unmount()
    fetchHouseholdConsent.mockResolvedValue(
      consent({ students: [{ student_name: 'Ada', consented: true, stale: true }] }),
    )
    render(<ConsentBanner />)
    expect(await screen.findByText('Updated Notice: Renewed Consent Required')).toBeTruthy()
  })

  it('offers the notice text and version behind a disclosure', async () => {
    fetchHouseholdConsent.mockResolvedValue(consent())
    render(<ConsentBanner />)
    expect(await screen.findByText('Read the Notice')).toBeTruthy()
    expect(screen.getByText('We keep lesson data on your own computer.')).toBeTruthy()
    expect(screen.getByText('Notice version 2026-10')).toBeTruthy()
    expect(screen.getByRole('region', { name: 'Text of the Notice' })).toBeTruthy()
  })

  it('never writes consent state to browser storage', async () => {
    fetchHouseholdConsent.mockResolvedValue(consent())
    render(<ConsentBanner />)
    fireEvent.click(await screen.findByRole('checkbox'))
    expect(JSON.stringify(localStorage)).not.toMatch(/consent|hash-1/i)
  })
})
