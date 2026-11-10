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

import {
  streamTutorChat, StreamStallError, StreamTruncatedError, TUTOR_RETRY_BUDGET_MS, VOICE_EVENTS_SILENCE_MS, MAX_TRANSCRIBE_UPLOAD_BYTES,
} from './api'
import { startVoiceStream, pushVoiceStreamChunk, finishVoiceStream, streamVoiceEvents, transcribeAudio } from './voiceApi'
import { readerFacingError } from '../utils/networkFailure'
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

/** Runs a promise to completion under fake timers, a second at a time, so a
 *  test of the retry backoff does not have to count its waits. */
async function drive<T>(promise: Promise<T>): Promise<T> {
  let settled = false
  promise.then(() => { settled = true }, () => { settled = true })
  for (let i = 0; i < 300 && !settled; i++) await vi.advanceTimersByTimeAsync(1_000)
  return promise
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
    // The server pings every 3 seconds (routers/voice.py); the client now
    // gives up after 10 seconds of total silence.
    for (let seconds = 0; seconds < 120; seconds += 3) {
      await vi.advanceTimersByTimeAsync(3_000)
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
  beforeEach(() => { vi.useFakeTimers() })

  it('retries, and the child gets the reply they would have lost', async () => {
    fetchMock
      .mockRejectedValueOnce(loadFailed())
      .mockResolvedValueOnce(sseResponse(REPLY))

    const chunks = await drive(collect(run()))

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

    await drive(collect(run()))

    const bodies = fetchMock.mock.calls.map((c) => JSON.parse(c[1].body))
    expect(bodies).toHaveLength(2)
    expect(bodies[0].child_message).toBe('I was coughing the whole day')
    expect(bodies[1]).toEqual(bodies[0])
  })

  it('gives up rather than retrying forever, and reports the real failure', async () => {
    fetchMock.mockRejectedValue(loadFailed())

    await expect(drive(collect(run()))).rejects.toThrow('Load failed')
    expect(fetchMock).toHaveBeenCalledTimes(6)
  })
})

