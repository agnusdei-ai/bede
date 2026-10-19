import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import LicenseSettings from './LicenseSettings'

const api = vi.hoisted(() => ({
  fetchLicenseStatus: vi.fn(),
  applyLicenseKey: vi.fn(),
}))
vi.mock('../services/api', async (original) => ({
  ...await original<typeof import('../services/api')>(),
  ...api,
}))

const expired = {
  tier: 'trial',
  licensee: 'Synthetic Pilot',
  seats: 25,
  unlimited_learners: false,
  location_id: null,
  expires: '2026-10-01',
  is_expired: true,
  days_remaining: -18,
  problem: 'Pilot expired; request a replacement code',
}

beforeEach(() => {
  vi.resetAllMocks()
  api.fetchLicenseStatus.mockResolvedValue(expired)
})
afterEach(() => cleanup())

async function openCard() {
  render(<LicenseSettings token="synthetic-parent-token" />)
  const header = await screen.findByRole('button', { name: /License/ })
  fireEvent.click(header)
  return header
}

describe('pilot license error and recovery journeys', () => {
  it('shows expired entitlement status instead of claiming the pilot is active', async () => {
    await openCard()
    expect(screen.getByText(/Expired 2026-10-01/)).toBeTruthy()
    expect(screen.getByText(/request a replacement code/)).toBeTruthy()
  })

  it('renders a human-readable invalid activation error and preserves the input', async () => {
    api.applyLicenseKey.mockRejectedValue(new Error('That license key is not valid: signature verification failed'))
    await openCard()
    fireEvent.change(screen.getByPlaceholderText('eyJ...'), { target: { value: 'invalid-synthetic-code' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    await screen.findByText(/signature verification failed/)
    expect(screen.getByPlaceholderText('eyJ...')).toHaveProperty('value', 'invalid-synthetic-code')
    expect(screen.queryByText('[object Object]')).toBeNull()
  })

  it('allows retry with a renewed mock entitlement and clears the prior error', async () => {
    api.applyLicenseKey.mockRejectedValueOnce(new Error('Activation code expired'))
      .mockResolvedValueOnce({ ...expired, is_expired: false, days_remaining: 40, expires: '2026-12-01', problem: null })
    await openCard()
    const input = screen.getByPlaceholderText('eyJ...')
    fireEvent.change(input, { target: { value: 'expired-synthetic' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    await screen.findByText('Activation code expired')
    fireEvent.change(input, { target: { value: 'renewed-synthetic' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    await screen.findByText(/License applied/)
    await waitFor(() => expect(screen.queryByText('Activation code expired')).toBeNull())
    expect(api.applyLicenseKey).toHaveBeenCalledWith('synthetic-parent-token', 'renewed-synthetic')
  })
})
