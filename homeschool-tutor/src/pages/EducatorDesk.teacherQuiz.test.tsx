import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Drives the real call site: EducatorDesk mounts the drafting tool and the
// teacher quiz tool, and a drafted quiz handed between them arrives with
// every answer marked as Bede's suggestion, unapproved.

const m = vi.hoisted(() => ({
  fetchInstructorRoster: vi.fn(),
  fetchInstructorFrameworks: vi.fn(),
  fetchInstructorDibelsProgress: vi.fn(),
  fetchInstructorActivity: vi.fn(),
  fetchMyEducatorPasskeys: vi.fn(),
  fetchEducatorQuizOptions: vi.fn(),
  generateEducatorQuiz: vi.fn(),
  approveTeacherQuiz: vi.fn(),
  fetchPracticeCoachEnabled: vi.fn(),
}))
vi.mock('../services/api', async (original) => ({
  ...await original<typeof import('../services/api')>(),
  ...m,
}))
vi.mock('../store/sessionStore', () => ({
  useSessionStore: () => ({ token: 'educator-token', setSessionConfig: vi.fn(), startSession: vi.fn(), logout: vi.fn() }),
}))
vi.mock('react-router', async (original) => ({
  ...await original<typeof import('react-router')>(),
  useNavigate: () => vi.fn(),
}))

import i18n from '../i18n'
import EducatorDesk from './EducatorDesk'
import { TeacherQuizProblems } from '../services/api'

beforeEach(async () => {
  vi.clearAllMocks()
  await i18n.changeLanguage('en')
  m.fetchInstructorRoster.mockResolvedValue([])
  m.fetchInstructorFrameworks.mockResolvedValue([])
  m.fetchMyEducatorPasskeys.mockResolvedValue([])
  m.fetchPracticeCoachEnabled.mockResolvedValue(true)
  m.fetchEducatorQuizOptions.mockResolvedValue({
    subjects: [{ id: 'history', display_name: 'History' }], grades: ['4'], kinds: ['quiz'], levels: ['on_level'],
    max_questions: 50, route: { local_available: true, cloud_provider: null, draft_provider: null },
  })
  m.generateEducatorQuiz.mockResolvedValue({
    report: { answers_recomputed: 0, dropped: 0, short_by: 0 },
    quiz: {
      title: 'Egypt', subject: 'history', grade: '4', kind: 'quiz', level: 'on_level', coverage: [], est_minutes: 2,
      questions: [{ number: 1, type: 'short_answer', topic: '', prompt: 'Which river flooded?', options: [], answer: 'Nile', answer_check: 'checked' }],
    },
  })
  m.approveTeacherQuiz.mockRejectedValue(new TeacherQuizProblems([{ number: 1, problem: 'key_not_approved' }], ''))
})
afterEach(() => cleanup())

describe('EducatorDesk teacher quizzes', () => {
  it('hands a drafted quiz to the teacher quiz tool as unapproved suggestions', async () => {
    render(<MemoryRouter><EducatorDesk /></MemoryRouter>)
    const builder = await screen.findByRole('region', { name: 'Make a quiz or exam' })
    fireEvent.click(within(builder).getByRole('button', { name: 'Start' }))
    fireEvent.change(await within(builder).findByLabelText('What to cover'), { target: { value: 'Egypt' } })
    fireEvent.click(within(builder).getByRole('button', { name: 'Draft quiz' }))
    fireEvent.click(await within(builder).findByRole('button', { name: "Edit the key and score students' work" }))

    const studio = screen.getByRole('region', { name: 'Your own quiz, with an answer key' })
    expect((await within(studio).findByTestId('source-1')).textContent).toBe('Suggested by Bede')
    fireEvent.click(within(studio).getByRole('button', { name: 'Check and approve the key' }))
    await waitFor(() => expect(m.approveTeacherQuiz).toHaveBeenCalledWith('educator-token', expect.objectContaining({
      questions: [expect.objectContaining({ answer: 'Nile', key_source: 'bede', key_approved: false })],
    })))
    expect(await within(studio).findByText(/This answer was not written by you/)).toBeTruthy()
  })
})
