/**
 * A dropped connection must not cost a child their turn.
 *
 * From a real 5G trace, mid-lesson: `POST /tutor/chat` rejected with
 * `TypeError: Load failed` after 12.9 seconds, the child's answer was
 * discarded, and the only thing that spoke afterwards was the 60-second
 * idle timer sending [CONTINUE] — which invites them to go on as though
 * they had never answered. Nothing retried.
 *
 * These guards pin the retry AND the three things it must refuse to do,
 * because an over-eager retry is its own bug: a duplicated model call, a
 * sentence restarted under a reader mid-way through it, or a request
 * reissued for a child who has already left.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { streamTutorChat } from './api'
import { startVoiceStream, pushVoiceStreamChunk, finishVoiceStream, streamVoiceEvents } from './voiceApi'
import type { SessionConfig, StreamChunk, Subject } from '../types'

const CONFIG = { student_name: 'Ada', grade: '4', subjects: [] } as unknown as SessionConfig
const SUBJECT = 'mathematics' as Subject

/** A Response whose body streams these already-encoded SSE lines. */
function sseResponse(lines: string[], ok = true, status = 200): Response {
  let i = 0
  const encoder = new TextEncoder()
  return {
    ok,
    status,
    body: {
      getReader: () => ({
        read: async () =>
          i < lines.length
            ? { done: false, value: encoder.encode(lines[i++]) }
            : { done: true, value: undefined },
        cancel: async () => {},
      }),
    },
  } as unknown as Response
}

const REPLY = [
  'data: {"type":"text","content":"Tell me what you remember."}\n',
  'data: {"type":"done"}\n',
]

/** Safari's own wording for a transport failure — the reported case. */
function loadFailed() {
  return new TypeError('Load failed')
}

async function collect(gen: AsyncGenerator<StreamChunk>): Promise<StreamChunk[]> {
  const out: StreamChunk[] = []
  for await (const c of gen) out.push(c)
  return out
}

function run(signal?: AbortSignal) {
  return streamTutorChat('tok', CONFIG, SUBJECT, [], 'I was coughing the whole day', signal)
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('real HTTP path deadlines and voice cancellation', () => {
  it('allows 120 seconds of recording with SSE keepalives but no transcript data', async () => {
    vi.useFakeTimers()
    let stream!: ReadableStreamDefaultController<Uint8Array>
    fetchMock.mockResolvedValue(new Response(new ReadableStream({ start: (controller) => { stream = controller } })))
    const events = streamVoiceEvents('tok', 'synthetic')
    const first = events.next()
    const encoder = new TextEncoder()
    for (let seconds = 0; seconds < 120; seconds += 30) {
      await vi.advanceTimersByTimeAsync(30_000)
      stream.enqueue(encoder.encode(': ping\n\n'))
      await vi.advanceTimersByTimeAsync(0)
    }
    stream.enqueue(encoder.encode('data: {"type":"final","text":"Synthetic narration"}\n'))
    await expect(first).resolves.toEqual({ done: false, value: { type: 'final', text: 'Synthetic narration' } })
    await events.return(undefined)
  })
  it('bounds chat before headers without replaying a potentially accepted turn', async () => {
    vi.useFakeTimers()
    fetchMock.mockImplementation((_url: string, init: RequestInit) => new Promise<Response>((_, reject) => {
      init.signal?.addEventListener('abort', () => reject(loadFailed()), { once: true })
    }))
    const pending = collect(run())
    const rejected = expect(pending).rejects.toThrow('Request timed out')
    await vi.advanceTimersByTimeAsync(60_000)
    await rejected
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect((fetchMock.mock.calls[0][1].signal as AbortSignal).aborted).toBe(true)
  })

  it.each(['start', 'chunk', 'finish', 'events'])('bounds a hanging voice %s request', async (stage) => {
    vi.useFakeTimers()
    fetchMock.mockImplementation(() => new Promise<Response>(() => {}))
    const pending = stage === 'start' ? startVoiceStream('tok')
      : stage === 'chunk' ? pushVoiceStreamChunk('tok', 'synthetic', new Blob(['pcm']))
      : stage === 'finish' ? finishVoiceStream('tok', 'synthetic')
      : streamVoiceEvents('tok', 'synthetic').next()
    const rejected = expect(pending).rejects.toThrow('Request timed out')
    await vi.advanceTimersByTimeAsync(30_000)
    await rejected
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect((fetchMock.mock.calls[0][1].signal as AbortSignal).aborted).toBe(true)
    expect(fetchMock.mock.calls[0][1].headers.Authorization.split(' ')).toEqual(['Bearer', 'tok'])
  })

  it('also bounds the start response JSON body', async () => {
    vi.useFakeTimers()
    fetchMock.mockResolvedValue({ ok: true, json: () => new Promise(() => {}) })
    const pending = startVoiceStream('tok')
    const rejected = expect(pending).rejects.toThrow('Request timed out')
    await vi.advanceTimersByTimeAsync(30_000)
    await rejected
  })

  it.each([401, 403, 404, 423])('does not replay a voice chunk refused with %s', async (status) => {
    fetchMock.mockResolvedValue(new Response('', { status }))
    await expect(pushVoiceStreamChunk('tok', 'synthetic', new Blob(['pcm']))).rejects.toThrow()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('cancels the real SSE body reader when the voice turn is canceled', async () => {
    const canceled = vi.fn()
    fetchMock.mockResolvedValue(new Response(new ReadableStream({ cancel: canceled })))
    const controller = new AbortController()
    const events = streamVoiceEvents('tok', 'synthetic', controller.signal)
    const next = events.next()
    const rejected = expect(next).rejects.toThrow('Aborted')
    await Promise.resolve()
    await Promise.resolve()
    controller.abort()
    await rejected
    expect(canceled).toHaveBeenCalledTimes(1)
  })

  it('runs synthetic start, chunk, finish, and events through the authenticated real helpers', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith('/start')) return new Response('{"session_id":"synthetic"}')
      if (url.endsWith('/events')) return sseResponse([
        'data: {"type":"final","text":"Synthetic words"}\n',
        'data: {"type":"done"}\n',
      ])
      return new Response('{}')
    })
    const session = await startVoiceStream('tok', 'en')
    await pushVoiceStreamChunk('tok', session, new Blob(['pcm']))
    await finishVoiceStream('tok', session)
    const out = []
    for await (const event of streamVoiceEvents('tok', session)) out.push(event)
    expect(out).toEqual([{ type: 'final', text: 'Synthetic words' }, { type: 'done' }])
    expect(fetchMock.mock.calls.map((call) => (call[0] as string).split('/').pop())).toEqual(['start', 'chunk', 'finish', 'events'])
    for (const call of fetchMock.mock.calls) expect(call[1].headers.Authorization.split(' ')).toEqual(['Bearer', 'tok'])
  })
})

