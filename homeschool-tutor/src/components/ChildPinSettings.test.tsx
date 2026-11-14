/**
 * "Set a PIN for this child" (core/child_pin.py), as a parent sees it in
 * Parent Setup: set, change and remove go to the real API wrappers with the
 * right student, the PIN is never shown back, and an unsaved student is told
 * to save first instead of being offered a control the server would refuse.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { fetchChildPins, setChildPin, clearChildPin } = vi.hoisted(() => ({
  fetchChildPins: vi.fn(),
  setChildPin: vi.fn(),
  clearChildPin: vi.fn(),
}))

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return { ...actual, fetchChildPins, setChildPin, clearChildPin }
})

import i18n from '../i18n'
import ChildPinSettings from './ChildPinSettings'

const NAME = 'Sample Learner One'

beforeEach(() => {
  fetchChildPins.mockReset()
  setChildPin.mockReset()
  clearChildPin.mockReset()
})

afterEach(() => {
  cleanup()
  i18n.changeLanguage('en')
})

describe('ChildPinSettings', () => {
  it('asks the parent to save an unsaved student first', () => {
    render(<ChildPinSettings token="tok" studentName={NAME} saved={false} />)
    expect(screen.getByText(/Save this student first/)).toBeTruthy()
    expect(fetchChildPins).not.toHaveBeenCalled()
  })

  it('sets a PIN for this child and never shows it back', async () => {
    fetchChildPins.mockResolvedValueOnce({}).mockResolvedValueOnce({
      [NAME]: { has_pin: true, locked: false, changed_at: null },
    })
    setChildPin.mockResolvedValue(undefined)
    render(<ChildPinSettings token="tok" studentName={NAME} saved />)
    fireEvent.click(await screen.findByText('Set a PIN for this child'))
    fireEvent.change(screen.getByLabelText('New PIN for this child'), { target: { value: '48a1937' } })
    expect((screen.getByLabelText('New PIN for this child') as HTMLInputElement).value).toBe('481937')
    fireEvent.click(screen.getByText('Save PIN'))
    await waitFor(() => expect(setChildPin).toHaveBeenCalledWith('tok', NAME, '481937'))
    await screen.findByText('Has their own PIN')
    expect(document.body.textContent).not.toContain('481937')
  })

  it('shows the server’s reason when a PIN is refused', async () => {
    fetchChildPins.mockResolvedValue({})
    setChildPin.mockRejectedValue(new Error('Another child already uses that PIN. Each child needs their own.'))
    render(<ChildPinSettings token="tok" studentName={NAME} saved />)
    fireEvent.click(await screen.findByText('Set a PIN for this child'))
    fireEvent.change(screen.getByLabelText('New PIN for this child'), { target: { value: '730582' } })
    fireEvent.click(screen.getByText('Save PIN'))
    expect((await screen.findByRole('alert')).textContent).toMatch(/Each child needs their own/)
  })

  it('changes, removes, and reports a lock', async () => {
    fetchChildPins.mockResolvedValueOnce({ [NAME]: { has_pin: true, locked: true, changed_at: null } })
      .mockResolvedValue({})
    clearChildPin.mockResolvedValue(undefined)
    render(<ChildPinSettings token="tok" studentName={NAME} saved />)
    expect(await screen.findByText(/Locked after too many wrong tries/)).toBeTruthy()
    expect(screen.getByText('Change PIN')).toBeTruthy()
    fireEvent.click(screen.getByText('Remove PIN'))
    await waitFor(() => expect(clearChildPin).toHaveBeenCalledWith('tok', NAME))
    await screen.findByText('Signs in with the family PIN')
  })

  it('is localized in Spanish', async () => {
    i18n.changeLanguage('es')
    fetchChildPins.mockResolvedValue({})
    render(<ChildPinSettings token="tok" studentName={NAME} saved />)
    expect(await screen.findByText('Crear un PIN para este niño')).toBeTruthy()
  })
})