describe('what it deliberately will not retry', () => {
  beforeEach(() => { vi.useFakeTimers() })

  it('leaves a refusal the server actually made alone', async () => {
    // A 4xx/5xx is a decision, not a dropped packet. Repeating it just
    // asks to be refused twice and spends a family's tokens doing it.
    fetchMock.mockResolvedValue(sseResponse([], false, 500))

    await expect(drive(collect(run()))).rejects.toThrow(/Tutor request failed/)
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
      await expect(drive(collect(run()))).rejects.toThrow(/Tutor request failed/)
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
      drive((async () => {
        for await (const c of run()) seen.push(c)
      })()),
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

    await expect(drive(collect(run(controller.signal)))).rejects.toThrow('Aborted')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

// A real demo trace: headers arrived, then no byte at all for 60 seconds, and
// the turn failed. The server sends a keep-alive every 15 seconds while it
// works, so total silence means the connection is gone and asking again is
// the only way the child gets an answer.
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

  it('asks again and the child gets the reply', async () => {
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

// The retry has to outlast a dead zone, not just a blip: three attempts 600ms
// apart gave up within about two seconds, shorter than a tunnel, a lift, or
// a cellular handoff.
describe('a dead zone, not just a blip', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.restoreAllMocks() })

  it('outlasts a 20-second dead zone and the reply still arrives', async () => {
    const t0 = Date.now()
    fetchMock.mockImplementation(async () => {
      if (Date.now() - t0 < 20_000) throw loadFailed()
      return sseResponse(REPLY)
    })
    const chunks = await drive(collect(run()))
    expect(chunks.map((c) => c.type)).toEqual(['text', 'done'])
    expect(fetchMock.mock.calls.length).toBeGreaterThan(3)
  })

  it('waits in widening steps, about 25 seconds in all, then reports the real failure', async () => {
    const t0 = Date.now()
    const at: number[] = []
    fetchMock.mockImplementation(async () => {
      at.push(Date.now() - t0)
      throw loadFailed()
    })
    await expect(drive(collect(run()))).rejects.toThrow('Load failed')
    expect(at).toEqual([0, 1_000, 3_000, 7_000, 15_000, 25_000])
    expect(TUTOR_RETRY_BUDGET_MS).toBeGreaterThanOrEqual(20_000)
    expect(TUTOR_RETRY_BUDGET_MS).toBeLessThanOrEqual(30_000)
  })

  it('waits for the browser to come back online rather than knocking while offline', async () => {
    let online = false
    vi.spyOn(navigator, 'onLine', 'get').mockImplementation(() => online)
    fetchMock.mockRejectedValueOnce(loadFailed()).mockResolvedValueOnce(sseResponse(REPLY))
    const pending = collect(run())
    await vi.advanceTimersByTimeAsync(15_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    online = true
    window.dispatchEvent(new Event('online'))
    const chunks = await pending
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(chunks[0]).toMatchObject({ type: 'text' })
  })

  it('gives up with the real failure once the budget runs out while still offline', async () => {
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
    fetchMock.mockRejectedValue(loadFailed())
    const t0 = Date.now()
    await expect(drive(collect(run()))).rejects.toThrow('Load failed')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(Date.now() - t0).toBeLessThanOrEqual(TUTOR_RETRY_BUDGET_MS + 1_000)
  })

  it('stops waiting for the network when the reader leaves', async () => {
    vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
    fetchMock.mockRejectedValue(loadFailed())
    const controller = new AbortController()
    const pending = collect(run(controller.signal))
    const rejected = expect(pending).rejects.toThrow('Aborted')
    await vi.advanceTimersByTimeAsync(5_000)
    controller.abort()
    await rejected
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

// A body that simply ENDS without `done` was cut off in transit. Treating
// that end as normal made half an answer look complete.
describe('a stream cut off before it finished', () => {
  beforeEach(() => { vi.useFakeTimers() })

  it('is asked again when nothing had been shown yet', async () => {
    fetchMock.mockResolvedValueOnce(sseResponse([': ping\n'])).mockResolvedValueOnce(sseResponse(REPLY))
    const chunks = await drive(collect(run()))
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(chunks.map((c) => c.type)).toEqual(['text', 'done'])
  })

  it('once part of the reply is on screen, is reported as a dropped connection and not replayed', async () => {
    fetchMock.mockResolvedValue(sseResponse(['data: {"type":"text","content":"Well"}\n']))
    const seen: StreamChunk[] = []
    const err = await drive((async () => { for await (const c of run()) seen.push(c) })().then(() => null, (e: unknown) => e))
    expect(err).toBeInstanceOf(StreamTruncatedError)
    expect(seen).toHaveLength(1)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    // What the reader sees is the translated connection message, never the
    // error's English text.
    expect(readerFacingError(err, 'Se perdió la conexión.')).toBe('Se perdió la conexión.')
  })

  it('a final `done` with no trailing newline is still a complete reply', async () => {
    fetchMock.mockResolvedValue(sseResponse(['data: {"type":"text","content":"Hi"}\n', 'data: {"type":"done"}']))
    const chunks = await drive(collect(run()))
    expect(chunks.map((c) => c.type)).toEqual(['text', 'done'])
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('a voice events stream that ends without `done` is a truncation, not a finished turn', async () => {
    fetchMock.mockResolvedValue(sseResponse(['data: {"type":"partial","text":"I was"}\n']))
    const events = streamVoiceEvents('tok', 'synthetic')
    await expect(events.next()).resolves.toMatchObject({ value: { type: 'partial' } })
    await expect(events.next()).rejects.toBeInstanceOf(StreamTruncatedError)
  })
})

describe('the voice events stream gives up on a silent connection quickly', () => {
  it('after ten seconds with no byte at all, not sixty', async () => {
    vi.useFakeTimers()
    fetchMock.mockResolvedValue(new Response(new ReadableStream({ start: () => {} })))
    const events = streamVoiceEvents('tok', 'synthetic')
    const next = events.next()
    let rejected: unknown = null
    next.catch((e) => { rejected = e })
    await vi.advanceTimersByTimeAsync(VOICE_EVENTS_SILENCE_MS - 1)
    expect(rejected).toBeNull()
    await vi.advanceTimersByTimeAsync(1)
    expect(rejected).toBeInstanceOf(StreamStallError)
    expect(VOICE_EVENTS_SILENCE_MS).toBe(10_000)
  })
})

describe('transcribeAudio, the one-shot fallback for a lost voice stream', () => {
  it('sends the whole answer and its language, authenticated, and returns the text', async () => {
    fetchMock.mockResolvedValue(new Response('{"text":"I was coughing","language":"es"}'))
    const wav = new Blob(['RIFF....'], { type: 'audio/wav' })
    await expect(transcribeAudio('tok', wav, 'es')).resolves.toBe('I was coughing')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url as string).toMatch(/\/voice\/transcribe$/)
    expect(init.method).toBe('POST')
    expect(init.headers.Authorization).toBe('Bearer tok')
    const form = init.body as FormData
    expect(form.get('language')).toBe('es')
    expect(form.get('audio')).toBeInstanceOf(Blob)
  })

  it('throws on a refusal rather than returning nothing', async () => {
    fetchMock.mockResolvedValue(new Response('', { status: 413 }))
    await expect(transcribeAudio('tok', new Blob(['x']))).rejects.toThrow('Voice transcription failed')
  })

  it('refuses, without sending, a recording larger than the server accepts', async () => {
    const huge = { size: MAX_TRANSCRIBE_UPLOAD_BYTES + 1 } as Blob
    await expect(transcribeAudio('tok', huge)).rejects.toThrow(/too large/)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('is bounded by a request deadline long enough for a whole answer', async () => {
    vi.useFakeTimers()
    fetchMock.mockImplementation(() => new Promise<Response>(() => {}))
    const pending = transcribeAudio('tok', new Blob(['x']))
    let rejected: unknown = null
    pending.catch((e) => { rejected = e })
    await vi.advanceTimersByTimeAsync(30_000)
    expect(rejected).toBeNull()
    await vi.advanceTimersByTimeAsync(30_000)
    expect((rejected as Error).message).toBe('Request timed out')
    expect((fetchMock.mock.calls[0][1].signal as AbortSignal).aborted).toBe(true)
  })

  it('the longest recording fits under the upload cap', () => {
    // 16kHz 16-bit mono is 32,000 bytes a second, plus a 44-byte WAV header;
    // the hook's ceiling is 120 seconds.
    expect((120_000 / 1000) * 32_000 + 44).toBeLessThan(MAX_TRANSCRIBE_UPLOAD_BYTES)
  })
})
