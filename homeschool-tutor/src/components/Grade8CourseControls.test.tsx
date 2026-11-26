import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import Grade8CourseControls, { type Grade8Selection } from './Grade8CourseControls'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ i18n: { language: 'en' } }) }))
afterEach(cleanup)
const lessons = [{ id: 'math', title: 'Mathematics focus', subject: 'mathematics' },
  { id: 'spanish', title: 'Spanish focus', subject: 'spanish' }]

function Harness({ load, initial = null, subjects = ['mathematics'], grade = '8' }: {
  load: (week: number, pathway: string) => Promise<{ runtime_enabled: boolean; lessons: typeof lessons }>
  initial?: Grade8Selection | null; subjects?: string[]; grade?: string
}) {
  const [value, setValue] = useState(initial)
  return <><Grade8CourseControls grade={grade} value={value} subjects={subjects} onChange={setValue} load={load} />
    <output data-testid="choice">{JSON.stringify(value)}</output></>
}
const choice = () => JSON.parse(screen.getByTestId('choice').textContent!)

describe('adult-selected Grade8 course', () => {
  it('keeps other grades unchanged', () => {
    const load = vi.fn()
    render(<Harness grade="9" load={load} />)
    expect(screen.queryByRole('checkbox')).toBeNull()
    expect(load).not.toHaveBeenCalled()
  })
  it('never lets publication switch on an operator-disabled release', async () => {
    const load = vi.fn().mockResolvedValue({ runtime_enabled: false, lessons })
    render(<Harness load={load} />)
    await screen.findByText(/This complete Grade 8 year is not active yet/)
    expect((screen.getByRole('checkbox') as HTMLInputElement).disabled).toBe(true)
    expect(choice()).toBeNull()
  })
  it('selects weeks and pathways explicitly, clearing stale lesson IDs', async () => {
    const load = vi.fn().mockResolvedValue({ runtime_enabled: true, lessons })
    render(<Harness load={load} initial={{ week: 24, pathway: 'algebra', lesson_id: 'math' }} />)
    await waitFor(() => expect((screen.getByLabelText('Curriculum week') as HTMLSelectElement).disabled).toBe(false))
    expect(choice().lesson_id).toBe('math')
    fireEvent.change(screen.getByLabelText('Curriculum week'), { target: { value: '25' } })
    expect(choice()).toEqual({ week: 25, pathway: 'algebra', lesson_id: null })
    await waitFor(() => expect(load).toHaveBeenCalledWith(25, 'algebra'))
    await waitFor(() => expect((screen.getByLabelText('Mathematics pathway') as HTMLSelectElement).disabled).toBe(false))
    fireEvent.change(screen.getByLabelText('Mathematics pathway'), { target: { value: 'foundations' } })
    expect(choice().pathway).toBe('foundations')
    expect(choice().lesson_id).toBeNull()
  })
  it('preserves saved choices when metadata cannot load', async () => {
    const load = vi.fn().mockRejectedValue(new Error('offline'))
    render(<Harness load={load} initial={{ week: 36, pathway: 'algebra', lesson_id: 'math' }} />)
    await screen.findByRole('alert')
    expect(choice()).toEqual({ week: 36, pathway: 'algebra', lesson_id: 'math' })
    fireEvent.click(screen.getByRole('checkbox'))
    expect(choice()).toBeNull()
  })
  it('removes the specific lesson when its subject is removed', async () => {
    const load = vi.fn().mockResolvedValue({ runtime_enabled: true, lessons })
    const initial = { week: 1, pathway: 'foundations' as const, lesson_id: 'spanish' }
    const view = render(<Harness load={load} initial={initial} subjects={['mathematics', 'spanish']} />)
    await waitFor(() => expect((screen.getByLabelText('Specific curriculum lesson') as HTMLSelectElement).disabled).toBe(false))
    view.rerender(<Harness load={load} initial={initial} subjects={['mathematics']} />)
    await waitFor(() => expect(choice().lesson_id).toBeNull())
    expect(choice().week).toBe(1)
  })
})
