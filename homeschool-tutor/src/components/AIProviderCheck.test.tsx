/**
 * The parent's "Check AI providers" button: one press, one request to the
 * server, and a plain account of which providers answer and why the others
 * do not. A backup nobody has seen answer is not a backup (2026-11-17: the
 * demo's two backups could not answer and nothing showed it).
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { AIProviderCheckResult } from '../types'
import { ProviderCheck } from './AIProviderSettings'

const checkAIProviders = vi.hoisted(() => vi.fn())
vi.mock('../services/api', () => ({
  checkAIProviders,
  fetchAIProviderStatus: vi.fn(),
  setAIProvider: vi.fn(),
  setAIProviderSecondary: vi.fn(),
}))

afterEach(() => { cleanup(); checkAIProviders.mockReset() })

const ok = (provider: AIProviderCheckResult['provider']): AIProviderCheckResult =>
  ({ provider, ok: true, code: 'ok', message: 'Answering normally.', detail: '' })

describe('ProviderCheck', () => {
  it('names each provider that refuses, says why, and shows the provider’s own words', async () => {
    checkAIProviders.mockResolvedValue([
      ok('openai'),
      { provider: 'mistral', ok: false, code: 'rate_limited', message: 'Refusing because of a rate limit.', detail: 'Rate limit exceeded' },
      { provider: 'anthropic', ok: false, code: 'no_credit', message: 'Out of credit.', detail: 'Your credit balance is too low' },
    ])
    render(<ProviderCheck token="tok" />)
    fireEvent.click(screen.getByRole('button', { name: /Check AI providers/ }))

    const results = await screen.findByRole('status', { name: 'AI provider check results' })
    expect(checkAIProviders).toHaveBeenCalledOnce()
    expect(checkAIProviders).toHaveBeenCalledWith('tok')
    expect(results.textContent).toContain('Mistral AI')
    expect(results.textContent).toContain('Refusing because of a rate limit.')
    expect(results.textContent).toContain('The provider said: Your credit balance is too low')
    // Some answer, some do not: lessons work but the backup is not real.
    expect(results.textContent).toMatch(/nothing to\s+fall back to/)
  })

  it('says plainly when no provider answers', async () => {
    checkAIProviders.mockResolvedValue([
      { provider: 'openai', ok: false, code: 'no_credit', message: 'Out of credit.', detail: '' },
      { provider: 'mistral', ok: false, code: 'rate_limited', message: 'Rate limit.', detail: '' },
    ])
    render(<ProviderCheck token="tok" />)
    fireEvent.click(screen.getByRole('button', { name: /Check AI providers/ }))
    expect((await screen.findByRole('status', { name: 'AI provider check results' })).textContent)
      .toContain('No provider answered')
  })

  it('says so when every provider answers', async () => {
    checkAIProviders.mockResolvedValue([ok('openai'), ok('mistral')])
    render(<ProviderCheck token="tok" />)
    fireEvent.click(screen.getByRole('button', { name: /Check AI providers/ }))
    expect((await screen.findByRole('status', { name: 'AI provider check results' })).textContent)
      .toContain('Every provider answered')
  })

  it('shows the server’s own refusal, such as the half-minute limit', async () => {
    checkAIProviders.mockRejectedValue(new Error('Bede checked the providers moments ago.'))
    render(<ProviderCheck token="tok" />)
    fireEvent.click(screen.getByRole('button', { name: /Check AI providers/ }))
    expect((await screen.findByRole('alert')).textContent).toContain('moments ago')
  })

  it('says each check costs a little, before anyone presses it', () => {
    render(<ProviderCheck token="tok" />)
    expect(screen.getByText(/real request/)).toBeTruthy()
    expect(checkAIProviders).not.toHaveBeenCalled()
  })
})
