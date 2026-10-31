import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import en from '../i18n/locales/en.json'
import es from '../i18n/locales/es.json'
import SchoolDataAuthorization from './SchoolDataAuthorization'
import { NoticeChangedError } from '../services/api'
import { ApiRequestError } from '../utils/requestFailure'

const api = vi.hoisted(() => ({
  fetchSchoolDataAuthorization: vi.fn(),
  authorizeSchoolData: vi.fn(),
  revokeSchoolData: vi.fn(),
}))
vi.mock('../services/api', async (original) => ({
  ...await original<typeof import('../services/api')>(),
  ...api,
}))

const C = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const status = (over: Record<string, unknown> = {}) => ({
  authorized: false, stale: false, notice_hash: 'hash-1', notice_version: '2026-10-v1',
  notice_text: '1. Purpose\nSynthetic notice text.\n2. Scope', authorized_at: null,
  authorized_by: null, ...over,
})
const authorizedStatus = status({
  authorized: true, authorized_at: '2026-10-20T12:00:00Z', authorized_by: 'administrator',
})

beforeEach(() => {
  vi.clearAllMocks()
  i18n.changeLanguage('en')
  api.fetchSchoolDataAuthorization.mockResolvedValue(status())
})
afterEach(cleanup)

const HEADING = 'Authorization to Store Student Information'
const optInButton = () => screen.getByRole('button', { name: 'Authorize' }) as HTMLButtonElement
const fill = () => {
  fireEvent.change(screen.getByLabelText('Name of Authorized Official'), { target: { value: 'Pat Example' } })
  fireEvent.click(screen.getByRole('checkbox'))
}

