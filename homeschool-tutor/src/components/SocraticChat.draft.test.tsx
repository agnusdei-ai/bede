/**
 * What a child has typed but not sent survives a reload (utils/chatDraft.ts),
 * and never reaches anyone else.
 *
 * The chat box is rendered for real, because a draft store nothing reads or
 * writes would pass every unit test and still lose a child's narration to the
 * next reload. The cases that matter most are the ones where the chat stays
 * on screen while who it belongs to changes: a different learner, a different
 * sign-in, a forced sign-out.
 */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { useSessionStore } from '../store/sessionStore'
import type { SessionConfig } from '../types'
import SocraticChat from './SocraticChat'
import {
  DRAFT_KEY_PREFIX, MAX_CLOCK_SKEW_MS, MAX_DRAFT_AGE_MS, MAX_DRAFT_CHARS,
  clearAllDrafts, draftOwnerFor, loadDraft, saveDraft,
} from '../utils/chatDraft'

function config(student: string) {
  return { student_name: student, grade: '4', grade_stage: '3-5', subjects: ['living_books'] } as unknown as SessionConfig
}

function signIn(student = 'Ada', token = 'child-token-1') {
  act(() => {
    useSessionStore.getState().logout()
    useSessionStore.getState().setAuth(token, 'child')
    useSessionStore.getState().setSessionConfig(config(student))
    useSessionStore.getState().startSession()
  })
}

const owner = (student = 'Ada', token = 'child-token-1') => draftOwnerFor('child', token, student)

