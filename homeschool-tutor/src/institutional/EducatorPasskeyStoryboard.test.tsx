import { describe, expect, it } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => cleanup())
import EducatorPasskeyStoryboard from './EducatorPasskeyStoryboard'

describe('educator passkey usability storyboard (mock only)', () => {
  it('starts with passwordless, school-affiliated invitation', () => {
    render(<EducatorPasskeyStoryboard />)
    expect(screen.getByText(/School-affiliated email is used for invitations/i)).toBeTruthy()
    expect(screen.queryByLabelText(/password/i)).toBeNull()
    expect(screen.getByText(/NO LIVE AUTHENTICATION/)).toBeTruthy()
  })
  it('allows other-device passkeys and cancel-retry without lockout', () => {
    render(<EducatorPasskeyStoryboard />)
    fireEvent.click(screen.getByRole('button', { name: /Continue to passkey setup/i }))
    const other = screen.getByRole('button', { name: /Another device or security key/i })
    fireEvent.click(other)
    expect(other.getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(screen.getByRole('button', { name: /^Continue/i }))
    fireEvent.click(screen.getByRole('button', { name: /I canceled/i }))
    expect(screen.getByText(/Prompt canceled. You can retry/i)).toBeTruthy()
    expect(screen.getByRole('button', { name: /Simulate browser prompt/i })).toBeTruthy()
  })
  it('explains supervised recovery rather than email-only login', () => {
    render(<EducatorPasskeyStoryboard />)
    fireEvent.click(screen.getByRole('button', { name: /Need help accessing your account/i }))
    expect(screen.getByText(/Email alone never unlocks your account/i)).toBeTruthy()
    expect(screen.getByText(/independently confirm your identity/i)).toBeTruthy()
  })
})
