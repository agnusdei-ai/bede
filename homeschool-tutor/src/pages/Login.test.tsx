/**
 * Regression coverage for the per-login language toggle (see
 * docs/LOCALIZATION.md): the toggle must stay hidden on an English-only
 * deployment, appear when the backend actually offers a locale, and wire
 * the selection all the way through — switching i18n live and sending the
 * choice on the login POST itself, not just cosmetically.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { fetchAvailableLocales, login } = vi.hoisted(() => ({
  fetchAvailableLocales: vi.fn(),
  login: vi.fn(),
}))

vi.mock('../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api')>()
  return { ...actual, fetchAvailableLocales, login }
})

import i18n from '../i18n'
import { setLogoutNotice } from '../utils/logoutNotice'
import Login from './Login'

function renderLogin() {
  return render(
    <MemoryRouter>
      <Login />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  fetchAvailableLocales.mockReset()
  login.mockReset()
  sessionStorage.clear()
})

afterEach(() => {
  // This project's vitest config doesn't set `globals: true`, so RTL's own
  // automatic afterEach(cleanup) never registers — without this, each
  // render() below leaks into document.body and later tests' screen.getBy*
  // queries match stale elements from a previous test's render.
  cleanup()
  i18n.changeLanguage('en')
})

describe('Login language toggle', () => {
  it('renders no toggle on an English-only deployment', async () => {
    fetchAvailableLocales.mockResolvedValue([])
    renderLogin()

    await waitFor(() => expect(fetchAvailableLocales).toHaveBeenCalled())
    expect(screen.queryByText('English')).toBeNull()
    expect(screen.queryByText('Español')).toBeNull()
  })

  it('renders the toggle when the deployment offers a locale', async () => {
    fetchAvailableLocales.mockResolvedValue([{ code: 'es', name: 'Spanish (Español)' }])
    renderLogin()

    await waitFor(() => expect(screen.queryByText('English')).not.toBeNull())
    expect(screen.queryByText('Español')).not.toBeNull()
  })

  it('switches i18n live when Español is selected, without waiting for login to complete', async () => {
    fetchAvailableLocales.mockResolvedValue([{ code: 'es', name: 'Spanish (Español)' }])
    renderLogin()

    await waitFor(() => expect(screen.queryByText('Español')).not.toBeNull())
    act(() => { fireEvent.click(screen.getByText('Español')) })

    expect(i18n.language).toBe('es')
  })

  it('sends the selected locale on the login request', async () => {
    fetchAvailableLocales.mockResolvedValue([{ code: 'es', name: 'Spanish (Español)' }])
    login.mockResolvedValue({ accessToken: 'tok', role: 'child', mfaRequired: false, mfaMethods: [] })
    renderLogin()

    await waitFor(() => expect(screen.queryByText('Español')).not.toBeNull())
    // Role toggle first, in English — clicking "Español" re-renders the
    // whole page (including this button's own label) in Spanish, same
    // proof point as the earlier "switches i18n live" test.
    fireEvent.click(screen.getByText('Student'))
    fireEvent.click(screen.getByText('Español'))
    fireEvent.change(screen.getByPlaceholderText('Ingresa el PIN'), { target: { value: '602656' } })
    fireEvent.click(screen.getByText('Continuar →'))

    await waitFor(() => expect(login).toHaveBeenCalledWith('child', '602656', 'es'))
  })

  it('defaults to English on the login request when no locale was ever offered', async () => {
    fetchAvailableLocales.mockResolvedValue([])
    login.mockResolvedValue({ accessToken: 'tok', role: 'child', mfaRequired: false, mfaMethods: [] })
    renderLogin()

    await waitFor(() => expect(fetchAvailableLocales).toHaveBeenCalled())
    fireEvent.click(screen.getByText('Student'))
    fireEvent.change(screen.getByPlaceholderText('Enter PIN'), { target: { value: '602656' } })
    fireEvent.click(screen.getByText('Continue →'))

    await waitFor(() => expect(login).toHaveBeenCalledWith('child', '602656', 'en'))
  })
})

describe('why you are looking at this screen', () => {
  // The whole reason utils/logoutNotice.ts exists: an automated logout used
  // to drop someone here with no explanation, which mid-lesson reads as the
  // app having crashed.
  it('says so, in words, after an inactivity logout', async () => {
    fetchAvailableLocales.mockResolvedValue([])
    setLogoutNotice('inactivity')
    renderLogin()

    await waitFor(() => expect(screen.queryByText(/Logged out due to inactivity/i)).not.toBeNull())
  })

  it('distinguishes a break logout from an ordinary one', async () => {
    fetchAvailableLocales.mockResolvedValue([])
    setLogoutNotice('break-inactivity')
    renderLogin()

    // Different situation, different sentence — docs/CHILD_GUIDE.md promises
    // the child this specific rule, so the notice has to match it.
    await waitFor(() => expect(screen.queryByText(/during your break/i)).not.toBeNull())
    expect(screen.queryByText(/Logged out due to inactivity/i)).toBeNull()
  })

  it('shows nothing at all on an ordinary visit to the login screen', async () => {
    fetchAvailableLocales.mockResolvedValue([])
    renderLogin()

    await waitFor(() => expect(fetchAvailableLocales).toHaveBeenCalled())
    expect(screen.queryByText(/Logged out/i)).toBeNull()
    expect(screen.queryByText(/session ended/i)).toBeNull()
  })

  it('does not re-accuse on the next visit', async () => {
    // Sign in after being timed out, come back later: the notice is spent.
    // A message that reappears is worse than none, because it claims
    // something that isn't true this time.
    fetchAvailableLocales.mockResolvedValue([])
    setLogoutNotice('inactivity')
    renderLogin()
    await waitFor(() => expect(screen.queryByText(/Logged out due to inactivity/i)).not.toBeNull())

    cleanup()
    renderLogin()
    await waitFor(() => expect(fetchAvailableLocales).toHaveBeenCalled())
    expect(screen.queryByText(/Logged out due to inactivity/i)).toBeNull()
  })

  it('is translated, not left as a raw key', async () => {
    fetchAvailableLocales.mockResolvedValue([{ code: 'es', name: 'Spanish (Español)' }])
    setLogoutNotice('inactivity')
    i18n.changeLanguage('es')
    renderLogin()

    await waitFor(() => expect(screen.queryByText(/por inactividad/i)).not.toBeNull())
    expect(screen.queryByText(/common\.loggedOut/)).toBeNull()
  })
})
