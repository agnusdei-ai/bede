import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { invitePasskeyInstructor, recoverPasskeyInstructor, fetchInstructors, fetchEducatorPilotMode } = vi.hoisted(() => ({
  invitePasskeyInstructor: vi.fn(),
  recoverPasskeyInstructor: vi.fn(),
  fetchInstructors: vi.fn(),
  fetchEducatorPilotMode: vi.fn(),
}))
vi.mock('../services/api', async original => ({
  ...await original<typeof import('../services/api')>(),
  invitePasskeyInstructor,
  recoverPasskeyInstructor,
  fetchInstructors,
  fetchEducatorPilotMode,
}))
import ClassroomSetup from './ClassroomSetup'
import { useSessionStore } from '../store/sessionStore'

const LINK = 'https://bede.sample.example/educator-enroll#ticket=12345678-1234-1234-1234-123456789abc&token=' + 'z'.repeat(43)

const fill = () => {
  fireEvent.change(screen.getByPlaceholderText('instructor.name'), { target: { value: 'sample.teacher' } })
  fireEvent.change(screen.getAllByPlaceholderText('teacher@school.example')[0],
    { target: { value: 'sample.teacher@school.example' } })
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
  useSessionStore.setState({ token: 'sample-admin-token' })
  window.localStorage.clear()
  window.sessionStorage.clear()
})
afterEach(() => cleanup())

describe('teacher invitation without outbound mail', () => {
  it('shows the one-time link once, with a copy button, and stores it nowhere', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    invitePasskeyInstructor.mockResolvedValue({
      sent: false, delivery: 'shown_to_admin', username: 'sample.teacher',
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
    invitePasskeyInstructor.mockResolvedValue({ sent: true, username: 'sample.teacher' })
    render(<MemoryRouter><ClassroomSetup /></MemoryRouter>)
    fill()
    await waitFor(() => expect(screen.getByRole('button', { name: /Send passkey invitation/ }).hasAttribute('disabled')).toBe(false))
    fireEvent.click(screen.getByRole('button', { name: /Send passkey invitation/ }))
    expect(await screen.findByText(/sent to the school mailbox for sample\.teacher/)).toBeTruthy()
    expect(screen.queryByLabelText('Enrollment link')).toBeNull()
  })
})

describe('lost-passkey recovery without outbound mail', () => {
  const TEACHER = { id: '87654321-4321-4321-4321-cba987654321', username: 'sample.teacher', enabled: true, learner_count: 0 }
  const issue = async () => {
    render(<MemoryRouter><ClassroomSetup /></MemoryRouter>)
    await screen.findByRole('option', { name: /sample\.teacher/ })
    fireEvent.change(screen.getAllByPlaceholderText('teacher@school.example')[1],
      { target: { value: 'sample.teacher@school.example' } })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Issue recovery link' }).hasAttribute('disabled')).toBe(false))
    fireEvent.click(screen.getByRole('button', { name: 'Issue recovery link' }))
  }

  it('shows the recovery link once for the selected teacher and stores it nowhere', async () => {
    fetchInstructors.mockResolvedValue([TEACHER])
    recoverPasskeyInstructor.mockReset()
    recoverPasskeyInstructor.mockResolvedValue({
      sent: false, delivery: 'shown_to_admin', enrollment_url: LINK, expires_in_minutes: 10,
    })
    await issue()
    const box = await screen.findByLabelText('Enrollment link') as HTMLInputElement
    expect(box.value).toBe(LINK)
    expect(recoverPasskeyInstructor).toHaveBeenCalledWith('sample-admin-token', TEACHER.id, 'sample.teacher@school.example')
    expect(screen.getByText(/Recovery link for sample\.teacher/)).toBeTruthy()
    expect(screen.getByText(/It works once and expires in 10 minutes\./)).toBeTruthy()
    expect(storageText()).not.toContain('educator-enroll')
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(document.body.textContent).not.toContain(LINK)
  })

  it('shows no link when recovery was emailed', async () => {
    fetchInstructors.mockResolvedValue([TEACHER])
    recoverPasskeyInstructor.mockReset()
    recoverPasskeyInstructor.mockResolvedValue({ sent: true })
    await issue()
    expect(await screen.findByText(/recovery link sent to the school mailbox/i)).toBeTruthy()
    expect(screen.queryByLabelText('Enrollment link')).toBeNull()
  })
})
