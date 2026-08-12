/**
 * AIProviderSettings.tsx — reliability gap this closes: before this, a
 * family running exactly one AI provider had no ongoing prompt to ever
 * add a backup, since this component rendered nothing at all with fewer
 * than two providers configured. Now it renders a lightweight nudge for
 * exactly one, the full switcher for two or more, and nothing only for
 * zero (a different, broken-deployment problem this card isn't about).
 */
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { fetchAIProviderStatus, setAIProvider, setAIProviderSecondary } = vi.hoisted(() => ({
  fetchAIProviderStatus: vi.fn(),
  setAIProvider: vi.fn(),
  setAIProviderSecondary: vi.fn(),
}))

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return { ...actual, fetchAIProviderStatus, setAIProvider, setAIProviderSecondary }
})

import AIProviderSettings from './AIProviderSettings'

function status(overrides: Partial<import('../types').AIProviderStatus> = {}) {
  return {
    known: ['local', 'anthropic', 'openai', 'mistral'],
    configured: [],
    env_order: [],
    effective_order: [],
    primary: null,
    secondary: null,
    override: null,
    secondary_override: null,
    forced: null,
    ...overrides,
  }
}

beforeEach(() => {
  fetchAIProviderStatus.mockReset()
  setAIProvider.mockReset()
  setAIProviderSecondary.mockReset()
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('AIProviderSettings — zero configured', () => {
  it('renders nothing when no provider is configured at all', async () => {
    fetchAIProviderStatus.mockResolvedValue(status({ configured: [] }))
    const { container } = render(<AIProviderSettings token="t" />)
    await waitFor(() => expect(fetchAIProviderStatus).toHaveBeenCalledWith('t'))
    await waitFor(() => expect(container.firstChild).toBeNull())
  })
})

describe('AIProviderSettings — exactly one configured', () => {
  it('renders a nudge naming the single configured provider, not the full switcher', async () => {
    fetchAIProviderStatus.mockResolvedValue(
      status({ configured: ['anthropic'], primary: 'anthropic', effective_order: ['anthropic'] }),
    )
    render(<AIProviderSettings token="t" />)

    await screen.findByText(/Anthropic \(Claude\)/)
    expect(screen.getByText(/Only one AI provider is configured/)).toBeTruthy()
    expect(screen.getByText(/PROVIDER_ADAPTERS\.md/)).toBeTruthy()
    // The full switcher's interactive elements must not be present — this
    // is a passive nudge, not a picker with nothing to pick between.
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('never calls the status-mutating endpoints for a single-provider deployment', async () => {
    fetchAIProviderStatus.mockResolvedValue(
      status({ configured: ['local'], primary: 'local', effective_order: ['local'] }),
    )
    render(<AIProviderSettings token="t" />)

    await screen.findByText(/Only one AI provider is configured/)
    expect(setAIProvider).not.toHaveBeenCalled()
    expect(setAIProviderSecondary).not.toHaveBeenCalled()
  })
})

describe('AIProviderSettings — two or more configured', () => {
  it('renders the full collapsible switcher, not the single-provider nudge', async () => {
    fetchAIProviderStatus.mockResolvedValue(
      status({
        configured: ['local', 'anthropic'],
        primary: 'local',
        effective_order: ['local', 'anthropic'],
      }),
    )
    render(<AIProviderSettings token="t" />)

    await screen.findByText('AI Provider')
    expect(screen.queryByText(/Only one AI provider is configured/)).toBeNull()
    // The collapsible header is present and clickable — the two-or-more path.
    expect(screen.getByRole('button')).toBeTruthy()
  })
})
