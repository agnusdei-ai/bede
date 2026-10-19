import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PilotOfficialAssessmentForm from './PilotOfficialAssessmentForm'

const api = vi.hoisted(() => ({
  fetchOfficialAssessments: vi.fn(), fetchOfficialAssessment: vi.fn(),
  fetchOfficialDataDay: vi.fn(), createOfficialAssessment: vi.fn(),
  transitionOfficialAssessment: vi.fn(), enterOfficialScores: vi.fn(),
  recordOfficialObservation: vi.fn(), requestOfficialProposal: vi.fn(),
  decideOfficialProposal: vi.fn(), recordOfficialPlan: vi.fn(),
  fetchTeacherArtifact: vi.fn(), fetchTeacherFollowUps: vi.fn(), recordTeacherFollowUp: vi.fn(),
}))
vi.mock('../services/api', async (original) => ({
  ...await original<typeof import('../services/api')>(), ...api,
}))

const CID = '11111111-1111-4111-8111-111111111111'
const LID = '22222222-2222-4222-8222-222222222222'
const AID = '33333333-3333-4333-8333-333333333333'
const record = {
  assessment_id: AID, campus_id: CID, learner_id: LID,
  administrator_id: '44444444-4444-4444-8444-444444444444',
  instrument: 'dibels8', edition: '8', form_id: 'SYN-OFFICIAL-1',
  measure: 'PSF', grade: '1', administration_purpose: 'progress_monitoring',
  instructional_cycle: 'valor_q1', administered_at: '2026-10-17T12:00:00Z',
  report_source: 'manual_official_form', official_benchmark_window: 'none',
  state: 'IN_PROGRESS', snapshot_sha256: null, scores: [],
  finalized_at: null,
}
const packet = { proposed_next_steps: [], prior_teacher_decisions: [],
  boundaries: { changes_official_scores: false, starts_instruction: false, delivers_instruction: false } }

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchOfficialAssessments.mockResolvedValue([record])
  api.fetchOfficialAssessment.mockResolvedValue(record)
  api.fetchOfficialDataDay.mockResolvedValue(packet)
  api.enterOfficialScores.mockResolvedValue(record)
  api.recordOfficialObservation.mockResolvedValue({ evidence_id: 'synthetic' })
})
afterEach(cleanup)

function view() {
  return render(<PilotOfficialAssessmentForm token="synthetic-token" campusId={CID}
    learnerId={LID} learnerName="Synthetic Learner" />)
}

describe('pilot official assessment two-panel workflow', () => {
  it('separates the official record from teacher observation and links only authorized materials', async () => {
    view()
    expect(screen.getByText('1. Official assessment record')).toBeTruthy()
    expect(screen.getByText('2. Teacher observation and decision')).toBeTruthy()
    expect(screen.getByText(/Teacher delivers instruction/)).toBeTruthy()
    expect(screen.getByRole('link', { name: /authorized official DIBELS 8 materials/ })
      .getAttribute('href')).toBe('https://dibels.uoregon.edu/materials/dibels')
    await waitFor(() => expect(api.fetchOfficialAssessment).toHaveBeenCalledWith(
      'synthetic-token', CID, LID, AID))
  })

  it('shows an approved teacher artifact and separately records an after-teaching observation', async () => {
    const planId = '55555555-5555-4555-8555-555555555555'
    api.fetchOfficialAssessment.mockResolvedValue({ ...record, state: 'INSTRUCTIONAL_PLAN_READY', snapshot_sha256: 'a'.repeat(64) })
    api.fetchOfficialDataDay.mockResolvedValue({
      ...packet,
      prior_teacher_decisions: [{ assessment_id: AID, action: 'approve',
        outcome: { plan_recorded: true, plan_id: planId, delivery_state: 'NOT_REQUESTED' } }],
    })
    api.fetchTeacherArtifact.mockResolvedValue({
      artifact_type: 'teacher_use_instructional_plan',
      status: 'teacher_approved_for_offline_use',
      campus_id: CID, learner_id: LID, assessment_id: AID, plan_id: planId,
      approval_action: 'approve', plan_text: 'Synthetic teacher-approved handout',
      disclaimer: 'Teacher material, not an official report',
    })
    api.recordTeacherFollowUp.mockResolvedValue({ follow_up_id: 'synthetic-follow-up' })
    api.fetchTeacherFollowUps.mockResolvedValue([{ follow_up_id: 'synthetic-follow-up',
      observed_on: '2026-10-19', teaching_mode: 'in_person', observation: 'Synthetic teacher observation',
      next_step: null }])
    view()
    fireEvent.click(await screen.findByRole('button', { name: 'Prepare teacher-use artifact' }))
    expect(await screen.findByText('Synthetic teacher-approved handout')).toBeTruthy()
    expect(api.fetchTeacherArtifact).toHaveBeenCalledWith('synthetic-token', CID, LID, AID, planId)
    expect(screen.getByText(/not an official report/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('What you observed'), {
      target: { value: 'Synthetic teacher observation' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save teacher follow-up' }))
    await waitFor(() => expect(api.recordTeacherFollowUp).toHaveBeenCalled())
    const [token, campusId, learnerId, assessmentId, savedPlanId, body] = api.recordTeacherFollowUp.mock.calls[0]
    expect([token, campusId, learnerId, assessmentId, savedPlanId])
      .toEqual(['synthetic-token', CID, LID, AID, planId])
    expect(body.observation).toBe('Synthetic teacher observation')
    expect(body.teaching_mode).toBe('in_person')
    expect(await screen.findByText('Synthetic teacher observation')).toBeTruthy()
  })

  it('does not convert a skipped measure to a numeric zero', async () => {
    view()
    await screen.findByText(/Administration: in progress/)
    fireEvent.change(screen.getByLabelText('Measure administration status'),
      { target: { value: 'skipped' } })
    expect(screen.getByRole('button', { name: 'Save official measure result' })
      .hasAttribute('disabled')).toBe(true)
    fireEvent.change(screen.getByLabelText(/Reason \(required/),
      { target: { value: 'Not administered in synthetic session' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save official measure result' }))
    await waitFor(() => expect(api.enterOfficialScores).toHaveBeenCalled())
    const scores = api.enterOfficialScores.mock.calls[0][4]
    expect(scores[0].administration_status).toBe('skipped')
    expect(scores[0].raw_score).toBeNull()
    expect(scores[0].score_unit).toBeNull()
    expect(scores[0].reason).toContain('Not administered')
  })

  it('uses the configured campus and learner UUID, not display name, on record creation', async () => {
    api.fetchOfficialAssessments.mockResolvedValue([])
    api.createOfficialAssessment.mockResolvedValue(record)
    view()
    fireEvent.change(screen.getByLabelText('Official form identifier'),
      { target: { value: 'SYN-OFFICIAL-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create official record' }))
    await waitFor(() => expect(api.createOfficialAssessment).toHaveBeenCalled())
    const [token, campus, learner, body] = api.createOfficialAssessment.mock.calls[0]
    expect(token).toBe('synthetic-token')
    expect(campus).toBe(CID)
    expect(learner).toBe(LID)
    expect(body.form_id).toBe('SYN-OFFICIAL-1')
    expect(body.administration_purpose).toBe('progress_monitoring')
    expect(body.official_benchmark_window).toBe('none')
  })
})