describe('a connection that drops before Bede answers', () => {
  it('retries, and the child gets the reply they would have lost', async () => {
    fetchMock
      .mockRejectedValueOnce(loadFailed())
      .mockResolvedValueOnce(sseResponse(REPLY))

    const chunks = await collect(run())

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(chunks.map((c) => c.type)).toEqual(['text', 'done'])
  })

  it('sends the child’s own words again, not an empty turn', async () => {
    // The retry must reissue the SAME message. A retry that dropped the
    // child's text would produce a reply to nothing, which is the exact
    // failure the idle [CONTINUE] sentinel already causes.
    fetchMock
      .mockRejectedValueOnce(loadFailed())
      .mockResolvedValueOnce(sseResponse(REPLY))

    await collect(run())

    const bodies = fetchMock.mock.calls.map((c) => JSON.parse(c[1].body))
    expect(bodies).toHaveLength(2)
    expect(bodies[0].child_message).toBe('I was coughing the whole day')
    expect(bodies[1]).toEqual(bodies[0])
  })

  it('gives up rather than retrying forever, and reports the real failure', async () => {
    fetchMock.mockRejectedValue(loadFailed())

    await expect(collect(run())).rejects.toThrow('Load failed')
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })
})

describe('what it deliberately will not retry', () => {
  it('leaves a refusal the server actually made alone', async () => {
    // A 4xx/5xx is a decision, not a dropped packet. Repeating it just
    // asks to be refused twice and spends a family's tokens doing it.
    fetchMock.mockResolvedValue(sseResponse([], false, 500))

    await expect(collect(run())).rejects.toThrow(/Tutor request failed/)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('a retry is a fresh request the server re-authorizes, and its refusal ends the retries', async () => {
    // G1: the server resolves the educator's grant again on every request,
    // so a retry after revocation is refused (401 once the credential
    // version moved, 404 once the learner is unassigned). Neither refusal
    // may be retried: the turn ends there.
    for (const status of [401, 404]) {
      fetchMock.mockReset()
      fetchMock
        .mockRejectedValueOnce(loadFailed())
        .mockResolvedValueOnce(sseResponse([], false, status))
      await expect(collect(run())).rejects.toThrow(/Tutor request failed/)
      expect(fetchMock).toHaveBeenCalledTimes(2)
    }
  })

  it('does not restart a reply the child is already reading', async () => {
    // Fails AFTER the first chunk reached the caller. Retrying here would
    // replay text already on screen, mid-sentence.
    const encoder = new TextEncoder()
    let read = 0
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      body: {
        getReader: () => ({
          read: async () => {
            if (read++ === 0) {
              return { done: false, value: encoder.encode('data: {"type":"text","content":"Well"}\n') }
            }
            throw loadFailed()
          },
          cancel: async () => {},
        }),
      },
    } as unknown as Response)

    const seen: StreamChunk[] = []
    await expect(
      (async () => {
        for await (const c of run()) seen.push(c)
      })(),
    ).rejects.toThrow('Load failed')

    expect(seen).toHaveLength(1)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does not reissue a request for a child who has already left', async () => {
    const controller = new AbortController()
    fetchMock.mockImplementation(async () => {
      controller.abort()
      throw loadFailed()
    })

    await expect(collect(run(controller.signal))).rejects.toThrow('Aborted')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
