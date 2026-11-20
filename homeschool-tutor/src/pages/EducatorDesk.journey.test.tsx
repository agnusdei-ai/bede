import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EducatorDesk from './EducatorDesk'

const { fetchInstructorRoster, fetchInstructorFrameworks,
  fetchInstructorDibelsProgress, fetchInstructorActivity, setSessionConfig, startSession,
  navigate, logout } = vi.hoisted(() => ({
  fetchInstructorRoster: vi.fn(),
  fetchInstructorFrameworks: vi.fn(),
  fetchInstructorDibelsProgress: vi.fn(),
  fetchInstructorActivity: vi.fn(),
  setSessionConfig: vi.fn(),
  startSession: vi.fn(),
  navigate: vi.fn(),
  logout: vi.fn(),
}))

vi.mock('../services/api', async (original) => ({
  ...await original<typeof import('../services/api')>(),
  fetchInstructorRoster, fetchInstructorFrameworks,
  fetchInstructorDibelsProgress, fetchInstructorActivity,
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

  it('does not put a grade 9-12 learner into the K-8 DIBELS grade choice', async () => {
    fetchInstructorRoster.mockResolvedValue([{
      student_name: 'Learner B', grade: '10', grade_stage: '6-8', subjects: ['mathematics'],
    }])
    fetchInstructorFrameworks.mockResolvedValue([{
      id: 'dibels8', supported_measures: ['ORF'], measure_units: { ORF: 'words_correct_per_minute' },
      grades: ['K', '1', '2', '3', '4', '5', '6', '7', '8'], windows: ['beginning'],
    }])
    render(<MemoryRouter><EducatorDesk /></MemoryRouter>)
    await waitFor(() => expect(fetchInstructorRoster).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: /See progress/i }))
    expect(await screen.findByTestId('dibels-upper-school-note')).toBeTruthy()
    const select = screen.getByLabelText(/Assessed grade/i) as HTMLSelectElement
    expect(Array.from(select.options).map((o) => o.value)).not.toContain('10')
    expect(select.value).toBe('4')
  })
})
