/**
 * DeviceSettings.tsx — the parent-facing device list + revoke UI for P9
 * (core/device_registry.py). Renders nothing for an empty deployment,
 * lists devices once loaded, and revoking calls through to the API —
 * ElevationPrompt.tsx (mounted separately, at the app root) is what
 * actually handles the 403 a real revoke call can return; this file only
 * proves DeviceSettings itself calls the right functions with the right
 * arguments and reflects the result.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { fetchDevices, revokeDevice, listPodConfigs, assignChildLearner, getOrCreateDeviceId } = vi.hoisted(() => ({
  fetchDevices: vi.fn(),
  revokeDevice: vi.fn(),
  listPodConfigs: vi.fn(),
  assignChildLearner: vi.fn(),
  getOrCreateDeviceId: vi.fn(),
}))

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return { ...actual, fetchDevices, revokeDevice, listPodConfigs, assignChildLearner }
})
vi.mock('../utils/deviceId', () => ({ getOrCreateDeviceId }))

import DeviceSettings from './DeviceSettings'

const DEV_1 = {
  device_id: 'dev-1',
  first_seen_at: '2026-08-01T10:00:00Z',
  last_seen_at: '2026-08-04T09:00:00Z',
  last_role: 'parent',
  last_user_agent: 'Safari on iPad',
  revoked: false,
  revoked_at: null,
}
const DEV_2 = {
  device_id: 'dev-2',
  first_seen_at: '2026-08-02T10:00:00Z',
  last_seen_at: '2026-08-03T09:00:00Z',
  last_role: 'child',
  last_user_agent: 'Chrome on Android',
  revoked: false,
  revoked_at: null,
}

beforeEach(() => {
  fetchDevices.mockReset()
  revokeDevice.mockReset()
  listPodConfigs.mockReset()
  listPodConfigs.mockResolvedValue([])
  assignChildLearner.mockReset()
  getOrCreateDeviceId.mockReset()
  getOrCreateDeviceId.mockReturnValue('dev-1')
  vi.spyOn(window, 'confirm').mockReturnValue(true)
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('DeviceSettings — empty and loading states', () => {
  it('renders nothing once loaded with zero devices', async () => {
    fetchDevices.mockResolvedValue([])
    const { container } = render(<DeviceSettings token="tok" />)
    await waitFor(() => expect(fetchDevices).toHaveBeenCalledWith('tok'))
    await waitFor(() => expect(container.firstChild).toBeNull())
  })

  it('keeps the card visible (not silently hidden) when the fetch fails', async () => {
    fetchDevices.mockRejectedValue(new Error('network error'))
    render(<DeviceSettings token="tok" />)
    await waitFor(() => expect(fetchDevices).toHaveBeenCalled())
    expect(screen.getByText('Devices')).toBeTruthy()
  })
})

describe('DeviceSettings — listing', () => {
  it('shows each device once expanded, with a "This device" badge on the matching one', async () => {
    fetchDevices.mockResolvedValue([DEV_1, DEV_2])
    render(<DeviceSettings token="tok" />)
    await waitFor(() => expect(fetchDevices).toHaveBeenCalled())

    fireEvent.click(screen.getByText('Devices'))

    expect(await screen.findByText(/Parent · Safari on iPad/)).toBeTruthy()
    expect(screen.getByText(/Child · Chrome on Android/)).toBeTruthy()
    expect(screen.getByText('This device')).toBeTruthy()
  })

  it('never shows a revoke button for an already-revoked device', async () => {
    fetchDevices.mockResolvedValue([{ ...DEV_1, revoked: true, revoked_at: '2026-08-04T10:00:00Z' }])
    render(<DeviceSettings token="tok" />)
    await waitFor(() => expect(fetchDevices).toHaveBeenCalled())
    fireEvent.click(screen.getByText('Devices'))

    await screen.findByText(/Parent · Safari on iPad/)
    expect(screen.queryByText('Revoke')).toBeNull()
    expect(screen.getByText(/Revoked/)).toBeTruthy()
  })
})

describe('DeviceSettings — revoking', () => {
  it('revokes a DIFFERENT device without asking for confirmation', async () => {
    fetchDevices.mockResolvedValue([DEV_2])
    revokeDevice.mockResolvedValue({ ...DEV_2, revoked: true, revoked_at: '2026-08-04T10:00:00Z' })
    render(<DeviceSettings token="tok" />)
    await waitFor(() => expect(fetchDevices).toHaveBeenCalled())
    fireEvent.click(screen.getByText('Devices'))

    fireEvent.click(await screen.findByText('Revoke'))

    expect(window.confirm).not.toHaveBeenCalled()
    await waitFor(() => expect(revokeDevice).toHaveBeenCalledWith('tok', 'dev-2'))
    await waitFor(() => expect(screen.getByText(/Revoked/)).toBeTruthy())
  })

  it('confirms before revoking the CURRENT device, and does not call the API if cancelled', async () => {
    fetchDevices.mockResolvedValue([DEV_1])
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<DeviceSettings token="tok" />)
    await waitFor(() => expect(fetchDevices).toHaveBeenCalled())
    fireEvent.click(screen.getByText('Devices'))

    fireEvent.click(await screen.findByText('Revoke'))

    expect(window.confirm).toHaveBeenCalled()
    expect(revokeDevice).not.toHaveBeenCalled()
  })

  it('revokes the current device once confirmed', async () => {
    fetchDevices.mockResolvedValue([DEV_1])
    revokeDevice.mockResolvedValue({ ...DEV_1, revoked: true, revoked_at: '2026-08-04T10:00:00Z' })
    render(<DeviceSettings token="tok" />)
    await waitFor(() => expect(fetchDevices).toHaveBeenCalled())
    fireEvent.click(screen.getByText('Devices'))

    await act(async () => {
      fireEvent.click(await screen.findByText('Revoke'))
    })

    expect(revokeDevice).toHaveBeenCalledWith('tok', 'dev-1')
  })

  it('surfaces an error and keeps the device listed as unrevoked when the API call fails', async () => {
    fetchDevices.mockResolvedValue([DEV_2])
    revokeDevice.mockRejectedValue(new Error('This device could not be revoked'))
    render(<DeviceSettings token="tok" />)
    await waitFor(() => expect(fetchDevices).toHaveBeenCalled())
    fireEvent.click(screen.getByText('Devices'))

    fireEvent.click(await screen.findByText('Revoke'))

    expect(await screen.findByText('This device could not be revoked')).toBeTruthy()
    expect(screen.getByText('Revoke')).toBeTruthy() // still there — not marked revoked
  })
})


describe('DeviceSettings — parent-authorized learner assignment', () => {
  it('lets a parent assign or switch a configured learner on a known device', async () => {
    fetchDevices.mockResolvedValue([DEV_2])
    listPodConfigs.mockResolvedValue([{ student_name: 'Emma' }, { student_name: 'Noah' }])
    assignChildLearner.mockResolvedValue(undefined)
    render(<DeviceSettings token="parent-token" />)
    fireEvent.click(screen.getByText('Devices'))
    const select = await screen.findByRole('combobox', { name: 'Learner for dev-2' })
    fireEvent.change(select, { target: { value: 'Noah' } })
    fireEvent.click(screen.getByRole('button', { name: 'Assign / switch' }))
    await waitFor(() => expect(assignChildLearner).toHaveBeenCalledWith('parent-token', 'dev-2', 'Noah'))
    expect(await screen.findByRole('status')).toHaveProperty('textContent', expect.stringContaining('sign in again'))
  })

  it('does not offer learner assignment for a revoked device', async () => {
    fetchDevices.mockResolvedValue([{ ...DEV_2, revoked: true, revoked_at: '2026-08-04T10:00:00Z' }])
    listPodConfigs.mockResolvedValue([{ student_name: 'Emma' }])
    render(<DeviceSettings token="parent-token" />)
    fireEvent.click(screen.getByText('Devices'))
    await screen.findByText(/Revoked/)
    expect(screen.queryByRole('button', { name: 'Assign / switch' })).toBeNull()
  })
})