beforeEach(() => {
  i18n.changeLanguage('en')
  sessionStorage.clear()
  // Every turn, the opener included, ends at once; these tests are about the box.
  vi.stubGlobal('fetch', vi.fn(async () => new Response('data: {"type":"text","content":"Hello."}\n\ndata: {"type":"done"}\n\n', { status: 200 })))
  Element.prototype.scrollIntoView = vi.fn()
  signIn()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

function box(): HTMLTextAreaElement {
  return screen.getAllByRole('textbox').at(-1) as HTMLTextAreaElement
}

function type(text: string) {
  fireEvent.change(box(), { target: { value: text } })
}

describe('the chat box keeps unsent words', () => {
  it('restores what the child typed after the page reloads', () => {
    const first = render(<SocraticChat />)
    type('The Nile flooded every summer and')
    first.unmount() // the reload: same tab, same sign-in

    render(<SocraticChat />)
    expect(box().value).toBe('The Nile flooded every summer and')
  })

  it('forgets the draft once it is sent', async () => {
    render(<SocraticChat />)
    await screen.findByText('Hello.') // the opener has finished
    type('The river was the Nile.')
    expect(loadDraft(owner())).toBe('The river was the Nile.')
    fireEvent.keyDown(box(), { key: 'Enter' })
    await screen.findByText('The river was the Nile.')
    expect(loadDraft(owner())).toBe('')
  })

  it('never shows one child\'s draft to the next person who signs in', () => {
    const first = render(<SocraticChat />)
    type('Ada was halfway through this')
    first.unmount()

    signIn('Ben', 'child-token-2')
    render(<SocraticChat />)
    expect(box().value).toBe('')
  })
})

describe('when who the chat belongs to changes while it stays open', () => {
  it('a different learner never sees, or inherits, the previous learner\'s words', () => {
    render(<SocraticChat />)
    type('Ada\'s unsent sentence')

    act(() => { useSessionStore.getState().setSessionConfig(config('Ben')) })
    expect(box().value).toBe('', ) // not shown to Ben
    expect(loadDraft(owner('Ben'))).toBe('') // not saved as Ben's
    type('Ben writes his own')
    expect(loadDraft(owner('Ben'))).toBe('Ben writes his own')
  })

  it('a second account with a learner of the same name finds nothing', () => {
    const first = render(<SocraticChat />)
    type('typed under the first sign-in')
    first.unmount()

    // A different household signs in on the same tablet, same learner name.
    act(() => {
      useSessionStore.getState().setAuth('another-household-token', 'child')
      useSessionStore.getState().setSessionConfig(config('Ada'))
    })
    render(<SocraticChat />)
    expect(box().value).toBe('')
  })

  it('a forced sign-out clears the draft, and nothing writes it back', () => {
    render(<SocraticChat />)
    type('about to be signed out')
    expect(loadDraft(owner())).toBe('about to be signed out')

    // What the 401 interceptor and the idle timeout both do.
    act(() => { useSessionStore.getState().logout() })
    expect(Object.keys(sessionStorage).filter((k) => k.startsWith(DRAFT_KEY_PREFIX))).toEqual([])
  })
})

describe('chatDraft', () => {
  it('names an owner only when there is a role, a sign-in and a learner, and never stores the token', () => {
    expect(draftOwnerFor('child', 'tok', 'Ada')).toMatch(/^child:[0-9a-f]{8}:Ada$/)
    expect(draftOwnerFor('child', 'tok', 'Ada')).not.toContain('tok')
    expect(draftOwnerFor('child', 'tok-a', 'Ada')).not.toBe(draftOwnerFor('child', 'tok-b', 'Ada'))
    expect(draftOwnerFor(null, 'tok', 'Ada')).toBe('')
    expect(draftOwnerFor('child', null, 'Ada')).toBe('')
    expect(draftOwnerFor('child', 'tok', '')).toBe('')
  })

  it('keeps nothing for an empty owner', () => {
    saveDraft('', 'text')
    expect(Object.keys(sessionStorage).filter((k) => k.startsWith(DRAFT_KEY_PREFIX))).toEqual([])
  })

  it('keeps one owner\'s draft per tab', () => {
    saveDraft(owner('Ada'), 'Ada text')
    saveDraft(owner('Ben'), 'Ben text')
    expect(loadDraft(owner('Ben'))).toBe('Ben text')
    expect(loadDraft(owner('Ada'))).toBe('')
  })

  it('drops a draft that is too old instead of restoring it', () => {
    saveDraft(owner(), 'yesterday', 1_000)
    expect(loadDraft(owner(), 1_000 + MAX_DRAFT_AGE_MS + 1)).toBe('')
  })

  it.each([
    ['stamped in the future', (now: number) => now + MAX_CLOCK_SKEW_MS + 1],
    ['stamped at zero', () => 0],
    ['stamped negative', () => -5],
  ])('drops a draft %s', (_label, stamp) => {
    const now = 1_000_000
    sessionStorage.setItem(DRAFT_KEY_PREFIX + owner(), JSON.stringify({ text: 'x', savedAt: stamp(now) }))
    expect(loadDraft(owner(), now)).toBe('')
  })

  it('drops a draft whose time is not a finite number', () => {
    // JSON cannot carry Infinity or NaN; they arrive as strings or null.
    for (const savedAt of ['"Infinity"', 'null', '"1700000000000"']) {
      sessionStorage.setItem(DRAFT_KEY_PREFIX + owner(), `{"text":"x","savedAt":${savedAt}}`)
      expect(loadDraft(owner())).toBe('')
    }
  })

  it('tolerates a little clock skew', () => {
    const now = 1_000_000
    saveDraft(owner(), 'fine', now + MAX_CLOCK_SKEW_MS - 1)
    expect(loadDraft(owner(), now)).toBe('fine')
  })

  it('does not store text past the cap', () => {
    saveDraft(owner(), 'x'.repeat(MAX_DRAFT_CHARS + 1))
    expect(loadDraft(owner())).toBe('')
  })

  it('treats a malformed entry as no draft', () => {
    sessionStorage.setItem(DRAFT_KEY_PREFIX + owner(), '{"text": 5}')
    expect(loadDraft(owner())).toBe('')
    sessionStorage.setItem(DRAFT_KEY_PREFIX + owner(), 'not json')
    expect(loadDraft(owner())).toBe('')
  })

  it('is silent when storage refuses', () => {
    const broken = {
      length: 0, key: () => null, getItem: () => { throw new Error('SecurityError') },
      setItem: () => { throw new Error('QuotaExceededError') }, removeItem: () => {},
    } as unknown as Storage
    expect(() => saveDraft(owner(), 'text', Date.now(), broken)).not.toThrow()
    expect(loadDraft(owner(), Date.now(), broken)).toBe('')
    expect(() => clearAllDrafts(broken)).not.toThrow()
  })

  it('clears every draft at sign-out and leaves other storage alone', () => {
    saveDraft(owner(), 'text')
    sessionStorage.setItem('unrelated', 'keep')
    clearAllDrafts()
    expect(loadDraft(owner())).toBe('')
    expect(sessionStorage.getItem('unrelated')).toBe('keep')
  })
})
