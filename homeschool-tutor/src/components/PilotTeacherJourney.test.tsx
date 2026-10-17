import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PilotTeacherJourney from './PilotTeacherJourney'
import { ApiRequestError } from '../utils/requestFailure'

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
  it('offers a clear, calm teacher decision flow without implying automatic learner delivery', async () => {
    render(<PilotTeacherJourney token="t" />)
    expect(await screen.findByRole('heading', { name: 'Review Bede’s suggestions' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: '1. Look at the learner’s work' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: '2. Ask Bede for a suggestion' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: '3. Your approved teaching guidance' })).toBeTruthy()
    expect(screen.getByText(/You decide what is helpful/)).toBeTruthy()
    expect(screen.getByText(/not sent to learners automatically/)).toBeTruthy()
    expect(await screen.findByText(pendingRec.proposal)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Edit' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeTruthy()
  })

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
    const approved = { ...pendingRec, status: 'approved', version: 2, delivery_state: 'NOT_REQUESTED',
      authorized_instruction: pendingRec.proposal, decided_at: '2026-10-11T00:00:00Z' }
    api.decidePilotRecommendation.mockResolvedValue(approved)
    api.fetchPilotRecommendations.mockResolvedValue([approved])
    api.fetchPilotLedger.mockResolvedValue({ chain_valid: true,
      entries: [{ seq: 1, action: 'approve', educator_id: 'e', created_at: '', note: null }] })
    fireEvent.click(screen.getByRole('button', { name: /Approve/ }))
    await waitFor(() => expect(api.decidePilotRecommendation).toHaveBeenCalledWith(
      't', A, REC, { action: 'approve', expected_version: 1 }))
    expect(await screen.findByText(/1 decision · integrity check passed/)).toBeTruthy()
    expect(screen.queryByText(/Draft, awaiting your decision/)).toBeNull()
    // Decision 7: delivery into a learner session is unavailable (#585), so an
    // approval is shown as recorded and ready for teacher use, never as delivered.
    expect((await screen.findAllByText(/ready for teacher use/)).length).toBeGreaterThan(0)
    const text = document.body.textContent ?? ''
    for (const claim of [/reaches a learner/i, /sent to the learner/i, /delivered/i, /applied to/i, /Teach this with Bede/i]) {
      expect(text).not.toMatch(claim)
    }
    expect(screen.queryByRole('button', { name: /teach|start session|deliver/i })).toBeNull()
    expect(screen.getByText(/Not sent to any learner session/)).toBeTruthy()
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

  it('reject is recorded, not described as delivery', async () => {
    render(<PilotTeacherJourney token="t"/>)
    await screen.findByText(pendingRec.proposal)
    api.decidePilotRecommendation.mockResolvedValue({ ...pendingRec, status: 'rejected' })
    api.fetchPilotRecommendations.mockResolvedValue([{ ...pendingRec, status: 'rejected' }])
    fireEvent.click(screen.getByRole('button', { name: /Reject/ }))
    expect(await screen.findByText(/Recommendation rejected and recorded/)).toBeTruthy()
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

  it('explains a failed audit-trail check calmly, with what to do', async () => {
    api.fetchPilotLedger.mockResolvedValue({ chain_valid: false,
      entries: [{ seq: 1, action: 'approve', educator_id: 'e', created_at: '', note: null }] })
    render(<PilotTeacherJourney token="t"/>)
    const line = await screen.findByText(/integrity check did not pass/)
    expect(line.textContent).toMatch(/tell your administrator before relying on this history/)
    expect(line.textContent).not.toMatch(/\b[A-Z]{4,}\b/)  // no all-caps alarm words
  })

  it('explains a decision conflict and refreshes instead of echoing server text', async () => {
    render(<PilotTeacherJourney token="t"/>)
    await screen.findByText(pendingRec.proposal)
    api.decidePilotRecommendation.mockRejectedValue(
      new ApiRequestError(409, 'Recommendation already decided or changed'))
    const loads = api.fetchPilotRecommendations.mock.calls.length
    fireEvent.click(screen.getByRole('button', { name: /Approve/ }))
    expect(await screen.findByText(/Could not record your decision\. This draft was already decided/)).toBeTruthy()
    await waitFor(() => expect(api.fetchPilotRecommendations.mock.calls.length).toBeGreaterThan(loads))
  })

  it('never shows raw exception text, and names a dropped connection', async () => {
    render(<PilotTeacherJourney token="t"/>)
    await screen.findByText(pendingRec.proposal)
    api.decidePilotRecommendation.mockRejectedValue(
      new ApiRequestError(500, 'Traceback (most recent call last): sqlalchemy.exc.OperationalError'))
    fireEvent.click(screen.getByRole('button', { name: /Approve/ }))
    expect(await screen.findByText(/Could not record your decision\. The server could not finish/)).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/Traceback|sqlalchemy|OperationalError/)

    api.decidePilotRecommendation.mockRejectedValue(new TypeError('Load failed'))
    fireEvent.click(screen.getByRole('button', { name: /Approve/ }))
    expect(await screen.findByText(/couldn't reach the server\. Check your internet connection/)).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/Load failed/)
  })
})
