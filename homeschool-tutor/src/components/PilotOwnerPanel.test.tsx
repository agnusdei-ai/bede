import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PilotOwnerPanel, { RECEIPT_COPY } from './PilotOwnerPanel'
import { ApiRequestError } from '../utils/requestFailure'

const api = vi.hoisted(() => ({
  fetchEducatorPilotMode: vi.fn(),
  fetchPilotOwnerCampuses: vi.fn(),
  fetchPilotDeletionReceipts: vi.fn(),
  fetchPilotOwnerLearners: vi.fn(),
  deletePilotLearner: vi.fn(),
}))
vi.mock('../services/api', async (original) => ({
  ...await original<typeof import('../services/api')>(),
  ...api,
}))

// Synthetic, canonical UUIDv4-shaped ids only.
const C = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const L = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
const SHA = 'f'.repeat(64)

const receipt = (over: Record<string, unknown> = {}) => ({
  receipt_id: 'r1', campus_id: C, learner_id: L, actor: 'owner',
  deleted_counts: { learners: 1, evidence: 2, roster_grants: 1, recommendations: 1, decisions: 1 },
  remaining_counts: { learners: 0, evidence: 0, roster_grants: 0, recommendations: 0, decisions: 0 },
  deleted_at: '2026-10-16T12:00:00.000000Z', receipt_sha256: SHA, ...over,
})

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchEducatorPilotMode.mockResolvedValue({ enabled: true, shared_child_pin_disabled: true })
  api.fetchPilotOwnerCampuses.mockResolvedValue([{ campus_id: C, title: 'Synthetic Campus One', enabled: true }])
  api.fetchPilotDeletionReceipts.mockResolvedValue([])
  api.fetchPilotOwnerLearners.mockResolvedValue([
    { learner_id: L, campus_id: C, display_name: 'Example Learner', enabled: true },
  ])
})
afterEach(cleanup)

