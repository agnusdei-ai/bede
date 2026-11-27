import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, it, vi } from 'vitest'
import CurriculumAvailability from './CurriculumAvailability'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ i18n: { language: 'es' } }) }))
afterEach(cleanup)

it('uses the shared release and refreshes its operator state in Spanish', async () => {
  const release = (enabled: boolean) => ({
    contract_version: 1,
    grades: [{ grade: '8', default_route: 'catalog_guided' as const,
      accepted_full_year: { release_id: 'bede-grade8-2026-accepted', runtime_enabled: enabled } }],
  })
  const load = vi.fn().mockResolvedValueOnce(release(true)).mockResolvedValue(release(false))
  render(<CurriculumAvailability grade="8" load={load} />)
  await screen.findByText(/Año completo aceptado disponible/)
  fireEvent.focus(window)
  await screen.findByText(/no está activo en este entorno/)
})
