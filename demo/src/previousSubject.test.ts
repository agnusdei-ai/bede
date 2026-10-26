/**
 * The demo tells Bede which subject the visitor just came from, so Bede
 * marks the change instead of greeting them again (see the backend's
 * _subject_transition_note). Pins the request body and that ChatScreen
 * passes its tracked previous subject to every chat call.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { streamTutorChat, type Subject } from './api'
import type { SessionConfig } from './api'

describe('previous_subject in the demo', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('reaches the request body, and is null when there is none', async () => {
    const bodies: Record<string, unknown>[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
      bodies.push(JSON.parse(init.body as string))
      return { ok: true, status: 200, body: { getReader: () => ({
        read: async () => ({ done: true, value: undefined }), cancel: async () => {},
      }) } } as unknown as Response
    }))
    const config = { student_name: 'Ada', grade: '4', subjects: [] } as unknown as SessionConfig
    for await (const _ of streamTutorChat(
      'tok', config, 'history' as Subject, [], '[START]', null, undefined, 'morning', 'mathematics' as Subject,
    )) { /* drain */ }
    for await (const _ of streamTutorChat('tok', config, 'history' as Subject, [], '[START]', null)) { /* drain */ }
    expect(bodies[0].previous_subject).toBe('mathematics')
    expect(bodies[1].previous_subject).toBeNull()
  })

  it('is passed by ChatScreen on every chat call', () => {
    const source = readFileSync(join(__dirname, 'App.tsx'), 'utf8')
    const calls = source.split('runChat(subject,').slice(1)
    expect(calls.length).toBeGreaterThanOrEqual(1)
    for (const call of calls) expect(call.split('\n')[0]).toContain('previousSubjectRef.current')
    expect(source).toContain('streamTutorChat(token, config!, subject, history, childMessage, drawingImage, signal, timeOfDay, previousSubject)')
  })
})
