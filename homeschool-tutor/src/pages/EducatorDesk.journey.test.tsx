import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EducatorDesk from './EducatorDesk'

const { fetchInstructorRoster, fetchInstructorFrameworks,
  fetchInstructorDibelsProgress, fetchInstructorActivity, saveInstructorAssessment, setSessionConfig, startSession,
  navigate, logout } = vi.hoisted(() => ({
  fetchInstructorRoster: vi.fn(),
  fetchInstructorFrameworks: vi.fn(),
  fetchInstructorDibelsProgress: vi.fn(),
  fetchInstructorActivity: vi.fn(),
  saveInstructorAssessment: vi.fn(),
  setSessionConfig: vi.fn(),
  startSession: vi.fn(),
  navigate: vi.fn(),
  logout: vi.fn(),
}))

vi.mock('../services/api', async (original) => ({
  ...await original<typeof import('../services/api')>(),
  fetchInstructorRoster, fetchInstructorFrameworks,
  fetchInstructorDibelsProgress, fetchInstructorActivity, saveInstructorAssessment,
}))
vi.mock('../store/sessionStore', () => ({
  useSessionStore: () => ({
    token: 'sample-educator-token', setSessionConfig, startSession, logout,
  }),
}))
vi.mock('react-router', async (original) => ({
  ...await original<typeof import('react-router')>(),
  useNavigate: () => navigate,
}))

beforeEach(() => {
  vi.clearAllMocks()
  fetchInstructorRoster.mockResolvedValue([{
    student_name: 'Learner A', grade: '4', grade_stage: '3-5',
    subjects: ['mathematics', 'living_books'], current_unit: 'Fractions',
  }])
  fetchInstructorFrameworks.mockResolvedValue([])
  fetchInstructorDibelsProgress.mockResolvedValue({
    total_dibels_records: 0, records_excluded_from_comparison: 0, series: [],
  })
  fetchInstructorActivity.mockResolvedValue({ total: 0 })
})
afterEach(() => cleanup())

describe('authenticated educator-to-learner journey', () => {
  it('shows assigned roster then permits approved real tutor session', async () => {
    render(<MemoryRouter><EducatorDesk /></MemoryRouter>)
    await waitFor(() => expect(fetchInstructorRoster).toHaveBeenCalledWith('sample-educator-token'))
    expect(await screen.findByText(/Learner A — grade 4/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Plan a lesson/i }))
    expect(screen.getByRole('button', { name: /Begin guided lesson/i })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Begin guided lesson/i }))
    expect(startSession).toHaveBeenCalledOnce()
    expect(setSessionConfig).toHaveBeenCalledOnce()
    expect(navigate).toHaveBeenCalledWith('/session')
  })

  it('keeps external assessment reporting separate from the tutoring flow', async () => {
    render(<MemoryRouter><EducatorDesk /></MemoryRouter>)
    await waitFor(() => expect(fetchInstructorRoster).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: /See progress/i }))
    expect(screen.getByText(/do not establish that Bede caused a learning gain/i)).toBeTruthy()
    expect(screen.getByText(/Transcribe an independently administered assessment report/i)).toBeTruthy()
  })

  it('never carries a report grade from one learner to the next', async () => {
    fetchInstructorRoster.mockResolvedValue([
      { student_name: 'Learner A', grade: '4', grade_stage: '3-5', subjects: ['mathematics'] },
      { student_name: 'Learner B', grade: '10', grade_stage: '6-8', subjects: ['mathematics'] },
      { student_name: 'Learner C', grade: '2', grade_stage: '0-2', subjects: ['mathematics'] },
    ])
    fetchInstructorFrameworks.mockResolvedValue([{
      id: 'dibels8', supported_measures: ['ORF'], measure_units: { ORF: 'words_correct_per_minute' },
      grades: ['K', '1', '2', '3', '4', '5', '6', '7', '8'], windows: ['beginning'],
    }])
    render(<MemoryRouter><EducatorDesk /></MemoryRouter>)
    await waitFor(() => expect(fetchInstructorRoster).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: /See progress/i }))
    const grade = () => screen.getByTestId('dibels-report-grade') as HTMLSelectElement
    const learner = screen.getByLabelText(/Select learner/i)
    await waitFor(() => expect(grade().value).toBe('4'))

    // The teacher picks another grade for Learner A and starts typing a report.
    fireEvent.change(grade(), { target: { value: '6' } })
    fireEvent.change(screen.getByLabelText(/Reported numeric score/i), { target: { value: '88' } })

    // A grade 9-12 learner: nothing from Learner A survives, and the grade
    // is not one of the K-8 choices, so the teacher must choose it.
    fireEvent.change(learner, { target: { value: 'Learner B' } })
    await waitFor(() => expect(grade().value).toBe(''))
    expect(Array.from(grade().options).map((o) => o.value)).not.toContain('10')
    expect((screen.getByLabelText(/Reported numeric score/i) as HTMLInputElement).value).toBe('')
    expect(screen.getByTestId('dibels-grade-range').textContent)
      .toMatch(/kindergarten through grade 8.*Choose it before saving/)

    // Saving without choosing is refused and nothing is sent.
    fireEvent.change(screen.getByLabelText(/Reported numeric score/i), { target: { value: '70' } })
    fireEvent.change(screen.getByLabelText(/Source/i), { target: { value: 'Sample report' } })
    fireEvent.click(screen.getByRole('button', { name: /Record|Save/i }))
    expect(saveInstructorAssessment).not.toHaveBeenCalled()

    // Back to a K-8 learner: defaults to that learner's own grade.
    fireEvent.change(learner, { target: { value: 'Learner C' } })
    await waitFor(() => expect(grade().value).toBe('2'))
  })
})
