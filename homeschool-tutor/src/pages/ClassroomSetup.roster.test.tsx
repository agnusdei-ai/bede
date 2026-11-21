import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { assignInstructorRoster, fetchInstructors, fetchEducatorPilotMode } = vi.hoisted(() => ({
  assignInstructorRoster: vi.fn(),
  fetchInstructors: vi.fn(),
  fetchEducatorPilotMode: vi.fn(),
}))
vi.mock('../services/api', async original => ({
  ...await original<typeof import('../services/api')>(),
  assignInstructorRoster, fetchInstructors, fetchEducatorPilotMode,
}))
import ClassroomSetup, { buildRoster, ROSTER_GRADES, type RosterRow } from './ClassroomSetup'
import { useSessionStore } from '../store/sessionStore'

const row = (id: number, name: string, grade: RosterRow['grade'], sex: RosterRow['sex'] = ''): RosterRow => ({ id, name, grade, sex })

describe('roster rows', () => {
  it('offers kindergarten through grade 12 and maps each to a stage', () => {
    expect([...ROSTER_GRADES]).toEqual(['K', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12'])
    const roster = buildRoster(ROSTER_GRADES.map((g, i) => row(i, `Learner ${i}`, g)))
    expect(roster.map(r => r.grade)).toEqual([...ROSTER_GRADES])
    expect(roster.map(r => r.grade_stage)).toEqual(
      ['K-2', 'K-2', 'K-2', '3-5', '3-5', '3-5', '6-8', '6-8', '6-8', '6-8', '6-8', '6-8', '6-8'])
  })

  it('refuses a row with no grade chosen, a blank name, or a duplicate', () => {
    expect(() => buildRoster([row(1, 'Sample Learner', '')])).toThrow(/choose a grade/)
    expect(() => buildRoster([row(1, '', '4')])).toThrow(/enter a name/)
    expect(() => buildRoster([row(1, 'Sample Learner', '4'), row(2, 'sample learner', '5')])).toThrow(/Duplicate/)
  })

  it('ignores a wholly empty extra row', () => {
    expect(buildRoster([row(1, 'Sample Learner', '9', 'F'), row(2, '', '')])).toHaveLength(1)
  })
})

describe('the roster screen', () => {
  beforeEach(() => {
    assignInstructorRoster.mockReset()
    fetchInstructors.mockResolvedValue([{ id: 'e1', username: 'sample.teacher', learner_count: 0, enabled: true }])
    fetchEducatorPilotMode.mockResolvedValue({ enabled: true })
    useSessionStore.setState({ token: 'sample-admin-token' })
  })
  afterEach(() => cleanup())

  it('has no free-text grade box: grade and sex are selectors, and a grade 11 learner saves', async () => {
    assignInstructorRoster.mockResolvedValue({ learner_count: 1, new_learner_count: 1, messaging: null })
    render(<MemoryRouter><ClassroomSetup /></MemoryRouter>)
    await waitFor(() => screen.getByLabelText('Learner 1 name'))
    expect(document.querySelector('textarea')).toBeNull()
    const grade = screen.getByLabelText('Learner 1 grade') as HTMLSelectElement
    expect(grade.tagName).toBe('SELECT')
    expect(Array.from(grade.options).map(o => o.value)).toEqual(['', ...ROSTER_GRADES])
    expect((screen.getByLabelText('Learner 1 sex (optional)') as HTMLSelectElement).tagName).toBe('SELECT')
    fireEvent.change(screen.getByLabelText('Learner 1 name'), { target: { value: 'Sample Learner' } })
    fireEvent.change(grade, { target: { value: '11' } })
    await waitFor(() => expect(screen.getByRole('button', { name: /Save authorized roster/ }).hasAttribute('disabled')).toBe(false))
    fireEvent.click(screen.getByRole('button', { name: /Save authorized roster/ }))
    await waitFor(() => expect(assignInstructorRoster).toHaveBeenCalled())
    const sent = assignInstructorRoster.mock.calls[0][2]
    expect(sent).toMatchObject([{ student_name: 'Sample Learner', grade: '11', grade_stage: '6-8' }])
  })

  it('adds and removes learner rows with buttons', async () => {
    render(<MemoryRouter><ClassroomSetup /></MemoryRouter>)
    await waitFor(() => screen.getByLabelText('Learner 1 name'))
    fireEvent.click(screen.getByRole('button', { name: 'Add a learner' }))
    expect(screen.getByLabelText('Learner 2 name')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Remove learner 2' }))
    expect(screen.queryByLabelText('Learner 2 name')).toBeNull()
  })
})
