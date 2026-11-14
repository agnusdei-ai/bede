/**
 * ParentGreetingSettings.tsx — the adult's optional greeting name. Optional,
 * editable, clearable; shown only as text; the server decides what it keeps.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { saveParentName, clearParentName } = vi.hoisted(() => ({
  saveParentName: vi.fn(),
  clearParentName: vi.fn(),
}))

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return { ...actual, saveParentName, clearParentName }
})

import i18n from '../i18n'
import ParentGreetingSettings from './ParentGreetingSettings'

beforeEach(() => {
  i18n.changeLanguage('en')
  saveParentName.mockReset()
  clearParentName.mockReset()
})
afterEach(cleanup)

describe('ParentGreetingSettings', () => {
  it('is optional: renders empty, with no name required and no Remove button', () => {
    render(<ParentGreetingSettings token="t" name={null} onChange={() => {}} />)
    expect((screen.getByLabelText(/What should Bede call you/) as HTMLInputElement).value).toBe('')
    expect(screen.queryByText('Remove my name')).toBeNull()
    expect(saveParentName).not.toHaveBeenCalled()
  })

  it('saves what the server kept, not what was typed', async () => {
    saveParentName.mockResolvedValue({ parent_display_name: 'Kristian' })
    const onChange = vi.fn()
    render(<ParentGreetingSettings token="t" name={null} onChange={onChange} />)
    fireEvent.change(screen.getByLabelText(/What should Bede call you/), { target: { value: '  Kristian <b> ' } })
    fireEvent.click(screen.getByText('Save'))
    await waitFor(() => expect(onChange).toHaveBeenCalledWith('Kristian'))
    expect(saveParentName).toHaveBeenCalledWith('t', '  Kristian <b> ')
    expect(screen.getByText('Saved.')).toBeTruthy()
  })

  it('an empty save clears it and says so', async () => {
    saveParentName.mockResolvedValue({ parent_display_name: null })
    const onChange = vi.fn()
    render(<ParentGreetingSettings token="t" name="Kristian" onChange={onChange} />)
    fireEvent.change(screen.getByLabelText(/What should Bede call you/), { target: { value: '' } })
    fireEvent.click(screen.getByText('Save'))
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(null))
    expect(screen.getByText('Your name is not set.')).toBeTruthy()
  })

  it('Remove my name clears it', async () => {
    clearParentName.mockResolvedValue({ parent_display_name: null })
    const onChange = vi.fn()
    render(<ParentGreetingSettings token="t" name="Kristian" onChange={onChange} />)
    fireEvent.click(screen.getByText('Remove my name'))
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(null))
    expect((screen.getByLabelText(/What should Bede call you/) as HTMLInputElement).value).toBe('')
  })

  it('a failed save says so and leaves the greeting as it was', async () => {
    saveParentName.mockRejectedValue(new Error('boom'))
    const onChange = vi.fn()
    render(<ParentGreetingSettings token="t" name="Kristian" onChange={onChange} />)
    fireEvent.click(screen.getByText('Save'))
    await waitFor(() => expect(screen.getByText('That did not save. Please try again.')).toBeTruthy())
    expect(onChange).not.toHaveBeenCalled()
  })

  it('renders a name as text, never as markup', () => {
    render(<ParentGreetingSettings token="t" name={'<img src=x onerror=alert(1)>'} onChange={() => {}} />)
    expect(document.querySelector('img')).toBeNull()
  })
})
