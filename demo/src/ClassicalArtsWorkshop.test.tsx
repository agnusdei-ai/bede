import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ClassicalArtsWorkshop from './ClassicalArtsWorkshop'
import type { ClassicalArtsCatalog, ClassicalArtsLesson } from './api'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ i18n: { language: 'en', resolvedLanguage: 'en' } }) }))
afterEach(() => { cleanup(); vi.restoreAllMocks() })

const catalog: ClassicalArtsCatalog = {
  release_id: 'fixture', runtime_enabled: true, scope_note: 'Component fixture, not a literary quotation.',
  units: [{ id: 'review-unit', title: 'Review unit', subjects: ['living_books'], min_grade: 8,
    weeks: 3, summary: 'Bounded review fixture.', content_note: 'Adult choice.' }],
}
function lesson(week = 1): ClassicalArtsLesson {
  return {
    release_id: 'fixture', unit_id: 'review-unit', title: 'Review unit', week,
    objective: `Week ${week} purpose`, companion_sources: [], visual_previews: [],
    source: { id: 'fixture', title: 'Original test fixture', url: 'https://example.invalid/fixture',
      locator: 'Sample test dialogue', language: 'en', rights: 'original',
      text: 'First speech.\nPartner cue.\nSecond speech.' },
    steps: [{ label: 'Read', instruction: 'Read together.' }], assessments: [],
    rehearsal: [{ speaker: 'A', text: 'First speech.' }, { speaker: 'B', text: 'Partner cue.' },
      { speaker: 'A', text: 'Second speech.' }],
  }
}

describe('adult-directed classical arts rehearsal', () => {
  it('keeps repeated speeches, unique roles, reveal/retry and typed work local', async () => {
    const onChooseUnit = vi.fn()
    render(<ClassicalArtsWorkshop grade="8" subjects={['living_books']} onChooseUnit={onChooseUnit}
      loadList={vi.fn().mockResolvedValue(catalog)} loadLesson={vi.fn().mockResolvedValue(lesson())} />)
    fireEvent.change(await screen.findByLabelText('Literature or arts unit'), { target: { value: 'review-unit' } })
    await screen.findByText('Week 1 purpose')
    expect(onChooseUnit).not.toHaveBeenCalled()
    const role = screen.getByLabelText('Read as')
    expect(within(role).getAllByRole('option')).toHaveLength(2)
    const ownLines = screen.getByText('Your line — A').parentElement!
    expect(within(ownLines).queryByText('First speech.')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Reveal my line' }))
    expect(within(ownLines).getByText('First speech.')).toBeTruthy()
    expect(within(ownLines).getByText('Second speech.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Type a response' }))
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'A local thought' } })
    fireEvent.click(screen.getByRole('button', { name: 'Begin this rehearsal again' }))
    await screen.findByText('Week 1 purpose')
    const resetLines = screen.getByText('Your line — A').parentElement!
    expect(within(resetLines).queryByText('First speech.')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Reveal my line' }))
    fireEvent.click(screen.getByRole('button', { name: 'Type a response' }))
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('')
    fireEvent.click(screen.getByRole('button', { name: 'Use for tutoring' }))
    expect(onChooseUnit).toHaveBeenCalledExactlyOnceWith('Bede classical arts: review-unit; week=1; support=guided')
    vi.spyOn(window, 'print').mockImplementation(() => window.dispatchEvent(new Event('afterprint')))
    fireEvent.click(screen.getByRole('button', { name: 'Print this lesson' }))
    expect(document.body.className).not.toContain('classical-arts-printing')
  })

  it('does not enable tutoring merely because a review preview loaded', async () => {
    const onChooseUnit = vi.fn()
    render(<ClassicalArtsWorkshop grade="8" subjects={['living_books']} onChooseUnit={onChooseUnit}
      loadList={vi.fn().mockResolvedValue({ ...catalog, runtime_enabled: false })}
      loadLesson={vi.fn().mockResolvedValue(lesson())} />)
    fireEvent.change(await screen.findByLabelText('Literature or arts unit'), { target: { value: 'review-unit' } })
    await screen.findByText('Week 1 purpose')
    expect((screen.getByRole('button', { name: 'Use for tutoring' }) as HTMLButtonElement).disabled).toBe(true)
    expect(onChooseUnit).not.toHaveBeenCalled()
  })

  it('ignores a late lesson response after a newer week is selected', async () => {
    let resolveLate!: (value: ClassicalArtsLesson) => void
    const old = new Promise<ClassicalArtsLesson>((resolve) => { resolveLate = resolve })
    const loadLesson = vi.fn().mockImplementationOnce(() => old).mockResolvedValue(lesson(2))
    const onChooseUnit = vi.fn()
    render(<ClassicalArtsWorkshop grade="8" subjects={['living_books']} onChooseUnit={onChooseUnit}
      loadList={vi.fn().mockResolvedValue(catalog)} loadLesson={loadLesson} />)
    fireEvent.change(await screen.findByLabelText('Literature or arts unit'), { target: { value: 'review-unit' } })
    fireEvent.change(screen.getByLabelText('Week'), { target: { value: '2' } })
    await screen.findByText('Week 2 purpose')
    await act(async () => resolveLate(lesson(1)))
    expect(screen.queryByText('Week 1 purpose')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Use for tutoring' }))
    expect(onChooseUnit).toHaveBeenCalledExactlyOnceWith('Bede classical arts: review-unit; week=2; support=guided')
  })
})
