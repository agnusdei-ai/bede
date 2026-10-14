import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { educatorPasskeyEnroll, webauthnSupported } = vi.hoisted(() => ({
  educatorPasskeyEnroll: vi.fn(),
  webauthnSupported: vi.fn(),
}))
vi.mock('../services/api', async original => ({
  ...await original<typeof import('../services/api')>(),
  educatorPasskeyEnroll,
}))
vi.mock('../services/webauthn', async original => ({
  ...await original<typeof import('../services/webauthn')>(),
  webauthnSupported,
}))
import EducatorEnroll from './EducatorEnroll'

const ticket = '12345678-1234-1234-1234-123456789abc'
const token = 'a'.repeat(43)
const renderPage = () => render(<MemoryRouter><EducatorEnroll /></MemoryRouter>)

beforeEach(() => {
  educatorPasskeyEnroll.mockReset()
  webauthnSupported.mockReturnValue(true)
  window.history.replaceState(null, '', '/educator-enroll')
})
afterEach(() => cleanup())

describe('school educator passkey invitation journey', () => {
  it('fails closed when the one-time school invitation is missing', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/missing or invalid/i))
    expect(screen.getByRole('button', { name: /Enroll passkey/i }).hasAttribute('disabled')).toBe(true)
  })

  it('keeps invitation tokens out of the visible URL and completes registration', async () => {
    window.history.replaceState(null, '', `/educator-enroll#ticket=${ticket}&token=${token}`)
    educatorPasskeyEnroll.mockResolvedValue(undefined)
    renderPage()
    await waitFor(() => expect(window.location.hash).toBe(''))
    fireEvent.click(screen.getByRole('button', { name: /Enroll passkey/i }))
    await waitFor(() => expect(educatorPasskeyEnroll).toHaveBeenCalledWith(ticket, token))
    expect(await screen.findByText(/Passkey enrolled successfully/i)).toBeTruthy()
  })

  it('allows retry after the user cancels the operating system prompt', async () => {
    window.history.replaceState(null, '', `/educator-enroll#ticket=${ticket}&token=${token}`)
    educatorPasskeyEnroll.mockRejectedValue(new DOMException('Canceled', 'NotAllowedError'))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Enroll passkey/i }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/canceled/i)
    expect(screen.getByRole('button', { name: /Enroll passkey/i }).hasAttribute('disabled')).toBe(false)
  })
})
