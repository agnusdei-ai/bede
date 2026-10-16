import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PilotOwnerPanel from './PilotOwnerPanel'

const api = vi.hoisted(() => ({
  fetchEducatorPilotMode: vi.fn(),
  fetchPilotOwnerCampuses: vi.fn(),
  fetchPilotDeletionReceipts: vi.fn(),
  fetchPilotOwnerLearners: vi.fn(),
  fetchPilotOwnerPlan: vi.fn(),
  fetchPilotOwnerSessions: vi.fn(),
  savePilotOwnerPlan: vi.fn(),
  deletePilotLearner: vi.fn(),
}))
vi.mock('../services/api', async (original) => ({
  ...await original<typeof import('../services/api')>(),
  ...api,
}))

const C = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const L = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchEducatorPilotMode.mockResolvedValue({ enabled: true, shared_child_pin_disabled: true })
  api.fetchPilotOwnerCampuses.mockResolvedValue([{ campus_id: C, title: 'Synthetic Campus Alpha', enabled: true }])
  api.fetchPilotDeletionReceipts.mockResolvedValue([])
  api.fetchPilotOwnerLearners.mockResolvedValue([
    { learner_id: L, campus_id: C, display_name: 'Example Learner', enabled: true, has_plan: false },
  ])
  api.fetchPilotOwnerPlan.mockResolvedValue({ learner_id: L, plan: null })
  api.fetchPilotOwnerSessions.mockResolvedValue([])
})
afterEach(cleanup)

const openPanel = async () => {
  fireEvent.click(await screen.findByRole('button', { name: /Valor pilot/ }))
  await screen.findByText('Delete this learner permanently')
}

describe('PilotOwnerPanel', () => {
  it('renders nothing when the institutional pilot is not enabled', async () => {
    api.fetchEducatorPilotMode.mockResolvedValue({ enabled: false, shared_child_pin_disabled: false })
    const { container } = render(<PilotOwnerPanel token="t"/>)
    await waitFor(() => expect(api.fetchEducatorPilotMode).toHaveBeenCalled())
    expect(container.innerHTML).toBe('')
  })

  it('asks for nothing privileged until the owner opens it', async () => {
    render(<PilotOwnerPanel token="t"/>)
    await screen.findByRole('button', { name: /Valor pilot/ })
    expect(api.fetchPilotOwnerCampuses).not.toHaveBeenCalled()
    await openPanel()
    expect(api.fetchPilotOwnerCampuses).toHaveBeenCalledWith('t')
  })

  it('saves the plan and shows the cleaned subjects the server returned', async () => {
    api.savePilotOwnerPlan.mockResolvedValue({ learner_id: L, plan: { grade: '1', subjects: ['mathematics'] } })
    render(<PilotOwnerPanel token="t"/>)
    await openPanel()
    fireEvent.click(screen.getByLabelText('Mathematics'))
    fireEvent.click(screen.getByRole('button', { name: 'Save plan' }))
    await waitFor(() => expect(api.savePilotOwnerPlan).toHaveBeenCalledWith(
      't', C, L, { grade: '1', subjects: ['mathematics'] }))
    expect(await screen.findByText('Session plan saved.')).toBeTruthy()
  })

  it('deletes only after the exact name is typed, then shows the receipt', async () => {
    api.deletePilotLearner.mockResolvedValue({
      receipt_id: 'r1', campus_id: C, learner_id: L, actor: 'owner',
      deleted_counts: { learners: 1, evidence: 2 }, remaining_counts: { learners: 0, evidence: 0 },
      deleted_at: '2026-10-16T12:00:00Z', receipt_sha256: 'f'.repeat(64),
    })
    render(<PilotOwnerPanel token="t"/>)
    await openPanel()
    const button = screen.getByRole('button', { name: 'Delete learner' }) as HTMLButtonElement
    fireEvent.change(screen.getByLabelText(/Type the learner's name/), { target: { value: 'Example' } })
    expect(button.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText(/Type the learner's name/), { target: { value: 'Example Learner' } })
    expect(button.disabled).toBe(false)
    fireEvent.click(button)
    await waitFor(() => expect(api.deletePilotLearner).toHaveBeenCalledWith('t', C, L, 'Example Learner'))
    expect(await screen.findByText('Deletion complete')).toBeTruthy()
    expect(screen.getByText('Remaining after re-check: none')).toBeTruthy()
  })

  it('flags a receipt whose hash no longer verifies', async () => {
    api.fetchPilotDeletionReceipts.mockResolvedValue([{
      receipt_id: 'r0', campus_id: C, learner_id: L, actor: 'owner', deleted_counts: {},
      remaining_counts: {}, deleted_at: '2026-10-15T00:00:00Z', receipt_sha256: 'x', hash_verified: false,
    }])
    render(<PilotOwnerPanel token="t"/>)
    await openPanel()
    expect(screen.getByText(/HASH MISMATCH/)).toBeTruthy()
  })
})
