/**
 * What a child has typed but not sent survives a reload (utils/chatDraft.ts).
 *
 * The utility is tested on its own below, and the chat box is rendered for
 * real above it, because a draft store nothing reads or writes would pass
 * every unit test and still lose a child's narration to the next reload.
 */
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import { useSessionStore } from '../store/sessionStore'
import type { SessionConfig } from '../types'
import SocraticChat from './SocraticChat'
import {
  DRAFT_KEY_PREFIX, MAX_DRAFT_AGE_MS, MAX_DRAFT_CHARS, clearAllDrafts, loadDraft, saveDraft,
} from '../utils/chatDraft'

const CONFIG = {
  student_name: 'Ada',
  grade: '4',
  grade_stage: '3-5',
  subjects: ['living_books'],
} as unknown as SessionConfig

function signIn() {
  act(() => {
    useSessionStore.getState().logout()
    useSessionStore.getState().setAuth('child-token', 'child')
    useSessionStore.getState().setSessionConfig(CONFIG)
    useSessionStore.getState().startSession()
  })
}

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

describe('the chat box keeps unsent words', () => {
  it('restores what the child typed after the page reloads', () => {
    const first = render(<SocraticChat />)
    fireEvent.change(box(), { target: { value: 'The Nile flooded every summer and' } })
    first.unmount() // the reload

    render(<SocraticChat />)
    expect(box().value).toBe('The Nile flooded every summer and')
  })

  it('forgets the draft once it is sent', async () => {
    render(<SocraticChat />)
    await screen.findByText('Hello.') // the opener has finished
    fireEvent.change(box(), { target: { value: 'The river was the Nile.' } })
    expect(loadDraft('Ada')).toBe('The river was the Nile.')
    fireEvent.keyDown(box(), { key: 'Enter' })
    await screen.findByText('The river was the Nile.')
    expect(loadDraft('Ada')).toBe('')
  })

  it('never shows one child\'s draft to the next person who signs in', () => {
    const first = render(<SocraticChat />)
    fireEvent.change(box(), { target: { value: 'Ada was halfway through this' } })
    first.unmount()

    signIn() // logout, then the next person signs in on the same tablet
    render(<SocraticChat />)
    expect(box().value).toBe('')
  })
})

describe('chatDraft', () => {
  it('keeps one student\'s draft per tab', () => {
    saveDraft('Ada', 'Ada text')
    saveDraft('Ben', 'Ben text')
    expect(loadDraft('Ben')).toBe('Ben text')
    expect(loadDraft('Ada')).toBe('')
  })

  it('drops a draft that is too old instead of restoring it', () => {
    saveDraft('Ada', 'yesterday', 1_000)
    expect(loadDraft('Ada', 1_000 + MAX_DRAFT_AGE_MS + 1)).toBe('')
  })

  it('does not store text past the cap', () => {
    saveDraft('Ada', 'x'.repeat(MAX_DRAFT_CHARS + 1))
    expect(loadDraft('Ada')).toBe('')
  })

  it('treats a malformed entry as no draft', () => {
    sessionStorage.setItem(DRAFT_KEY_PREFIX + 'Ada', '{"text": 5}')
    expect(loadDraft('Ada')).toBe('')
    sessionStorage.setItem(DRAFT_KEY_PREFIX + 'Ada', 'not json')
    expect(loadDraft('Ada')).toBe('')
  })

  it('is silent when storage refuses', () => {
    const broken = {
      length: 0, key: () => null, getItem: () => { throw new Error('SecurityError') },
      setItem: () => { throw new Error('QuotaExceededError') }, removeItem: () => {},
    } as unknown as Storage
    expect(() => saveDraft('Ada', 'text', Date.now(), broken)).not.toThrow()
    expect(loadDraft('Ada', Date.now(), broken)).toBe('')
    expect(() => clearAllDrafts(broken)).not.toThrow()
  })

  it('clears every draft at sign-out and leaves other storage alone', () => {
    saveDraft('Ada', 'text')
    sessionStorage.setItem('unrelated', 'keep')
    clearAllDrafts()
    expect(loadDraft('Ada')).toBe('')
    expect(sessionStorage.getItem('unrelated')).toBe('keep')
  })
})
