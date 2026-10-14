import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EducatorDesk from './EducatorDesk'

const { fetchInstructorRoster, fetchInstructorFrameworks, fetchInstructorLocutoCapacity,
  fetchInstructorDibelsProgress, fetchInstructorActivity, setSessionConfig, startSession,
  navigate, logout } = vi.hoisted(() => ({
  fetchInstructorRoster: vi.fn(),
  fetchInstructorFrameworks: vi.fn(),
  fetchInstructorLocutoCapacity: vi.fn(),
  fetchInstructorDibelsProgress: vi.fn(),
  fetchInstructorActivity: vi.fn(),
  setSessionConfig: vi.fn(),
  startSession: vi.fn(),
  navigate: vi.fn(),
  logout: vi.fn(),
}))

vi.mock('../services/api', async (original) => ({
  ...await original<typeof import('../services/api')>(),
  fetchInstructorRoster, fetchInstructorFrameworks, fetchInstructorLocutoCapacity,
  fetchInstructorDibelsProgress, fetchInstructorActivity,
}))
vi.mock('../store/sessionStore', () => ({
  useSessionStore: () => ({
    token: 'synthetic-educator-token', setSessionConfig, startSession, logout,
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
  fetchInstructorLocutoCapacity.mockResolvedValue({
    integration_status: 'planning_only_not_connected',
    maximum_members: 10, groups: [],
  })
  fetchInstructorDibelsProgress.mockResolvedValue({
    total_dibels_records: 0, records_excluded_from_comparison: 0, series: [],
  })
  fetchInstructorActivity.mockResolvedValue({ total: 0 })
})
afterEach(() => cleanup())

describe('authenticated educator-to-learner journey', () => {
  it('shows assigned roster then permits approved real tutor session', async () => {
    render(<MemoryRouter><EducatorDesk /></MemoryRouter>)
    await waitFor(() => expect(fetchInstructorRoster).toHaveBeenCalledWith('synthetic-educator-token'))
    expect(await screen.findByText(/Learner A — grade 4/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Plan lesson/i }))
    expect(screen.getByRole('button', { name: /Begin guided lesson/i })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Begin guided lesson/i }))
    expect(startSession).toHaveBeenCalledOnce()
    expect(setSessionConfig).toHaveBeenCalledOnce()
    expect(navigate).toHaveBeenCalledWith('/session')
  })

  it('keeps external assessment reporting separate from the tutoring flow', async () => {
    render(<MemoryRouter><EducatorDesk /></MemoryRouter>)
    await waitFor(() => expect(fetchInstructorRoster).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: /Learning evidence/i }))
    expect(screen.getByText(/do not establish that Bede caused a learning gain/i)).toBeTruthy()
    expect(screen.getByText(/Transcribe an independently administered assessment report/i)).toBeTruthy()
  })
})