describe('SchoolDataAuthorization', () => {
  it('shows the panel for an unauthorized campus and keeps the notice text', async () => {
    render(<SchoolDataAuthorization token="t" campusId={C} role="teacher"/>)
    expect(await screen.findByRole('heading', { name: HEADING })).toBeTruthy()
    const region = screen.getByRole('region', { name: 'School Authorization Notice' })
    expect(region.textContent).toContain('1. Purpose\nSynthetic notice text.')
    expect(screen.getByText(/Notice version 2026-10-v1/)).toBeTruthy()
    expect(screen.getByText('Teacher')).toBeTruthy()
    expect(api.fetchSchoolDataAuthorization).toHaveBeenCalledWith('t', C)
    expect(screen.getByText(en.schoolDataAuth.teacherWaitAdmin)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Authorize' })).toBeNull()
    expect(api.authorizeSchoolData).not.toHaveBeenCalled()
  })

  it('does not show the panel for an authorized campus (teacher sees nothing)', async () => {
    api.fetchSchoolDataAuthorization.mockResolvedValue(authorizedStatus)
    const { container } = render(<SchoolDataAuthorization token="t" campusId={C} role="teacher"/>)
    await waitFor(() => expect(api.fetchSchoolDataAuthorization).toHaveBeenCalled())
    expect(screen.queryByRole('heading', { name: HEADING })).toBeNull()
    expect(container.innerHTML).toBe('')
  })

  it('keeps Authorize disabled until both a name and the tick are present', async () => {
    render(<SchoolDataAuthorization token="t" campusId={C} role="administrator"/>)
    await screen.findByRole('heading', { name: HEADING })
    expect(optInButton().disabled).toBe(true)
    fireEvent.click(screen.getByRole('checkbox'))
    expect(optInButton().disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('Name of Authorized Official'), { target: { value: '   ' } })
    expect(optInButton().disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('Name of Authorized Official'), { target: { value: 'Pat Example' } })
    expect(optInButton().disabled).toBe(false)
    fireEvent.click(screen.getByRole('checkbox'))
    expect(optInButton().disabled).toBe(true)
  })

  it('posts the current notice hash, administrator role and trimmed name, then confirms', async () => {
    api.authorizeSchoolData.mockResolvedValue(status({
      authorized: true, authorized_at: '2026-10-20T12:00:00Z', authorized_by: 'administrator',
    }))
    const onChange = vi.fn()
    render(<SchoolDataAuthorization token="t" campusId={C} role="administrator" onChange={onChange}/>)
    await screen.findByRole('heading', { name: HEADING })
    fireEvent.change(screen.getByLabelText('Name of Authorized Official'), { target: { value: '  Pat Example ' } })
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(optInButton())
    await waitFor(() => expect(api.authorizeSchoolData).toHaveBeenCalledWith('t', C, {
      notice_hash: 'hash-1', authorizer_name: 'Pat Example', authorizer_role: 'administrator',
    }))
    const confirmation = await screen.findByText(/^Authorized by Administrator on /)
    expect(confirmation.textContent).toMatch(/2026/)
    expect(document.activeElement).toBe(confirmation)
    expect(onChange).toHaveBeenLastCalledWith(true)
    expect(screen.getByRole('button', { name: 'Withdraw Authorization' })).toBeTruthy()
  })

  it('on 409 notice_changed refetches, shows the new notice and asks for a fresh tick', async () => {
    api.fetchSchoolDataAuthorization
      .mockResolvedValueOnce(status())
      .mockResolvedValueOnce(status({ notice_hash: 'hash-2', notice_version: 'v2', notice_text: 'NEW TEXT' }))
    api.authorizeSchoolData.mockRejectedValue(new NoticeChangedError())
    render(<SchoolDataAuthorization token="t" campusId={C} role="administrator"/>)
    await screen.findByRole('heading', { name: HEADING })
    fill()
    fireEvent.click(optInButton())
    expect(await screen.findByText('NEW TEXT')).toBeTruthy()
    expect(api.fetchSchoolDataAuthorization).toHaveBeenCalledTimes(2)
    expect(screen.getByRole('heading', { name: 'Updated Notice: Renewed Authorization Required' })).toBeTruthy()
    expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false)
    expect(optInButton().disabled).toBe(true)
  })

  it('uses the stale wording when the server reports a changed notice', async () => {
    api.fetchSchoolDataAuthorization.mockResolvedValue(status({ stale: true }))
    render(<SchoolDataAuthorization token="t" campusId={C} role="administrator"/>)
    expect(await screen.findByRole('heading', { name: 'Updated Notice: Renewed Authorization Required' })).toBeTruthy()
    expect(screen.getByText(/must be reviewed again before authorization is renewed/)).toBeTruthy()
  })

  it('offers withdrawal to the administrator only, after confirmation', async () => {
    api.fetchSchoolDataAuthorization
      .mockResolvedValueOnce(authorizedStatus)
      .mockResolvedValueOnce(status())
    api.revokeSchoolData.mockResolvedValue({})
    render(<SchoolDataAuthorization token="t" campusId={C} role="administrator"/>)
    expect((await screen.findByText(/^Authorized by Administrator on /))).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Withdraw Authorization' }))
    expect(screen.getByText('Withdrawal ceases the storage of new student information. It does not delete existing records.')).toBeTruthy()
    expect(api.revokeSchoolData).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Withdraw Authorization' }))
    await waitFor(() => expect(api.revokeSchoolData).toHaveBeenCalledWith('t', C))
    expect(await screen.findByRole('heading', { name: HEADING })).toBeTruthy()
  })

  it('cancelling the withdrawal revokes nothing', async () => {
    api.fetchSchoolDataAuthorization.mockResolvedValue(authorizedStatus)
    render(<SchoolDataAuthorization token="t" campusId={C} role="administrator"/>)
    await screen.findByText(/^Authorized by Administrator on /)
    fireEvent.click(screen.getByRole('button', { name: 'Withdraw Authorization' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(api.revokeSchoolData).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Withdraw Authorization' })).toBeTruthy()
  })

  it('never offers withdrawal to a teacher', async () => {
    api.fetchSchoolDataAuthorization.mockResolvedValue(authorizedStatus)
    render(<SchoolDataAuthorization token="t" campusId={C} role="teacher"/>)
    await waitFor(() => expect(api.fetchSchoolDataAuthorization).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: /Withdraw/ })).toBeNull()
  })

  it('reports a load failure, fails closed and never stores state in localStorage', async () => {
    api.fetchSchoolDataAuthorization.mockRejectedValue(new ApiRequestError(500, 'x'))
    const onChange = vi.fn()
    render(<SchoolDataAuthorization token="t" campusId={C} role="teacher" onChange={onChange}/>)
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(onChange).toHaveBeenLastCalledWith(false)
    expect(localStorage.length).toBe(0)
  })

  it('has matching school authorization keys in English and Spanish, formally worded', () => {
    expect(Object.keys(es.schoolDataAuth).sort()).toEqual(Object.keys(en.schoolDataAuth).sort())
    expect(es.schoolDataAuth.heading).not.toBe(en.schoolDataAuth.heading)
  })

  it('renders in Spanish', async () => {
    await i18n.changeLanguage('es')
    render(<SchoolDataAuthorization token="t" campusId={C} role="teacher"/>)
    expect(await screen.findByRole('heading', { name: es.schoolDataAuth.heading })).toBeTruthy()
    expect(screen.getByText(es.schoolDataAuth.teacherWaitAdmin)).toBeTruthy()
  })
})
