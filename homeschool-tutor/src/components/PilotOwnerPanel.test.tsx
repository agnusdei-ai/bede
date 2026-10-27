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
  disablePilotOwnerCampus: vi.fn(),
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
  await screen.findByText(/Delete Example Learner's active pilot records/)
}

const confirmAndDelete = async () => {
  fireEvent.change(screen.getByLabelText(/to confirm/), { target: { value: 'Example Learner' } })
  const button = screen.getByRole('button', { name: 'Delete these records' }) as HTMLButtonElement
  await waitFor(() => expect(button.disabled).toBe(false))
  fireEvent.click(button)
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

  it('requires the exact selected campus name before a deliberate pilot stop', async () => {
    api.disablePilotOwnerCampus.mockResolvedValue({
      campus_id: C, status: 'disabled', memberships_disabled: 1,
      grants_revoked: 1, prior_educator_sessions_invalidated: true,
      learner_records_preserved: true,
    })
    render(<PilotOwnerPanel token="t"/>)
    await openPanel()
    const stop = screen.getByRole('button', { name: 'Disable campus access' }) as HTMLButtonElement
    expect(stop.disabled).toBe(true)
    const typed = screen.getByLabelText(/Type the campus name/)
    fireEvent.change(typed, { target: { value: 'Synthetic Campus' } })
    expect(stop.disabled).toBe(true)
    fireEvent.change(typed, { target: { value: 'Synthetic Campus One' } })
    expect(stop.disabled).toBe(false)
    fireEvent.click(stop)
    await waitFor(() => expect(api.disablePilotOwnerCampus).toHaveBeenCalledWith(
      't', C, 'Synthetic Campus One'))
    expect(await screen.findByText(/learner records are retained and educator access is stopped/i)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Disable campus access' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Delete these records' })).toBeNull()
  })

  it('does not mark a campus disabled if administrator authorization fails', async () => {
    api.disablePilotOwnerCampus.mockRejectedValue(
      new ApiRequestError(403, 'Verified administrator passkey required'))
    render(<PilotOwnerPanel token="t"/>)
    await openPanel()
    fireEvent.change(screen.getByLabelText(/Type the campus name/),
      { target: { value: 'Synthetic Campus One' } })
    fireEvent.click(screen.getByRole('button', { name: 'Disable campus access' }))
    await waitFor(() => expect(api.disablePilotOwnerCampus).toHaveBeenCalledTimes(1))
    expect((await screen.findByRole('alert')).textContent).toMatch(/administrator passkey/)
    expect(screen.getByRole('button', { name: 'Disable campus access' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Delete these records' })).toBeTruthy()
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

  // Fixed release rule: active application records may be removed, but Bede
  // never claims secure deletion, permanent erasure, or backup destruction —
  // backups may keep encrypted copies until an owner-approved retention policy
  // exists. Checked on what the owner actually reads (before and after a
  // deletion) and on the shared copy the docs quote.
  const ERASURE_CLAIM = /permanent|\berase|erasure|secure(ly)? delet|wip(e|ed|ing)\b|destroy|everywhere|cannot be undone|gone for good|irreversibl/i

  it('never claims erasure, permanence, or backup destruction', async () => {
    api.deletePilotLearner.mockResolvedValue(receipt())
    render(<PilotOwnerPanel token="t"/>)
    await openPanel()
    expect(document.body.textContent).not.toMatch(ERASURE_CLAIM)
    await confirmAndDelete()
    await screen.findByText(/active pilot records were removed on/)
    expect(document.body.textContent).not.toMatch(ERASURE_CLAIM)
    for (const sentence of Object.values(RECEIPT_COPY)) expect(sentence).not.toMatch(ERASURE_CLAIM)
    expect(RECEIPT_COPY.backups).toMatch(/does not change or remove any backup/)
  })

  it('leads with a plain summary of what was deleted, what remains, and backups', async () => {
    api.deletePilotLearner.mockResolvedValue(receipt())
    render(<PilotOwnerPanel token="t"/>)
    await openPanel()
    await confirmAndDelete()
    await waitFor(() => expect(api.deletePilotLearner).toHaveBeenCalledWith('t', C, L, 'Example Learner'))
    expect(await screen.findByText(/Example Learner's active pilot records were removed on/)).toBeTruthy()
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
    await waitFor(() => expect(api.deletePilotLearner).toHaveBeenCalledTimes(1))
    expect((await screen.findByRole('alert')).textContent).toBe(
      "Could not delete this learner's records. The name you typed doesn't match this learner. Check the spelling and try again.")

    api.deletePilotLearner.mockRejectedValue(new ApiRequestError(403, 'Verified administrator passkey required'))
    await confirmAndDelete()
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/needs your administrator passkey/))

    api.deletePilotLearner.mockRejectedValue(new ApiRequestError(500, 'Deletion did not complete; nothing was removed'))
    await confirmAndDelete()
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
