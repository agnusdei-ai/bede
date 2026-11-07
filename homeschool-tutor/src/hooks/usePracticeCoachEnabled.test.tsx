import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// PRACTICE_COACH_ENABLED (issue #763): the app shows Practice Coach's cards
// only when the server says it is on. Drives the real EducatorDesk call site
// and the real status fetch.

const m = vi.hoisted(() => ({
  fetchInstructorRoster: vi.fn(),
  fetchInstructorFrameworks: vi.fn(),
  fetchMyEducatorPasskeys: vi.fn(),
  fetchEducatorQuizOptions: vi.fn(),
  fetchPracticeCoachEnabled: vi.fn(),
}))
vi.mock('../services/api', async (original) => ({
  ...await original<typeof import('../services/api')>(),
  ...m,
}))
vi.mock('../store/sessionStore', () => ({
  useSessionStore: () => ({ token: 'educator-token', setSessionConfig: vi.fn(), startSession: vi.fn(), logout: vi.fn() }),
}))
vi.mock('react-router', async (original) => ({
  ...await original<typeof import('react-router')>(),
  useNavigate: () => vi.fn(),
}))

import i18n from '../i18n'
import EducatorDesk from '../pages/EducatorDesk'

beforeEach(async () => {
  vi.clearAllMocks()
  await i18n.changeLanguage('en')
  m.fetchInstructorRoster.mockResolvedValue([])
  m.fetchInstructorFrameworks.mockResolvedValue([])
  m.fetchMyEducatorPasskeys.mockResolvedValue([])
  m.fetchEducatorQuizOptions.mockResolvedValue({
    subjects: [{ id: 'history', display_name: 'History' }], grades: ['4'], kinds: ['quiz'], levels: ['on_level'],
    max_questions: 50, route: { local_available: true, cloud_provider: null, draft_provider: null },
  })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('Practice Coach switch in the app', () => {
  it('shows the quiz tools when Practice Coach is on', async () => {
    m.fetchPracticeCoachEnabled.mockResolvedValue(true)
    render(<MemoryRouter><EducatorDesk /></MemoryRouter>)
    expect(await screen.findByRole('region', { name: 'Make a quiz or exam' })).toBeTruthy()
    expect(m.fetchPracticeCoachEnabled).toHaveBeenCalledWith('educator-token')
  })

  it('hides every quiz tool when Practice Coach is off', async () => {
    m.fetchPracticeCoachEnabled.mockResolvedValue(false)
    render(<MemoryRouter><EducatorDesk /></MemoryRouter>)
    await waitFor(() => expect(m.fetchPracticeCoachEnabled).toHaveBeenCalled())
    await screen.findByText(/Choose a learner/)
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByRole('region', { name: 'Make a quiz or exam' })).toBeNull()
    expect(m.fetchEducatorQuizOptions).not.toHaveBeenCalled()
  })
})

describe('fetchPracticeCoachEnabled', () => {
  const real = async () =>
    (await vi.importActual<typeof import('../services/api')>('../services/api')).fetchPracticeCoachEnabled
  const respond = (status: number, body?: unknown) =>
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(body === undefined ? null : JSON.stringify(body), { status })))

  it('is on only for a clear yes', async () => {
    respond(200, { enabled: true })
    expect(await (await real())('t')).toBe(true)
    respond(200, { enabled: false })
    expect(await (await real())('t')).toBe(false)
    respond(200, { enabled: 'yes' })
    expect(await (await real())('t')).toBe(false)
  })

  it('treats a server without the route as on, since Coach always existed there', async () => {
    respond(404)
    expect(await (await real())('t')).toBe(true)
  })

  it('is off when the answer cannot be confirmed', async () => {
    respond(500)
    expect(await (await real())('t')).toBe(false)
    respond(401)
    expect(await (await real())('t')).toBe(false)
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Load failed')))
    expect(await (await real())('t')).toBe(false)
  })

  it('asks the status route with the session token', async () => {
    respond(200, { enabled: true })
    await (await real())('tok')
    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toBe('/api/practice/status')
    expect(init.headers.Authorization).toBe('Bearer tok')
  })
})
