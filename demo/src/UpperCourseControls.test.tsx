import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import UpperCourseControls, { type UpperSelection } from './UpperCourseControls'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ i18n: { language: 'en' } }) }))
afterEach(cleanup)
const lessons = [{ id: 'g10-year-mathematics-w01', title: 'Week 1: Proof', subject: 'mathematics' },
  { id: 'g10-year-spanish-w01', title: 'Week 1: Saludos', subject: 'spanish' }]

function Harness({ load, initial = null, subjects = ['mathematics'], grade = '10' }: {
  load: (grade: string, week: number) => Promise<{ runtime_enabled: boolean; lessons: typeof lessons }>
  initial?: UpperSelection | null; subjects?: string[]; grade?: string
}) {
  const [value, setValue] = useState(initial)
  return <><UpperCourseControls grade={grade} value={value} subjects={subjects} onChange={setValue} load={load} />
    <output data-testid="choice">{JSON.stringify(value)}</output></>
}
const choice = () => JSON.parse(screen.getByTestId('choice').textContent!)

describe('adult-selected Grades 9-12 year', () => {
  it('loads the selected grade and week and labels Math plainly', async () => {
    const load = vi.fn().mockResolvedValue({ runtime_enabled: true, lessons })
    render(<Harness load={load} />)
    await waitFor(() => expect((screen.getByRole('checkbox') as HTMLInputElement).disabled).toBe(false))
    expect(load).toHaveBeenCalledWith('10', 1)
    fireEvent.click(screen.getByRole('checkbox'))
    expect(choice()).toMatchObject({ release_id: 'bede-upper-2026-reviewed', week: 1, lesson_id: null })
    expect(screen.getByRole('group', { name: 'Math' })).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Specific curriculum lesson'), { target: { value: 'g10-year-mathematics-w01' } })
    expect(choice()).toMatchObject({ lesson_id: 'g10-year-mathematics-w01' })
    fireEvent.change(screen.getByLabelText('Curriculum week'), { target: { value: '36' } })
    expect(choice()).toMatchObject({ week: 36, lesson_id: null })
    await waitFor(() => expect(load).toHaveBeenCalledWith('10', 36))
    expect(screen.getByText(/not human acceptance/)).toBeTruthy()
  })
  it('does not appear for other grades', () => {
    const load = vi.fn()
    render(<Harness grade="8" load={load} />)
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(load).not.toHaveBeenCalled()
  })
  it('cannot be switched on when the operator disabled the release', async () => {
    const load = vi.fn().mockResolvedValue({ runtime_enabled: false, lessons })
    render(<Harness load={load} />)
    await screen.findByText(/not active yet/)
    expect((screen.getByRole('checkbox') as HTMLInputElement).disabled).toBe(true)
    expect(choice()).toBeNull()
  })
})
