/**
 * Regression coverage for a real bug found while investigating a report
 * that the "Privacy Notice" link on the entry screen did nothing when
 * pressed: `<Trans i18nKey="codeScreen.privacyNotice" components={{ link:
 * <a .../> }} />` used `link` as its custom tag name — which collides with
 * `<link>`, a real, void HTML element (`<link rel="stylesheet">`). Trans's
 * underlying string parser treats any tag name matching a known HTML void
 * element as self-closing regardless of the custom component it's mapped
 * to, so "Privacy Notice" rendered as plain text AFTER an empty, invisible
 * anchor/button rather than as its children — visible, but never actually
 * inside the clickable element. Confirmed via a real browser DOM
 * inspection before fixing (innerHTML showed `<button ...></button>Privacy
 * Notice`, text and element as unrelated siblings), not just reasoning
 * about it. Renamed to `privacyLink` (not a reserved element name) fixes
 * it; this test guards against it regressing back to a colliding name.
 */
import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { fetchAvailableLocales } = vi.hoisted(() => ({
  fetchAvailableLocales: vi.fn(),
}))

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  return { ...actual, fetchAvailableLocales }
})

import { CodeScreen } from './App'

beforeEach(() => {
  fetchAvailableLocales.mockResolvedValue([])
  localStorage.clear()
})

afterEach(() => {
  cleanup()
})

describe('CodeScreen privacy notice link', () => {
  it('renders "Privacy Notice" as the CONTENT of the clickable element, not as trailing sibling text', async () => {
    await act(async () => {
      render(<CodeScreen onLoggedIn={vi.fn()} />)
    })

    const privacyButton = screen.getByRole('button', { name: 'Privacy Notice' })
    expect(privacyButton).toBeTruthy()
    // The bug specifically left the button empty with "Privacy Notice" as
    // a sibling text node right after it — asserting on textContent alone
    // wouldn't catch that (it reads across sibling boundaries too), so
    // check the element's own direct content instead.
    expect(privacyButton.textContent).toBe('Privacy Notice')
  })

  it('opens the consent modal for review when pressed, even after consent was already given', async () => {
    localStorage.setItem('bede-demo-consent-v2', 'true')

    await act(async () => {
      render(<CodeScreen onLoggedIn={vi.fn()} />)
    })

    // Already consented — modal shouldn't be showing on load.
    expect(screen.queryByText('Before you begin')).toBeNull()

    const privacyButton = screen.getByRole('button', { name: 'Privacy Notice' })
    await act(async () => {
      privacyButton.click()
    })

    expect(screen.getByText('Before you begin')).toBeTruthy()
  })
})
