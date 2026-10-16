import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PilotTeacherJourney from './PilotTeacherJourney'

const api = vi.hoisted(() => ({
  fetchPilotLearners: vi.fn(),
  fetchInstructorFrameworks: vi.fn(),
  fetchPilotEvidence: vi.fn(),
  fetchPilotRecommendations: vi.fn(),
  fetchPilotLedger: vi.fn(),
  recordPilotEvidence: vi.fn(),
  requestPilotRecommendation: vi.fn(),
  decidePilotRecommendation: vi.fn(),
}))
vi.mock('../services/api', async (original) => ({
  ...await original<typeof import('../services/api')>(),
  ...api,
}))

// Synthetic, canonical UUIDv4-shaped ids. Two learners share a display name
// on purpose: the component must key on the id, never the name.
const A = '11111111-1111-4111-8111-111111111111'
const B = '22222222-2222-4222-8222-222222222222'
const EV = '33333333-3333-4333-8333-333333333333'
const REC = '44444444-4444-4444-8444-444444444444'

const evidence = [{
  evidence_id: EV, recorded_at: '2026-10-10T00:00:00Z', framework: 'dibels8',
  measure: 'PSF', assessed_on: '2026-10-09', source_name: 'Synthetic report',
  reported_band: 'strategic_some_risk',
}]
const pendingRec = {
  recommendation_id: REC, learner_id: A, status: 'pending', version: 1,
  policy_version: 'pilot-recommender/1', source_evidence_ids: [EV],
  proposal: 'Suggested focus for the next lessons: phoneme segmentation practice.',
  rationale: ["PSF (2026-10-09): the source report lists 'strategic_some_risk'."],
  authorized_instruction: null, created_at: '2026-10-10T00:00:00Z', decided_at: null,
}

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchPilotLearners.mockResolvedValue([
    { learner_id: A, campus_id: 'c-a', display_name: 'Example Learner' },
    { learner_id: B, campus_id: 'c-a', display_name: 'Example Learner' },
  ])
  api.fetchInstructorFrameworks.mockResolvedValue([])
  api.fetchPilotEvidence.mockResolvedValue(evidence)
  api.fetchPilotRecommendations.mockResolvedValue([pendingRec])
  api.fetchPilotLedger.mockResolvedValue({ chain_valid: true, entries: [] })
})
afterEach(cleanup)

describe('PilotTeacherJourney', () => {
  it('renders nothing when the educator has no pilot learners', async () => {
    api.fetchPilotLearners.mockResolvedValue([])
    const { container } = render(<PilotTeacherJourney token="t"/>)
    await waitFor(() => expect(api.fetchPilotLearners).toHaveBeenCalled())
    expect(container.innerHTML).toBe('')
  })

  it('renders nothing when the pilot is disabled (request refused)', async () => {
    api.fetchPilotLearners.mockRejectedValue(new Error('Institutional pilot is disabled'))
    const { container } = render(<PilotTeacherJourney token="t"/>)
    await waitFor(() => expect(api.fetchPilotLearners).toHaveBeenCalled())
    expect(container.innerHTML).toBe('')
  })

  it('loads the learner by immutable id, not display name', async () => {
    render(<PilotTeacherJourney token="t"/>)
    await screen.findByText(/Draft, awaiting your decision/)
    expect(api.fetchPilotEvidence).toHaveBeenLastCalledWith('t', A)
    fireEvent.change(screen.getByLabelText('Assigned learner'), { target: { value: B } })
    await waitFor(() => expect(api.fetchPilotEvidence).toHaveBeenLastCalledWith('t', B))
  })

  it('shows the draft as a draft, with the evidence it cites, and no instruction yet', async () => {
    render(<PilotTeacherJourney token="t"/>)
    expect(await screen.findByText(pendingRec.proposal)).toBeTruthy()
    expect(screen.getByText(/PSF · 2026-10-09 · strategic some risk/)).toBeTruthy()
    expect(screen.getByText('No instruction authorized yet.')).toBeTruthy()
  })

  it('approve sends the version it was shown, and the authorized instruction appears', async () => {
    render(<PilotTeacherJourney token="t"/>)
    await screen.findByText(pendingRec.proposal)
    const approved = { ...pendingRec, status: 'approved', version: 2,
      authorized_instruction: pendingRec.proposal, decided_at: '2026-10-11T00:00:00Z' }
    api.decidePilotRecommendation.mockResolvedValue(approved)
    api.fetchPilotRecommendations.mockResolvedValue([approved])
    api.fetchPilotLedger.mockResolvedValue({ chain_valid: true,
      entries: [{ seq: 1, action: 'approve', educator_id: 'e', created_at: '', note: null }] })
    fireEvent.click(screen.getByRole('button', { name: /Approve/ }))
    await waitFor(() => expect(api.decidePilotRecommendation).toHaveBeenCalledWith(
      't', A, REC, { action: 'approve', expected_version: 1 }))
    expect(await screen.findByText(/1 decision · integrity verified/)).toBeTruthy()
    expect(screen.queryByText(/Draft, awaiting your decision/)).toBeNull()
  })

  it('edit sends the teacher text and a note', async () => {
    render(<PilotTeacherJourney token="t"/>)
    await screen.findByText(pendingRec.proposal)
    fireEvent.click(screen.getByRole('button', { name: /Edit/ }))
    fireEvent.change(screen.getByLabelText('Your instruction'), { target: { value: 'Ten minutes with picture cards.' } })
    fireEvent.change(screen.getByLabelText(/Note for the audit trail/), { target: { value: 'Matches our scope' } })
    api.decidePilotRecommendation.mockResolvedValue({ ...pendingRec, status: 'edited' })
    fireEvent.click(screen.getByRole('button', { name: 'Save edited instruction' }))
    await waitFor(() => expect(api.decidePilotRecommendation).toHaveBeenCalledWith('t', A, REC, {
      action: 'edit', expected_version: 1, edited_text: 'Ten minutes with picture cards.', note: 'Matches our scope',
    }))
  })

  it('reject says plainly that nothing reached the learner', async () => {
    render(<PilotTeacherJourney token="t"/>)
    await screen.findByText(pendingRec.proposal)
    api.decidePilotRecommendation.mockResolvedValue({ ...pendingRec, status: 'rejected' })
    api.fetchPilotRecommendations.mockResolvedValue([{ ...pendingRec, status: 'rejected' }])
    fireEvent.click(screen.getByRole('button', { name: /Reject/ }))
    expect(await screen.findByText(/Nothing was sent to the learner/)).toBeTruthy()
    expect(api.decidePilotRecommendation).toHaveBeenCalledWith('t', A, REC, { action: 'reject', expected_version: 1 })
  })

  it('surfaces an abstention instead of inventing a draft', async () => {
    api.fetchPilotRecommendations.mockResolvedValue([])
    api.requestPilotRecommendation.mockResolvedValue({
      abstained: true, reason: 'No evidence has been recorded for this learner yet.', policy_version: 'p',
    })
    render(<PilotTeacherJourney token="t"/>)
    fireEvent.click(await screen.findByRole('button', { name: 'Ask Bede for a draft' }))
    expect(await screen.findByText(/No evidence has been recorded/)).toBeTruthy()
  })

  it('flags a failed audit-chain check loudly', async () => {
    api.fetchPilotLedger.mockResolvedValue({ chain_valid: false,
      entries: [{ seq: 1, action: 'approve', educator_id: 'e', created_at: '', note: null }] })
    render(<PilotTeacherJourney token="t"/>)
    expect(await screen.findByText(/integrity check FAILED/)).toBeTruthy()
  })
})
