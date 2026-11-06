/**
 * The demo runs the product's network resilience, not a copy of it.
 *
 * The trace this was written from IS a demo trace (bede-demo-api.onrender.com
 * over 5G), so the demo is the surface where a dropped turn was actually
 * seen — and it is the one a prospective family judges Bede by. The same
 * four properties the app's own `services/tutorRetry.test.ts` pins are
 * asserted here against the demo's own streamTutorChat.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { streamTutorChat, startVoiceStream, pushVoiceStreamChunk, finishVoiceStream, streamVoiceEvents } from './api'
import type { SessionConfig, StreamChunk, Subject } from './api'

const CONFIG = { student_name: 'Guest', grade: '4', subjects: [] } as unknown as SessionConfig
const SUBJECT = 'mathematics' as Subject

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

const loadFailed = () => new TypeError('Load failed')

async function collect(gen: AsyncGenerator<StreamChunk>): Promise<StreamChunk[]> {
  const out: StreamChunk[] = []
  for await (const c of gen) out.push(c)
  return out
}

function run(signal?: AbortSignal) {
  return streamTutorChat('tok', CONFIG, SUBJECT, [], 'I was coughing the whole day', null, signal)
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
  it('retries, and the visitor gets the reply they would have lost', async () => {
    fetchMock.mockRejectedValueOnce(loadFailed()).mockResolvedValueOnce(sseResponse(REPLY))
    const chunks = await collect(run())
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(chunks.map((c) => c.type)).toEqual(['text', 'done'])
  })

  it('gives up rather than retrying forever', async () => {
    fetchMock.mockRejectedValue(loadFailed())
    await expect(collect(run())).rejects.toThrow('Load failed')
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })
})

describe('what it deliberately will not retry', () => {
  it('leaves a refusal the server actually made alone', async () => {
    fetchMock.mockResolvedValue(sseResponse([], false, 500))
    await expect(collect(run())).rejects.toThrow(/Tutor request failed/)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('never retries an ended trial session, however the connection behaved', async () => {
    // A 401 here means the demo code expired. Retrying it would spend two
    // more round trips to be told the same thing, and delay the visitor
    // reaching the screen that actually helps them (generate a new code).
    fetchMock.mockResolvedValue(sseResponse([], false, 401))
    await expect(collect(run())).rejects.toThrow(/session has ended/i)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does not restart a reply the visitor is already reading', async () => {
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

  it('does not reissue a request for a visitor who has already left', async () => {
    const controller = new AbortController()
    fetchMock.mockImplementation(async () => {
      controller.abort()
      throw loadFailed()
    })
    await expect(collect(run(controller.signal))).rejects.toThrow('Aborted')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

// A real demo trace: headers arrived, then no byte at all for 60 seconds, and
// the turn failed. The server sends a keep-alive every 15 seconds while it
// works, so total silence means the connection is gone and asking again is
// the only way the visitor gets an answer.
describe('a connection that goes silent', () => {
  function silentResponse(): Response {
    return {
      ok: true,
      status: 200,
      body: { getReader: () => ({ read: () => new Promise(() => {}), cancel: async () => {} }) },
    } as unknown as Response
  }

  function timedResponse(steps: Array<{ afterMs: number; line: string }>): Response {
    let i = 0
    const encoder = new TextEncoder()
    return {
      ok: true,
      status: 200,
      body: {
        getReader: () => ({
          read: () => {
            if (i >= steps.length) return Promise.resolve({ done: true, value: undefined })
            const step = steps[i++]
            return new Promise((resolve) => setTimeout(() => resolve({ done: false, value: encoder.encode(step.line) }), step.afterMs))
          },
          cancel: async () => {},
        }),
      },
    } as unknown as Response
  }

  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('asks again and the visitor gets the reply', async () => {
    fetchMock.mockResolvedValueOnce(silentResponse()).mockResolvedValueOnce(sseResponse(REPLY))
    const pending = collect(run())
    await vi.advanceTimersByTimeAsync(40_000)
    const chunks = await pending
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(chunks[0]).toMatchObject({ type: 'text', content: 'Tell me what you remember.' })
  })

  it('waits patiently while keep-alives arrive', async () => {
    const pings = Array.from({ length: 5 }, () => ({ afterMs: 15_000, line: ': ping\n' }))
    fetchMock.mockResolvedValueOnce(timedResponse([...pings, ...REPLY.map((line) => ({ afterMs: 0, line }))]))
    const pending = collect(run())
    await vi.advanceTimersByTimeAsync(80_000)
    const chunks = await pending
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(chunks[0]).toMatchObject({ type: 'text' })
  })

  it('does not restart a reply that has already begun', async () => {
    fetchMock.mockResolvedValueOnce(timedResponse([
      { afterMs: 0, line: 'data: {"type":"text","content":"Tell me"}\n' },
      { afterMs: 10 ** 9, line: 'data: {"type":"done"}\n' },
    ]))
    const pending = collect(run()).catch((e: Error) => e)
    await vi.advanceTimersByTimeAsync(40_000)
    const result = await pending
    expect(result).toBeInstanceOf(Error)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
