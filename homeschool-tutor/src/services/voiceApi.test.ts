/**
 * G1 voice binding, client half: an educator's voice session must name its
 * learner, because the server binds the session to that learner's grant and
 * refuses an educator session that names none (homeschool-api's
 * routers/voice.py). These assert the request body actually sent.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { startVoiceStream, voiceScopeFor } from './voiceApi'

afterEach(() => {
  vi.unstubAllGlobals()
})

function captureFetch() {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ session_id: 'sess' }), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('voiceScopeFor', () => {
  it('scopes an educator session to its loaded learner', () => {
    expect(voiceScopeFor('educator', { student_name: 'Synthetic Learner One' }))
      .toEqual({ student_name: 'Synthetic Learner One' })
  })

  it('sends nothing for every other role, or with no learner loaded', () => {
    expect(voiceScopeFor('parent', { student_name: 'Synthetic Learner One' })).toBeUndefined()
    expect(voiceScopeFor('child', { student_name: 'Synthetic Learner One' })).toBeUndefined()
    expect(voiceScopeFor(null, null)).toBeUndefined()
    expect(voiceScopeFor('educator', null)).toBeUndefined()
  })
})

describe('startVoiceStream request body', () => {
  it('carries the learner scope beside the language', async () => {
    const fetchMock = captureFetch()
    await startVoiceStream('tok', 'en', { learner_id: '11111111-1111-4111-8111-111111111111' })
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(JSON.parse(init.body as string)).toEqual({
      language: 'en', learner_id: '11111111-1111-4111-8111-111111111111',
    })
  })

  it('sends only the language when there is no scope', async () => {
    const fetchMock = captureFetch()
    await startVoiceStream('tok', 'es')
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(JSON.parse(init.body as string)).toEqual({ language: 'es' })
  })
})
