/**
 * Bede has to be told the child has just come from another subject.
 *
 * Each subject's history is sent empty, so without previous_subject the
 * server cannot know a change happened: it greeted the child afresh on every
 * subject and opened each one as though the day were only beginning. These
 * pin the three links of that chain on the client: which subject counts as
 * "previous", that it reaches the request body, and that every chat call in
 * SocraticChat passes it.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { streamTutorChat } from './api'
import { previousSubjectOf } from '../store/sessionStore'
import type { SessionConfig, Subject } from '../types'

describe('previousSubjectOf', () => {
  it('is null on the first subject of the sitting', () => {
    expect(previousSubjectOf({ subjectsCompleted: [], currentSubject: 'morning_time' })).toBeNull()
  })

  it('is the subject the child just left', () => {
    expect(previousSubjectOf({
      subjectsCompleted: ['morning_time', 'mathematics'], currentSubject: 'history',
    })).toBe('mathematics')
  })

  it('never names the current subject, which endSession also appends', () => {
    expect(previousSubjectOf({
      subjectsCompleted: ['mathematics', 'history'], currentSubject: 'history',
    })).toBe('mathematics')
  })
})

describe('the request body', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('carries previous_subject, and null when there is none', async () => {
    const bodies: Record<string, unknown>[] = []
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
      bodies.push(JSON.parse(init.body as string))
      return { ok: true, status: 200, body: { getReader: () => ({
        read: async () => ({ done: true, value: undefined }), cancel: async () => {},
      }) } } as unknown as Response
    }))
    const config = { student_name: 'Ada', grade: '4', subjects: [] } as unknown as SessionConfig
    for await (const _ of streamTutorChat(
      'tok', config, 'history' as Subject, [], '[START]', undefined, null, 'morning', null, null, null,
      'mathematics' as Subject,
    )) { /* drain */ }
    for await (const _ of streamTutorChat('tok', config, 'history' as Subject, [], '[START]')) { /* drain */ }
    expect(bodies[0].previous_subject).toBe('mathematics')
    expect(bodies[1].previous_subject).toBeNull()
  })
})

describe('SocraticChat', () => {
  it('passes the previous subject on every chat call', () => {
    const source = readFileSync(join(__dirname, '../components/SocraticChat.tsx'), 'utf8')
    const calls = source.split('streamTutorChat(').slice(1).map((c) => c.split('\n    )')[0])
    expect(calls.length).toBeGreaterThanOrEqual(3)
    for (const call of calls) expect(call).toContain('previousSubjectOf(')
  })
})