const openPanel = async () => {
  fireEvent.click(await screen.findByRole('button', { name: /Classroom pilot/ }))
  await screen.findByText(/Permanently delete Example Learner's pilot records/)
}

const confirmAndDelete = async () => {
  fireEvent.change(screen.getByLabelText(/to confirm/), { target: { value: 'Example Learner' } })
  fireEvent.click(screen.getByRole('button', { name: 'Delete these records' }))
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
    await screen.findByRole('button', { name: /Classroom pilot/ })
    expect(api.fetchPilotOwnerCampuses).not.toHaveBeenCalled()
    await openPanel()
    expect(api.fetchPilotOwnerCampuses).toHaveBeenCalledWith('t')
    expect(api.fetchPilotOwnerLearners).toHaveBeenCalledWith('t', C)
  })

  it('offers no session plan, session receipts, or teaching action', async () => {
    render(<PilotOwnerPanel token="t"/>)
    await openPanel()
    const text = document.body.textContent ?? ''
    for (const s of [/session plan/i, /session receipts/i, /teach this/i, /delivered/i]) {
      expect(text).not.toMatch(s)
    }
    expect(screen.queryByRole('button', { name: /save plan|teach|start session|deliver/i })).toBeNull()
  })

  it('deletes only after the exact name is typed', async () => {
    render(<PilotOwnerPanel token="t"/>)
    await openPanel()
    const button = screen.getByRole('button', { name: 'Delete these records' }) as HTMLButtonElement
    fireEvent.change(screen.getByLabelText(/to confirm/), { target: { value: 'Example' } })
    expect(button.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText(/to confirm/), { target: { value: 'Example Learner' } })
    expect(button.disabled).toBe(false)
  })

  it('leads with a plain summary of what was deleted, what remains, and backups', async () => {
    api.deletePilotLearner.mockResolvedValue(receipt())
    render(<PilotOwnerPanel token="t"/>)
    await openPanel()
    await confirmAndDelete()
    await waitFor(() => expect(api.deletePilotLearner).toHaveBeenCalledWith('t', C, L, 'Example Learner'))
    expect(await screen.findByText(/All of Example Learner's pilot records were removed on/)).toBeTruthy()
    const status = screen.getAllByRole('status')[0]
    for (const sentence of Object.values(RECEIPT_COPY)) expect(status.textContent).toContain(sentence)
    // The technical detail is present but collapsed behind a disclosure.
    const details = status.querySelector('details') as HTMLDetailsElement
    expect(details.open).toBe(false)
    expect(details.querySelector('summary')?.textContent).toBe('Technical details for administrators')
    expect(details.textContent).toContain(SHA)
    expect(details.textContent).toContain('Teacher assignments')
    // Nothing technical appears outside the disclosure.
    const outside = status.textContent!.replace(details.textContent!, '')
    expect(outside).not.toMatch(/SHA-256|receipt id|r1|[0-9a-f]{64}/i)
  })

  it('says calmly when some records were not removed', async () => {
    api.deletePilotLearner.mockResolvedValue(receipt({ remaining_counts: { learners: 0, evidence: 1 } }))
    render(<PilotOwnerPanel token="t"/>)
    await openPanel()
    await confirmAndDelete()
    const line = await screen.findByText(/Some records were not removed\. Nothing further was deleted\./)
    expect(line.textContent).not.toMatch(/NOT ZERO|\b[A-Z]{4,}\b/)
    expect(screen.queryByText(/were removed on/)).toBeNull()
  })

  it('explains a receipt whose integrity check failed, without alarm words', async () => {
    api.fetchPilotDeletionReceipts.mockResolvedValue([{ ...receipt(), receipt_sha256: 'x', hash_verified: false }])
    render(<PilotOwnerPanel token="t"/>)
    await openPanel()
    const line = screen.getByText(/This receipt's integrity check failed/)
    expect(line.textContent).toMatch(/Keep it and report it; do not rely on it as proof of deletion\./)
    expect(document.body.textContent).not.toMatch(/HASH MISMATCH/)
  })

  it('turns failures into what failed and what to do, never server text', async () => {
    api.deletePilotLearner.mockRejectedValue(new ApiRequestError(422, 'Confirmation does not match'))
    render(<PilotOwnerPanel token="t"/>)
    await openPanel()
    await confirmAndDelete()
    expect((await screen.findByRole('alert')).textContent).toBe(
      "Could not delete this learner's records. The name you typed doesn't match this learner. Check the spelling and try again.")

    api.deletePilotLearner.mockRejectedValue(new ApiRequestError(403, 'Verified administrator passkey required'))
    fireEvent.click(screen.getByRole('button', { name: 'Delete these records' }))
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/needs your administrator passkey/))

    api.deletePilotLearner.mockRejectedValue(new ApiRequestError(500, 'Deletion did not complete; nothing was removed'))
    fireEvent.click(screen.getByRole('button', { name: 'Delete these records' }))
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/check whether the learner is still listed/))
    expect(document.body.textContent).not.toMatch(/Request failed|Deletion did not complete/)
  })

  it('the pilot doc quotes the receipt statements exactly', () => {
    const doc = readFileSync(
      resolve(__dirname, '../../../docs/EDUCATOR_CLASSROOM_PILOT.md'), 'utf-8').replace(/\s+/g, ' ')
    for (const sentence of Object.values(RECEIPT_COPY)) expect(doc).toContain(sentence)
  })

  it('names a dropped connection when the panel cannot load', async () => {
    api.fetchPilotOwnerCampuses.mockRejectedValue(new TypeError('Failed to fetch'))
    render(<PilotOwnerPanel token="t"/>)
    fireEvent.click(await screen.findByRole('button', { name: /Classroom pilot/ }))
    expect((await screen.findByRole('alert')).textContent).toBe(
      "Could not load the pilot campuses. We couldn't reach the server. Check your internet connection and try again.")
  })
})
