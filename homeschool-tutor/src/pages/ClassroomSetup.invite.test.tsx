import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { invitePasskeyInstructor, fetchInstructors, fetchEducatorPilotMode } = vi.hoisted(() => ({
  invitePasskeyInstructor: vi.fn(),
  fetchInstructors: vi.fn(),
  fetchEducatorPilotMode: vi.fn(),
}))
vi.mock('../services/api', async original => ({
  ...await original<typeof import('../services/api')>(),
  invitePasskeyInstructor,
  fetchInstructors,
  fetchEducatorPilotMode,
}))
import ClassroomSetup from './ClassroomSetup'
import { useSessionStore } from '../store/sessionStore'

const LINK = 'https://bede.synthetic.example/educator-enroll#ticket=12345678-1234-1234-1234-123456789abc&token=' + 'z'.repeat(43)

const fill = () => {
  fireEvent.change(screen.getByPlaceholderText('instructor.name'), { target: { value: 'synthetic.teacher' } })
  fireEvent.change(screen.getByPlaceholderText('teacher@school.example'),
    { target: { value: 'synthetic.teacher@school.example' } })
}

const storageText = () => {
  const all: string[] = []
  for (const store of [window.localStorage, window.sessionStorage]) {
    for (let i = 0; i < store.length; i++) {
      const key = store.key(i) as string
      all.push(key, store.getItem(key) ?? '')
    }
  }
  return all.join('\n')
}

beforeEach(() => {
  invitePasskeyInstructor.mockReset()
  fetchInstructors.mockResolvedValue([])
  fetchEducatorPilotMode.mockResolvedValue({ enabled: true })
  useSessionStore.setState({ token: 'synthetic-admin-token' })
  window.localStorage.clear()
  window.sessionStorage.clear()
})
afterEach(() => cleanup())

describe('teacher invitation without outbound mail', () => {
  it('shows the one-time link once, with a copy button, and stores it nowhere', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    invitePasskeyInstructor.mockResolvedValue({
      sent: false, delivery: 'shown_to_admin', username: 'synthetic.teacher',
      enrollment_url: LINK, expires_in_minutes: 10,
    })
    render(<MemoryRouter><ClassroomSetup /></MemoryRouter>)
    fill()
    await waitFor(() => expect(screen.getByRole('button', { name: /Send passkey invitation/ }).hasAttribute('disabled')).toBe(false))
    fireEvent.click(screen.getByRole('button', { name: /Send passkey invitation/ }))

    const box = await screen.findByLabelText('Enrollment link') as HTMLInputElement
    expect(box.value).toBe(LINK)
    expect(screen.getByText(/Email isn't set up on this computer\. Give this link to the teacher in person\. It works once and expires in 10 minutes\./)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Copy link/ }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(LINK))
    expect(await screen.findByRole('button', { name: /Copied/ })).toBeTruthy()
    expect(storageText()).not.toContain('token=')
    expect(storageText()).not.toContain('educator-enroll')

    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(screen.queryByLabelText('Enrollment link')).toBeNull()
    expect(document.body.textContent).not.toContain(LINK)
  })

  it('shows no link when the invitation was emailed', async () => {
    invitePasskeyInstructor.mockResolvedValue({ sent: true, username: 'synthetic.teacher' })
    render(<MemoryRouter><ClassroomSetup /></MemoryRouter>)
    fill()
    await waitFor(() => expect(screen.getByRole('button', { name: /Send passkey invitation/ }).hasAttribute('disabled')).toBe(false))
    fireEvent.click(screen.getByRole('button', { name: /Send passkey invitation/ }))
    expect(await screen.findByText(/sent to the school mailbox for synthetic\.teacher/)).toBeTruthy()
    expect(screen.queryByLabelText('Enrollment link')).toBeNull()
  })
})
