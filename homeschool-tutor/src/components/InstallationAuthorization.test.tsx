import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import type { InstallationStatus } from '../services/api'

const jsonRes = (status: number, body: unknown) =>
  ({ ok: status < 400, status, json: async () => body }) as Response

import {
  VerificationMethodUnavailableError, completeVerification, fetchInstallationStatus, startVerification,
  withdrawInstallation,
} from '../services/api'
import InstallationAuthorization from './InstallationAuthorization'
import ConsentBanner from './ConsentBanner'
import SchoolDataAuthorization from './SchoolDataAuthorization'
import { useSessionStore } from '../store/sessionStore'

const base = (over: Partial<InstallationStatus> = {}): InstallationStatus => ({
  state: 'pending_verification', mode: 'family', receipt_id: 'r-1',
  notice: { version: '2026-10-v1', sha256: 'abc' }, accepted_at: '2026-10-20T12:00:00Z',
  authorizer: { name: 'Pat Example', capacity: 'parent_guardian' },
  processing_enabled: false, chain_valid: true, ...over,
})

let fetchMock: ReturnType<typeof vi.fn>
beforeEach(() => {
  i18n.changeLanguage('en')
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('installation api', () => {
  it('GETs /installation/status and POSTs withdraw with the bearer token', async () => {
    fetchMock.mockResolvedValue(jsonRes(200, base()))
    await fetchInstallationStatus('tok')
    await withdrawInstallation('tok')
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/installation\/status$/)
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer tok')
    expect(fetchMock.mock.calls[1][0]).toMatch(/\/installation\/withdraw$/)
    expect(fetchMock.mock.calls[1][1].method).toBe('POST')
  })
  it('turns 409 verification_method_unavailable into a typed error, other failures stay generic', async () => {
    fetchMock.mockResolvedValue(jsonRes(409, { detail: { error: 'verification_method_unavailable' } }))
    await expect(startVerification('t')).rejects.toBeInstanceOf(VerificationMethodUnavailableError)
    await expect(completeVerification('t')).rejects.toBeInstanceOf(VerificationMethodUnavailableError)
    fetchMock.mockResolvedValue(jsonRes(409, { detail: { error: 'other' } }))
    await expect(startVerification('t')).rejects.not.toBeInstanceOf(VerificationMethodUnavailableError)
  })
})

describe('InstallationAuthorization states', () => {
  it('renders nothing while the status is unknown', () => {
    const { container } = render(<InstallationAuthorization token="t" status={null} />)
    expect(container.innerHTML).toBe('')
  })

  it('pending: says processing is off, calls it an attestation, never "verified"', () => {
    render(<InstallationAuthorization token="t" status={base()} />)
    expect(screen.getByTestId('install-auth-state').textContent).toBe('Awaiting verification')
    expect(screen.getByTestId('install-auth-processing').textContent).toBe('Child-data processing: not enabled')
    expect(screen.getByText(/attestation only/i)).toBeTruthy()
    expect(screen.queryByText(/^Verified$/)).toBeNull()
    expect(screen.getByText('Pat Example')).toBeTruthy()
    expect(screen.getByText('2026-10-v1')).toBeTruthy()
    expect(screen.getByText('Parent or legal guardian')).toBeTruthy()
    expect(screen.getByText('A family')).toBeTruthy()
  })

  it('verified: processing enabled', () => {
    render(<InstallationAuthorization token="t" status={base({ state: 'verified', processing_enabled: true })} />)
    expect(screen.getByTestId('install-auth-state').textContent).toBe('Verified')
    expect(screen.getByTestId('install-auth-processing').textContent).toBe('Child-data processing: enabled')
  })

  it('verified state with processing_enabled false or broken chain is not shown as enabled', () => {
    render(<InstallationAuthorization token="t" status={base({ state: 'verified', processing_enabled: true, chain_valid: false })} />)
    expect(screen.getByTestId('install-auth-processing').textContent).toBe('Child-data processing: not enabled')
    expect(screen.getByRole('alert').textContent).toMatch(/integrity check/)
  })

  it('a non-verified state never reads as enabled even if the flag says so', () => {
    render(<InstallationAuthorization token="t" status={base({ processing_enabled: true })} />)
    expect(screen.getByTestId('install-auth-processing').textContent).toBe('Child-data processing: not enabled')
  })

  it('invalid and withdrawn: off, no withdraw or verify actions', () => {
    for (const state of ['invalid', 'withdrawn'] as const) {
      const { unmount } = render(<InstallationAuthorization token="t" status={base({ state })} />)
      expect(screen.getByTestId('install-auth-processing').textContent).toBe('Child-data processing: not enabled')
      expect(screen.queryByRole('button', { name: 'Withdraw Authorization' })).toBeNull()
      expect(screen.queryByRole('button', { name: 'Start Verification' })).toBeNull()
      unmount()
    }
  })

  it('school mode points to the school panel', () => {
    render(<InstallationAuthorization token="t" status={base({
      mode: 'school', state: 'verified', processing_enabled: true,
      authorizer: { name: 'Sam', capacity: 'administrator' },
    })} />)
    expect(screen.getByText('A school')).toBeTruthy()
    expect(screen.getByText('School administrator')).toBeTruthy()
    expect(screen.getByText(/school authorization panel/i)).toBeTruthy()
  })

  it('renders in Spanish', () => {
    i18n.changeLanguage('es')
    render(<InstallationAuthorization token="t" status={base()} />)
    expect(screen.getByTestId('install-auth-state').textContent).toBe('En espera de verificación')
  })
})

describe('verification 409 path', () => {
  it('shows a plain not-yet-available state, not an error', async () => {
    fetchMock.mockResolvedValue(jsonRes(409, { detail: { error: 'verification_method_unavailable' } }))
    render(<InstallationAuthorization token="t" status={base()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Start Verification' }))
    expect(await screen.findByRole('status')).toBeTruthy()
    expect(screen.getByText(/not yet available/i)).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/installation\/verification\/start$/)
  })
  it('other failures show a retryable error', async () => {
    fetchMock.mockResolvedValue(jsonRes(500, {}))
    render(<InstallationAuthorization token="t" status={base()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Complete Verification' }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/try again/i)
    expect(screen.queryByText(/not yet available/i)).toBeNull()
  })
})

describe('withdraw through the real component', () => {
  it('needs confirmation, then POSTs /installation/withdraw and refreshes', async () => {
    fetchMock.mockResolvedValue(jsonRes(200, base({ state: 'withdrawn' })))
    const onChanged = vi.fn()
    render(<InstallationAuthorization token="tok" status={base({ state: 'verified', processing_enabled: true })} onChanged={onChanged} />)
    fireEvent.click(screen.getByRole('button', { name: 'Withdraw Authorization' }))
    expect(fetchMock).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Yes, Withdraw' }))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/installation\/withdraw$/)
    expect(fetchMock.mock.calls[0][1].method).toBe('POST')
  })
  it('Keep It cancels without calling the server', () => {
    render(<InstallationAuthorization token="tok" status={base()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Withdraw Authorization' }))
    fireEvent.click(screen.getByRole('button', { name: 'Keep It' }))
    expect(fetchMock).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'Yes, Withdraw' })).toBeNull()
  })
})

describe('ConsentBanner with a pending receipt', () => {
  const consent = (over = {}) => ({
    needs_consent: false, install_ack: true, notice_hash: 'h', notice_version: 'v',
    notice_text: 'text', students: [], ...over,
  })
  beforeEach(() => {
    sessionStorage.clear()
    useSessionStore.getState().logout()
    useSessionStore.getState().setAuth('parent-token', 'parent')
  })

  it('does not stay silent as if covered when the install ack is only pending', () => {
    render(<ConsentBanner consent={consent()} installation={base()} />)
    expect(screen.getByText('Installation Not Yet Verified')).toBeTruthy()
    expect(screen.getByText(/does not count as consent/i)).toBeTruthy()
  })
  it('stays silent when the receipt is verified, or unknown', () => {
    const a = render(<ConsentBanner consent={consent()} installation={base({ state: 'verified', processing_enabled: true })} />)
    expect(a.container.innerHTML).toBe('')
    a.unmount()
    const b = render(<ConsentBanner consent={consent()} installation={null} />)
    expect(b.container.innerHTML).toBe('')
  })
  it('adds the not-counted note to the consent form while pending', () => {
    render(<ConsentBanner consent={consent({ needs_consent: true, install_ack: false })} installation={base()} />)
    expect(screen.getByTestId('consent-receipt-pending')).toBeTruthy()
  })
})

describe('SchoolDataAuthorization installer provenance', () => {
  it('shows the installer note only when fromInstaller', async () => {
    const authorized = {
      authorized: true, stale: false, notice_hash: 'h', notice_version: 'v', notice_text: 't',
      authorized_at: '2026-10-20T12:00:00Z', authorized_by: 'administrator',
    }
    fetchMock.mockResolvedValue(jsonRes(200, authorized))
    const a = render(<SchoolDataAuthorization token="t" campusId="c1" role="administrator" fromInstaller />)
    expect(await screen.findByTestId('school-auth-from-installer')).toBeTruthy()
    a.unmount()
    render(<SchoolDataAuthorization token="t" campusId="c1" role="administrator" />)
    await screen.findByRole('button', { name: 'Withdraw Authorization' })
    expect(screen.queryByTestId('school-auth-from-installer')).toBeNull()
  })
})
