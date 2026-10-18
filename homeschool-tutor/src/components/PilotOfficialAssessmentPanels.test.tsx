import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PilotOfficialAssessmentPanels from './PilotOfficialAssessmentPanels'

const mocks = vi.hoisted(() => ({
  fetchPilotLearners: vi.fn(), fetchOfficialAssessments: vi.fn(),
  fetchOfficialAssessmentCalendar: vi.fn(),
  fetchOfficialAssessment: vi.fn(), fetchOfficialDataDay: vi.fn(),
  createOfficialAssessment: vi.fn(), updateOfficialMarks: vi.fn(),
  recordOfficialScores: vi.fn(), transitionOfficialAssessment: vi.fn(),
  recordOfficialEvidence: vi.fn(), requestOfficialProposal: vi.fn(),
  decideOfficialProposal: vi.fn(), recordOfficialPlan: vi.fn(),
  supersedeOfficialAssessment: vi.fn(),
}))
vi.mock('../services/api', async (original) => ({
  ...await original<typeof import('../services/api')>(),
  ...mocks,
}))

const campus = '11111111-1111-4111-8111-111111111111'
const learner = '22222222-2222-4222-8222-222222222222'
const record = (state = 'DRAFT') => ({
  assessment_id: '33333333-3333-4333-8333-333333333333',
  campus_id: campus, learner_id: learner, administrator_id: 'synthetic-teacher',
  instrument: 'dibels8', edition: '8th', measure: 'PSF', grade: '1',
  form_id: 'SYN-VALID', administration_purpose: 'progress_monitoring',
  instructional_cycle: 'valor_q1', administered_at: '2026-10-12T12:00:00+00:00',
  report_source: 'teacher_administered', official_benchmark_window: 'none',
  accommodations: [], notes: null, state,
  administration_log: null,
  finalized_at: state === 'FINALIZED' ? '2026-10-12T12:00:00+00:00' : null,
  snapshot_sha256: state === 'FINALIZED' ? 'a'.repeat(64) : null,
  scores: [],
})
const day = {
  cycle: { cycle_key: 'valor_q1', label: 'Valor Q1 Data Day', data_day_on: null },
  current_valid_results: [], prior_valid_results: [], cited_evidence: [],
  proposed_next_steps: [], prior_teacher_decisions: [],
  boundaries: { starts_instruction: false, delivers_instruction: false },
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.fetchPilotLearners.mockResolvedValue([{ learner_id: learner, campus_id: campus, display_name: 'Synthetic Learner' }])
  mocks.fetchOfficialAssessments.mockResolvedValue([])
  mocks.fetchOfficialDataDay.mockResolvedValue(day)
  mocks.fetchOfficialAssessmentCalendar.mockResolvedValue({ configured: true,
    cycles: [{ cycle_key: 'valor_q1', label: 'Valor Q1 Data Day', data_day_on: null }] })
  mocks.createOfficialAssessment.mockResolvedValue(record())
  mocks.fetchOfficialAssessment.mockResolvedValue(record())
  mocks.recordOfficialScores.mockResolvedValue(record('IN_PROGRESS'))
  mocks.recordOfficialEvidence.mockResolvedValue({ evidence_id: 'ev', observation: {} })
})
afterEach(() => cleanup())

describe('canonical official assessment and teacher observation', () => {
  it('presents two distinct panels and creates only a source-linked DIBELS metadata draft', async () => {
    render(<PilotOfficialAssessmentPanels token="synthetic-teacher-token" />)
    expect(await screen.findByRole('region', { name: 'Official assessment record' })).toBeTruthy()
    expect(screen.getByRole('region', { name: 'Teacher observation' })).toBeTruthy()
    expect(screen.queryByText('Teach this with Bede')).toBeNull()
    fireEvent.change(screen.getByLabelText('Official form identifier'), { target: { value: 'SYN-VALID' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create official record' }))
    await waitFor(() => expect(mocks.createOfficialAssessment).toHaveBeenCalledOnce())
    expect(mocks.createOfficialAssessment).toHaveBeenCalledWith(
      'synthetic-teacher-token', campus, learner,
      expect.objectContaining({
        instrument: 'dibels8', edition: '8th', measure: 'PSF',
        form_id: 'SYN-VALID', administration_purpose: 'progress_monitoring',
        official_benchmark_window: 'none',
      }),
    )
    const payload = mocks.createOfficialAssessment.mock.calls[0][3]
    expect(payload).not.toHaveProperty('items')
    expect(payload).not.toHaveProperty('passage')
    expect(payload).not.toHaveProperty('learner_session')
  })

  it('preserves skipped as a status without turning it into numeric zero', async () => {
    mocks.fetchOfficialAssessments.mockResolvedValue([record('IN_PROGRESS')])
    mocks.fetchOfficialAssessment.mockResolvedValue(record('IN_PROGRESS'))
    render(<PilotOfficialAssessmentPanels token="synthetic-teacher-token" />)
    expect(await screen.findByText(/Administration: in progress/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Measure status'), { target: { value: 'skipped' } })
    fireEvent.change(screen.getByLabelText('Reason no score exists'), { target: { value: 'Synthetic not administered' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save measure result' }))
    await waitFor(() => expect(mocks.recordOfficialScores).toHaveBeenCalledOnce())
    expect(mocks.recordOfficialScores).toHaveBeenCalledWith(
      'synthetic-teacher-token', campus, learner, record().assessment_id,
      [expect.objectContaining({
        measure: 'PSF', administration_status: 'skipped', reason: 'Synthetic not administered',
      })],
    )
    const score = mocks.recordOfficialScores.mock.calls[0][4][0]
    expect(score).not.toHaveProperty('raw_score')
    expect(score).not.toHaveProperty('correct_count')
  })

  it('records teacher interpretation separately and never creates learner delivery', async () => {
    mocks.fetchOfficialAssessments.mockResolvedValue([record('FINALIZED')])
    mocks.fetchOfficialAssessment.mockResolvedValue(record('FINALIZED'))
    render(<PilotOfficialAssessmentPanels token="synthetic-teacher-token" />)
    expect(await screen.findByText(/Teacher interpretation/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Teacher interpretation'), { target: { value: 'Synthetic teacher review' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save teacher observation' }))
    await waitFor(() => expect(mocks.recordOfficialEvidence).toHaveBeenCalledOnce())
    expect(mocks.recordOfficialEvidence).toHaveBeenCalledWith(
      'synthetic-teacher-token', campus, learner, record().assessment_id,
      expect.objectContaining({ teacher_interpretation: 'Synthetic teacher review' }),
      undefined,
    )
    expect(screen.getByText(/Delivery state: NOT_REQUESTED/)).toBeTruthy()
    expect(mocks.recordOfficialPlan).not.toHaveBeenCalled()
  })
})
