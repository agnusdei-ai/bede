import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import CurriculumAvailability from './CurriculumAvailability'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ i18n: { language: 'en' } }) }))
afterEach(cleanup)

const metadata = (enabled = true) => ({
  contract_version: 1,
  grades: [
    { grade: 'K', default_route: 'catalog_guided' as const, accepted_full_year: null },
    { grade: '8', default_route: 'catalog_guided' as const,
      accepted_full_year: { release_id: 'bede-grade8-2026-accepted', runtime_enabled: enabled } },
    { grade: '12', default_route: 'grade_specific_practice' as const, accepted_full_year: null },
  ],
})

it('changes grade without representing practice or catalogs as full authored years', async () => {
  const load = vi.fn().mockResolvedValue(metadata())
  const view = render(<CurriculumAvailability grade="K" load={load} />)
  await screen.findByText(/Catalog-guided instruction/)
  view.rerender(<CurriculumAvailability grade="8" load={load} />)
  expect(screen.getByText(/Accepted full year available/)).toBeTruthy()
  view.rerender(<CurriculumAvailability grade="12" load={load} />)
  expect(screen.getByText(/full year is not published yet/)).toBeTruthy()
})

it('refreshes an operator disable after focus without retaining a stale available label', async () => {
  const load = vi.fn().mockResolvedValueOnce(metadata()).mockResolvedValue(metadata(false))
  render(<CurriculumAvailability grade="8" load={load} />)
  await screen.findByText(/Accepted full year available/)
  fireEvent.focus(window)
  await screen.findByText(/not active in this runtime/)
  expect(screen.queryByText(/Accepted full year available/)).toBeNull()
})

it('does not retain a success label when a refresh fails', async () => {
  const load = vi.fn().mockResolvedValueOnce(metadata()).mockRejectedValue(new Error('Unavailable'))
  render(<CurriculumAvailability grade="8" load={load} />)
  await screen.findByText(/Accepted full year available/)
  fireEvent.focus(window)
  await screen.findByText(/could not be verified/)
})

it('rejects incompatible metadata and unknown grades explicitly', async () => {
  const load = vi.fn().mockResolvedValue({ ...metadata(), contract_version: 99 })
  const view = render(<CurriculumAvailability grade="8" load={load} />)
  await screen.findByText(/could not be verified/)
  load.mockResolvedValue(metadata())
  await act(async () => { fireEvent.focus(window) })
  view.rerender(<CurriculumAvailability grade="13" load={load} />)
  await waitFor(() => expect(screen.getByText(/could not be verified/)).toBeTruthy())
})
