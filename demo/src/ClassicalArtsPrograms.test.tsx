import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ClassicalArtsWorkshop from './ClassicalArtsWorkshop'
import { readClassicalSelection } from './ClassicalProgramPicker'
import type { ClassicalArtsCatalog, ClassicalArtsLesson, ClassicalArtsProgram } from './api'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ i18n: { language: 'en', resolvedLanguage: 'en' } }) }))
afterEach(cleanup)

function metadata(id: string): ClassicalArtsProgram {
  return { id: id as ClassicalArtsProgram['id'], label: `Test program ${id}`,
    description: 'Test metadata, not evidence of a publisher match.',
    schedule_note: 'Bede support weeks are not the school calendar.', coverage_note: 'Bounded test scope.',
    references: [] }
}
function catalog(program = 'bede'): ClassicalArtsCatalog {
  return { release_id: 'fixture', runtime_enabled: true, program: metadata(program), scope_note: 'Test scope.',
    units: [{ id: 'review-unit', title: 'Review unit', subjects: ['living_books'], min_grade: 8,
      weeks: 3, summary: 'Test unit.', content_note: 'Adult selection.' }] }
}
function token(week: number) { return (week === 1 ? 'a' : 'b').repeat(24) }
function lesson(week: number, program: string): ClassicalArtsLesson {
  return { release_id: 'fixture', unit_id: 'review-unit', title: 'Review unit', week,
    program: metadata(program), selection_token: token(week), objective: `Purpose ${week}`,
    source: { id: 'fixture', title: 'Original fixture', url: 'https://example.invalid/source',
      locator: 'Test lines', text: 'Original test text.', language: 'en', rights: 'original' },
    companion_sources: [], visual_previews: [], steps: [], assessments: [], rehearsal: [] }
}
const loadList = () => vi.fn(async (_grade: string, _locale: string, program: string) => catalog(program))
const loadLesson = () => vi.fn(async (_unit: string, _grade: string, week: number, _locale: string, _support: string, program: string) => lesson(week, program))
const useButton = () => screen.getByRole('button', { name: 'Use for tutoring' }) as HTMLButtonElement
const confirmation = () => screen.getByRole('checkbox', { name: /I checked the assigned reading/ }) as HTMLInputElement
const savedNote = (week: number, binding = token(week)) =>
  `Bede classical arts: review-unit; week=${week}; support=guided; program=valor; assignment=${binding}`

describe('program-aware adult source selection', () => {
  it('preserves legacy notes and rejects unknown program syntax', () => {
    expect(readClassicalSelection('Bede classical arts: review-unit; week=1; support=guided')?.program).toBe('bede')
    expect(readClassicalSelection(savedNote(2))?.assignment).toBe(token(2))
    expect(readClassicalSelection(savedNote(2).replace('program=valor', 'program=unknown'))).toBeNull()
  })

  it('requires exact current-source confirmation and includes it in the editable note', async () => {
    const onChooseUnit = vi.fn()
    const list = loadList(), load = loadLesson()
    render(<ClassicalArtsWorkshop grade="8" subjects={['living_books']} loadList={list}
      loadLesson={load} onChooseUnit={onChooseUnit} />)
    await screen.findByLabelText('Literature or arts unit')
    fireEvent.change(screen.getByLabelText('Curriculum program'), { target: { value: 'valor' } })
    fireEvent.change(await screen.findByLabelText('Literature or arts unit'), { target: { value: 'review-unit' } })
    await screen.findByText('Purpose 1')
    expect(list).toHaveBeenLastCalledWith('8', 'en', 'valor')
    expect(load).toHaveBeenLastCalledWith('review-unit', '8', 1, 'en', 'guided', 'valor')
    expect(useButton().disabled).toBe(true)
    expect(onChooseUnit).not.toHaveBeenCalled()
    fireEvent.click(confirmation())
    fireEvent.click(useButton())
    expect(onChooseUnit).toHaveBeenLastCalledWith(savedNote(1))
    fireEvent.change(screen.getByLabelText('Bede support week'), { target: { value: '2' } })
    await screen.findByText('Purpose 2')
    expect(confirmation().checked).toBe(false)
    expect(useButton().disabled).toBe(true)
    fireEvent.click(confirmation())
    fireEvent.click(useButton())
    expect(onChooseUnit).toHaveBeenLastCalledWith(savedNote(2))
  })

  it('restores a saved program, week and matching source binding without saving automatically', async () => {
    const onChooseUnit = vi.fn()
    render(<ClassicalArtsWorkshop grade="8" subjects={['living_books']} currentUnit={savedNote(2)}
      loadList={loadList()} loadLesson={loadLesson()} onChooseUnit={onChooseUnit} />)
    await screen.findByText('Purpose 2')
    expect((screen.getByLabelText('Curriculum program') as HTMLSelectElement).value).toBe('valor')
    expect((screen.getByLabelText('Bede support week') as HTMLSelectElement).value).toBe('2')
    expect(confirmation().checked).toBe(true)
    expect(onChooseUnit).not.toHaveBeenCalled()
    fireEvent.click(useButton())
    expect(onChooseUnit).toHaveBeenCalledExactlyOnceWith(savedNote(2))
  })

  it('does not reuse a saved confirmation for a different source version', async () => {
    render(<ClassicalArtsWorkshop grade="8" subjects={['living_books']} currentUnit={savedNote(2, 'c'.repeat(24))}
      loadList={loadList()} loadLesson={loadLesson()} onChooseUnit={vi.fn()} />)
    await screen.findByText('Purpose 2')
    expect(confirmation().checked).toBe(false)
    expect(useButton().disabled).toBe(true)
  })

  it('does not accept a late catalog from the previously selected program', async () => {
    let resolveOld!: (value: ClassicalArtsCatalog) => void
    const old = new Promise<ClassicalArtsCatalog>((resolve) => { resolveOld = resolve })
    const list = vi.fn((_grade: string, _locale: string, program: string) =>
      program === 'bede' ? old : Promise.resolve(catalog(program)))
    render(<ClassicalArtsWorkshop grade="8" subjects={['living_books']} loadList={list}
      loadLesson={loadLesson()} onChooseUnit={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Curriculum program'), { target: { value: 'valor' } })
    await screen.findByLabelText('Literature or arts unit')
    await act(async () => resolveOld(catalog('bede')))
    expect(screen.getByText('Test program valor.')).toBeTruthy()
    expect(screen.queryByText('Test program bede.')).toBeNull()
  })

  it('fails explicitly when an older server ignores program selection', async () => {
    const onChooseUnit = vi.fn(), load = loadLesson()
    render(<ClassicalArtsWorkshop grade="8" subjects={['living_books']} currentUnit={savedNote(1)}
      loadList={vi.fn().mockResolvedValue(catalog('bede'))} loadLesson={load} onChooseUnit={onChooseUnit} />)
    await screen.findByRole('alert')
    expect(screen.queryByLabelText('Literature or arts unit')).toBeNull()
    expect(load).not.toHaveBeenCalled()
    expect(onChooseUnit).not.toHaveBeenCalled()
  })
})
