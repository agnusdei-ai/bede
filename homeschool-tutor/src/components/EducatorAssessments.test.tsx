import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  fetchEducatorAssessments: vi.fn(),
  fetchAssessmentFrameworks: vi.fn(),
  saveEducatorAssessment: vi.fn(),
  removeEducatorAssessment: vi.fn(),
}))
vi.mock('../services/api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/api')>()
  return { ...original, ...mocks }
})

import i18n from '../i18n'
import EducatorAssessments from './EducatorAssessments'

const catalog = [
  {
    id: 'dibels8',
    label: 'DIBELS 8th Edition',
    supported_measures: ['ORF_WC', 'ORF_ACCURACY', 'COMPOSITE'],
    measure_units: { ORF_WC: 'correct_per_minute', ORF_ACCURACY: 'percent', COMPOSITE: 'points' },
    grades: ['K', '1', '4'],
    windows: ['beginning_of_year', 'middle_of_year', 'end_of_year', 'progress_monitoring'],
    reported_bands: [
      'not_reported', 'core_negligible_risk', 'core_minimal_risk',
      'strategic_some_risk', 'intensive_at_risk',
    ],
    administration: 'external_only',
    interpretation: 'educator_supplied_only',
  },
  {
    id: 'classical',
    supported_measures: ['oral_narration', 'composition'],
    administration: 'instructor_observation', interpretation: 'assistance_record_only',
  },
  {
    id: 'external_other', supported_measures: [],
    administration: 'external_only', interpretation: 'reported_score_only',
  },
]

beforeEach(() => {
  i18n.changeLanguage('en')
  mocks.fetchEducatorAssessments.mockResolvedValue([])
  mocks.fetchAssessmentFrameworks.mockResolvedValue(catalog)
  mocks.saveEducatorAssessment.mockResolvedValue({
    id: 1, student_name: 'Alex', record_status: 'educator_entered_unverified',
    quality_flags: [], measure: 'ORF_ACCURACY', framework: 'dibels8',
    assessed_grade: '4', assessment_window: 'middle_of_year',
    assessed_on: '2026-10-10', score: 95, score_unit: 'percent',
    reported_band: 'core_minimal_risk', source_name: 'Educator report',
  })
})

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
  i18n.changeLanguage('en')
})

describe('parent-entered DIBELS 8 report fidelity', () => {
  it('uses the backend measure catalog and sends grade/window/correct measure unit, not guessed norms', async () => {
    render(<EducatorAssessments token="parent-token" studentName="Alex" />)
    await waitFor(() => expect(mocks.fetchAssessmentFrameworks).toHaveBeenCalledWith('parent-token'))
    await waitFor(() => expect(screen.getByText('Add record')).toBeTruthy())
    fireEvent.click(screen.getByText('Add record'))

    const measure = screen.getByLabelText('Measure or observed work') as HTMLSelectElement
    expect([...measure.options].map((o) => o.value)).toEqual(['ORF_WC', 'ORF_ACCURACY', 'COMPOSITE'])
    fireEvent.change(measure, { target: { value: 'ORF_ACCURACY' } })
    fireEvent.change(screen.getByLabelText('Grade shown on assessment'), { target: { value: '4' } })
    fireEvent.change(screen.getByLabelText('Assessment window'), { target: { value: 'middle_of_year' } })
    fireEvent.change(screen.getByLabelText('Source or report'), { target: { value: 'Educator report' } })
    fireEvent.change(screen.getByLabelText('Score as reported'), { target: { value: '95' } })
    fireEvent.change(screen.getByLabelText('Benchmark classification as reported'), {
      target: { value: 'core_minimal_risk' },
    })
    fireEvent.click(screen.getByText('Save record'))
    await waitFor(() => expect(mocks.saveEducatorAssessment).toHaveBeenCalledTimes(1))
    expect(mocks.saveEducatorAssessment).toHaveBeenCalledWith(
      'parent-token', 'Alex',
      expect.objectContaining({
        framework: 'dibels8', measure: 'ORF_ACCURACY',
        assessed_grade: '4', assessment_window: 'middle_of_year',
        score: 95, score_unit: 'percent', reported_band: 'core_minimal_risk',
      }),
    )
    expect(screen.getByText(/Educator-entered; not independently verified/)).toBeTruthy()
  })

  it('does not save a DIBELS report until grade and test window are selected', async () => {
    render(<EducatorAssessments token="parent-token" studentName="Alex" />)
    await waitFor(() => expect(screen.getByText('Add record')).toBeTruthy())
    fireEvent.click(screen.getByText('Add record'))
    fireEvent.change(screen.getByLabelText('Source or report'), { target: { value: 'Report' } })
    fireEvent.change(screen.getByLabelText('Score as reported'), { target: { value: '91' } })
    fireEvent.click(screen.getByText('Save record'))
    expect(mocks.saveEducatorAssessment).not.toHaveBeenCalled()
  })

  it('preserves and visibly warns on older external evidence with incomplete provenance', async () => {
    mocks.fetchEducatorAssessments.mockResolvedValue([{
      id: 7, student_name: 'Alex', record_status: 'educator_entered_unverified',
      framework: 'dibels8', measure: 'ORF_WC', assessed_on: '2025-09-01',
      source_name: 'Older reading report', score: 80, score_unit: 'count',
      reported_band: 'below_benchmark', quality_flags: [
        'missing_assessed_grade', 'missing_assessment_window',
        'review_reported_unit', 'legacy_benchmark_label',
      ],
    }])
    render(<EducatorAssessments token="parent-token" studentName="Alex" />)
    await waitFor(() => expect(screen.getByText(/Older record needs source review/)).toBeTruthy())
    expect(screen.getByText(/Older reading report/)).toBeTruthy()
    expect(screen.getByText(/Below benchmark/)).toBeTruthy()
  })
})
