/**
 * When the server refuses a turn until a parent finishes the consent step,
 * the child sees one friendly sentence pointing at Parent Setup: not a raw
 * error, and never legal wording.
 */
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { useSessionStore } from '../store/sessionStore'
import type { SessionConfig } from '../types'
import SocraticChat from './SocraticChat'

const CONFIG = {
  student_name: 'Ada',
  grade: '4',
  grade_stage: '3-5',
  subjects: ['living_books'],
} as unknown as SessionConfig

function refusal(): Response {
  return {
    ok: false,
    status: 403,
    json: async () => ({
      detail: { error: 'parental_consent_required', message: 'Consent needed', parent_action: 'open_parent_setup' },
    }),
  } as unknown as Response
}

beforeEach(() => {
  i18n.changeLanguage('en')
  sessionStorage.clear()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(refusal()))
  // jsdom implements no scrolling.
  Element.prototype.scrollIntoView = vi.fn()
  act(() => {
    useSessionStore.getState().logout()
    useSessionStore.getState().setAuth('child-token', 'child')
    useSessionStore.getState().setSessionConfig(CONFIG)
    useSessionStore.getState().startSession()
  })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

describe('child-facing consent refusal', () => {
  it('shows the friendly parent-step message in English', async () => {
    render(<SocraticChat />)
    expect(
      await screen.findByText(/A parent needs to finish one quick step in Parent Setup\. Please ask them to open it\./),
    ).toBeTruthy()
    expect(screen.queryByText(/COPPA|consent|failed|403/i)).toBeNull()
  })

  it('shows it in Spanish too', async () => {
    i18n.changeLanguage('es')
    render(<SocraticChat />)
    expect(await screen.findByText(/Un adulto necesita completar un paso rápido/)).toBeTruthy()
  })
})
